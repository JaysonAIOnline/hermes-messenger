"""
Hermes Messenger — backend.

A small FastAPI service that provides:
  * account system (signup / login) with opaque bearer tokens
  * real-time user-to-user messaging over WebSocket
  * "bot" contacts that proxy messages to a local Hermes agent via the
    `hermes chat` CLI (each bot contact keeps a persistent named session)

Run:  uvicorn server:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sqlite3
import secrets
import time
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent
DB_PATH = os.environ.get("MESSENGER_DB", str(ROOT / "messenger.db"))
HERMES_BIN = os.environ.get("HERMES_BIN", "hermes")
# Bot contacts. Each may carry an optional Hermes profile (`-p <profile>`).
BOTS = json.loads(os.environ.get("MESSENGER_BOTS", '[{"id":"hermes","name":"Hermes","profile":""}]'))
BOT_TIMEOUT = int(os.environ.get("MESSENGER_BOT_TIMEOUT", "300"))

app = FastAPI(title="Hermes Messenger")

# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def db() -> sqlite3.Connection:
    cx = sqlite3.connect(DB_PATH)
    cx.row_factory = sqlite3.Row
    return cx

def init_db() -> None:
    cx = db()
    cx.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            pw_salt TEXT NOT NULL,
            pw_hash TEXT NOT NULL,
            created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS tokens (
            token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL,           -- 'user' | 'bot'
            user_a INTEGER NOT NULL,
            other TEXT NOT NULL,          -- other user id (as text) or bot id
            created_at REAL NOT NULL,
            UNIQUE(kind, user_a, other)
        );
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER NOT NULL,
            sender_id INTEGER NOT NULL,   -- 0 for bot/system
            body TEXT NOT NULL,
            created_at REAL NOT NULL
        );
        """
    )
    cx.commit()
    cx.close()

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def hash_pw(password: str) -> tuple[str, str]:
    salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 100_000).hex()
    return salt, h

def verify_pw(password: str, salt: str, h: str) -> bool:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 100_000).hex() == h

def uid_from_token(token: str) -> Optional[int]:
    cx = db()
    row = cx.execute("SELECT user_id FROM tokens WHERE token=?", (token,)).fetchone()
    cx.close()
    return row["user_id"] if row else None

def get_token_from_header(authorization: str | None) -> str | None:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    return authorization[7:].strip()

# HTTP routes use a Request-based dependency.
from fastapi import Request

async def auth_uid(request: Request) -> int:
    tok = get_token_from_header(request.headers.get("Authorization"))
    if not tok:
        raise HTTPException(status_code=401, detail="missing token")
    uid = uid_from_token(tok)
    if not uid:
        raise HTTPException(status_code=401, detail="invalid token")
    return uid

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class Signup(BaseModel):
    username: str
    password: str

class Login(BaseModel):
    username: str
    password: str

class SendMsg(BaseModel):
    to: str          # username (user) or bot id
    body: str
    kind: str = "auto"  # 'user' | 'bot' | 'auto'

# ---------------------------------------------------------------------------
# Connection registry (for real-time delivery)
# ---------------------------------------------------------------------------

conns: dict[int, list[WebSocket]] = {}

def contact_list(for_uid: int) -> list[dict]:
    cx = db()
    users = cx.execute(
        "SELECT id, username FROM users WHERE id != ? ORDER BY username", (for_uid,)
    ).fetchall()
    cx.close()
    out = [{"id": f"u:{u['id']}", "name": u["username"], "type": "user"} for u in users]
    for b in BOTS:
        out.append({"id": f"b:{b['id']}", "name": b["name"], "type": "bot"})
    return out

def ensure_conversation(kind: str, uid: int, other: str) -> int:
    cx = db()
    row = cx.execute(
        "SELECT id FROM conversations WHERE kind=? AND user_a=? AND other=?",
        (kind, uid, other),
    ).fetchone()
    if row:
        cid = row["id"]
    else:
        cur = cx.execute(
            "INSERT INTO conversations (kind, user_a, other, created_at) VALUES (?,?,?,?)",
            (kind, uid, other, time.time()),
        )
        cid = cur.lastrowid
    cx.commit()
    cx.close()
    return cid

async def persist_and_deliver(conversation_id: int, sender_id: int, body: str, to_uid: int | None):
    cx = db()
    cur = cx.execute(
        "INSERT INTO messages (conversation_id, sender_id, body, created_at) VALUES (?,?,?,?)",
        (conversation_id, sender_id, body, time.time()),
    )
    mid = cur.lastrowid
    cx.commit()
    cx.close()
    payload = {"type": "message", "conversation_id": conversation_id, "sender_id": sender_id,
               "body": body, "message_id": mid, "ts": time.time()}
    if to_uid is not None:
        for ws in conns.get(to_uid, []):
            try:
                await ws.send_json(payload)
            except Exception:
                pass

# ---------------------------------------------------------------------------
# Hermes bridge
# ---------------------------------------------------------------------------

async def ask_hermes(app_username: str, bot: dict, message: str) -> str:
    safe = "".join(c if c.isalnum() else "-" for c in app_username)
    session = f"msgapp-{safe}-{bot['id']}"
    profile = bot.get("profile", "")
    cmd = [HERMES_BIN]
    if profile:
        cmd += ["-p", profile]
    cmd += ["chat", "-Q", "--continue", session, "--create-if-missing", "-q", message]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        out, err = await asyncio.wait_for(proc.communicate(), timeout=BOT_TIMEOUT)
    except asyncio.TimeoutError:
        return "(Hermes did not respond in time — try again later.)"
    except FileNotFoundError:
        return "(Hermes CLI not found on this host.)"
    text = (out or b"").decode("utf-8", "replace")
    # `-Q` prints the final response then a short session footer; keep the response.
    if "Session:" in text:
        text = text.split("Session:")[0]
    return text.strip() or "(no response)"

# ---------------------------------------------------------------------------
# HTTP routes
# ---------------------------------------------------------------------------

@app.post("/api/auth/signup")
async def signup(body: Signup):
    username = body.username.strip()
    if not username or len(username) < 2:
        raise HTTPException(400, "username too short")
    salt, h = hash_pw(body.password)
    cx = db()
    try:
        cur = cx.execute(
            "INSERT INTO users (username, pw_salt, pw_hash, created_at) VALUES (?,?,?,?)",
            (username, salt, h, time.time()),
        )
        uid = cur.lastrowid
        cx.commit()
    except sqlite3.IntegrityError:
        cx.close()
        raise HTTPException(409, "username taken")
    token = secrets.token_urlsafe(32)
    cx.execute("INSERT INTO tokens (token, user_id, created_at) VALUES (?,?,?)", (token, uid, time.time()))
    cx.commit()
    cx.close()
    return {"token": token, "username": username, "user_id": uid}

@app.post("/api/auth/login")
async def login(body: Login):
    cx = db()
    row = cx.execute("SELECT * FROM users WHERE username=?", (body.username.strip(),)).fetchone()
    cx.close()
    if not row or not verify_pw(body.password, row["pw_salt"], row["pw_hash"]):
        raise HTTPException(401, "bad credentials")
    token = secrets.token_urlsafe(32)
    cx = db()
    cx.execute("INSERT INTO tokens (token, user_id, created_at) VALUES (?,?,?)", (token, row["id"], time.time()))
    cx.commit()
    cx.close()
    return {"token": token, "username": row["username"], "user_id": row["id"]}

@app.get("/api/contacts")
async def contacts(uid: int = Depends(auth_uid)):
    return {"contacts": contact_list(uid)}

@app.get("/api/conversations")
async def conversations(uid: int = Depends(auth_uid)):
    cx = db()
    rows = cx.execute(
        "SELECT id, kind, other, created_at FROM conversations WHERE user_a=? ORDER BY created_at DESC",
        (uid,),
    ).fetchall()
    cx.close()
    return {"conversations": [dict(r) for r in rows]}

@app.get("/api/conversations/{cid}/messages")
async def conv_messages(cid: int, uid: int = Depends(auth_uid)):
    cx = db()
    conv = cx.execute("SELECT * FROM conversations WHERE id=? AND user_a=?", (cid, uid)).fetchone()
    if not conv:
        cx.close()
        raise HTTPException(404, "no such conversation")
    rows = cx.execute(
        "SELECT id, sender_id, body, created_at FROM messages WHERE conversation_id=? ORDER BY id ASC",
        (cid,),
    ).fetchall()
    cx.close()
    return {"messages": [dict(r) for r in rows]}

@app.post("/api/send")
async def send(body: SendMsg, uid: int = Depends(auth_uid)):
    if not body.body.strip():
        raise HTTPException(400, "empty message")
    kind = body.kind
    if kind == "auto":
        kind = "bot" if body.to.startswith("b:") else "user"
    other = body.to[2:] if body.to.startswith(("u:", "b:")) else body.to
    cid = ensure_conversation(kind, uid, other)
    # persist sender message
    cx = db()
    cur = cx.execute(
        "INSERT INTO messages (conversation_id, sender_id, body, created_at) VALUES (?,?,?,?)",
        (cid, uid, body.body, time.time()),
    )
    mid = cur.lastrowid
    cx.commit()
    cx.close()
    if kind == "user":
        try:
            other_uid = int(other)
        except ValueError:
            other_uid = None
        if other_uid:
            for ws in conns.get(other_uid, []):
                try:
                    await ws.send_json({"type": "message", "conversation_id": cid,
                                        "sender_id": uid, "body": body.body, "message_id": mid, "ts": time.time()})
                except Exception:
                    pass
        return {"ok": True, "conversation_id": cid, "message_id": mid}
    else:
        # bot contact
        bot = next((b for b in BOTS if b["id"] == other), None)
        if not bot:
            raise HTTPException(404, "unknown bot")
        # notify sender we're thinking
        for ws in conns.get(uid, []):
            try:
                await ws.send_json({"type": "typing", "conversation_id": cid, "from": "bot"})
            except Exception:
                pass
        username = (await _username(uid))
        reply = await ask_hermes(username, bot, body.body)
        await persist_and_deliver(cid, 0, reply, uid)
        for ws in conns.get(uid, []):
            try:
                await ws.send_json({"type": "message", "conversation_id": cid,
                                    "sender_id": 0, "body": reply, "message_id": mid, "ts": time.time()})
            except Exception:
                pass
        return {"ok": True, "conversation_id": cid, "message_id": mid, "reply": reply}

async def _username(uid: int) -> str:
    cx = db()
    row = cx.execute("SELECT username FROM users WHERE id=?", (uid,)).fetchone()
    cx.close()
    return row["username"] if row else f"user{uid}"

# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------

@app.websocket("/ws")
async def ws(websocket: WebSocket):
    await websocket.accept()
    token = websocket.query_params.get("token")
    uid = uid_from_token(token) if token else None
    if not uid:
        await websocket.send_json({"type": "error", "detail": "unauthorized"})
        await websocket.close()
        return
    conns.setdefault(uid, []).append(websocket)
    try:
        await websocket.send_json({"type": "ready", "contacts": contact_list(uid)})
        while True:
            data = await websocket.receive_json()
            # client may send {type:'send', to, body} for symmetry
            if data.get("type") == "send":
                to = data.get("to", "")
                body = data.get("body", "")
                if not body.strip():
                    continue
                kind = "bot" if to.startswith("b:") else "user"
                other = to[2:] if to.startswith(("u:", "b:")) else to
                cid = ensure_conversation(kind, uid, other)
                cx = db()
                cur = cx.execute(
                    "INSERT INTO messages (conversation_id, sender_id, body, created_at) VALUES (?,?,?,?)",
                    (cid, uid, body, time.time()),
                )
                mid = cur.lastrowid
                cx.commit()
                cx.close()
                if kind == "user":
                    try:
                        ou = int(other)
                    except ValueError:
                        ou = None
                    if ou:
                        for ws in conns.get(ou, []):
                            try:
                                await ws.send_json({"type": "message", "conversation_id": cid,
                                                    "sender_id": uid, "body": body, "message_id": mid, "ts": time.time()})
                            except Exception:
                                pass
                else:
                    bot = next((b for b in BOTS if b["id"] == other), None)
                    if bot:
                        for ws in conns.get(uid, []):
                            try:
                                await ws.send_json({"type": "typing", "conversation_id": cid, "from": "bot"})
                            except Exception:
                                pass
                        uname = await _username(uid)
                        reply = await ask_hermes(uname, bot, body)
                        await persist_and_deliver(cid, 0, reply, uid)
                        for ws in conns.get(uid, []):
                            try:
                                await ws.send_json({"type": "message", "conversation_id": cid,
                                                    "sender_id": 0, "body": reply, "message_id": mid, "ts": time.time()})
                            except Exception:
                                pass
    except WebSocketDisconnect:
        pass
    finally:
        if websocket in conns.get(uid, []):
            conns[uid].remove(websocket)

# ---------------------------------------------------------------------------
# Static frontend
# ---------------------------------------------------------------------------

FRONTEND = ROOT / "frontend"
if FRONTEND.exists():
    @app.get("/")
    async def index():
        return FileResponse(str(FRONTEND / "index.html"))

    @app.get("/manifest.webmanifest")
    async def manifest():
        return FileResponse(str(FRONTEND / "manifest.webmanifest"))

    @app.get("/sw.js")
    async def sw():
        return FileResponse(str(FRONTEND / "sw.js"), headers={"Cache-Control": "no-cache"})

    app.mount("/", StaticFiles(directory=str(FRONTEND), html=True), name="static")

init_db()
