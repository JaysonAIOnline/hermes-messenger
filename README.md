# Hermes Messenger

A small, self-hosted **messenger** web app (installable PWA) that lets you:

* **Chat with other people** who sign up (real-time, over WebSocket).
* **Chat with your Hermes bots as contacts** — every bot contact is a persistent
  Hermes session. Messages are forwarded to the local `hermes` CLI and the reply
  is streamed back into the conversation.
* Run on your **LAN** and expose it safely through a **Cloudflare tunnel** so your
  phone (e.g. a Samsung S24 Ultra) can reach it from anywhere.
* Install to the home screen like a native app (PWA: manifest + service worker).

## Architecture

```
frontend/  Static PWA (index.html, app.js, styles.css, sw.js, manifest)
backend/   FastAPI service: accounts, WebSocket relay, SQLite store, Hermes bridge
```

The Hermes bridge calls `hermes chat -Q --continue <session> --create-if-missing -q <msg>`
per bot contact, so each contact keeps its own conversation memory.

## Quick start (local)

```bash
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
export MESSENGER_DB=messenger.db
# optional: MESSENGER_BOTS='[{"id":"hermes","name":"Hermes","profile":""}]'
uvicorn server:app --host 0.0.0.0 --port 8000
```

Open http://localhost:8000 , sign up, and start chatting.

## Docker

```bash
docker build -t hermes-messenger .
docker run -p 8000:8000 \
  -e MESSENGER_BOTS='[{"id":"hermes","name":"Hermes"}]' \
  -v $(pwd)/data:/data \
  hermes-messenger
```

`docker-compose.yml` is provided as well.

## Expose to your phone (Cloudflare tunnel)

```bash
cloudflared tunnel --url http://localhost:8000
```

Use the printed `https://*.trycloudflare.com` URL on your phone, then **Add to Home
Screen** to install the PWA. For a stable URL, create a named Cloudflare tunnel.

## Configuration

| Env var                  | Default | Meaning                                    |
|--------------------------|---------|--------------------------------------------|
| `MESSENGER_DB`           | `messenger.db` | Path to the SQLite database file     |
| `MESSENGER_BOTS`         | `[{"id":"hermes","name":"Hermes"}]` | JSON array of bot contacts |
| `MESSENGER_BOT_TIMEOUT`  | `300`   | Seconds to wait for a Hermes reply         |
| `HERMES_BIN`             | `hermes` | Path to the Hermes CLI                  |

A bot entry: `{"id":"hermes","name":"Hermes","profile":""}`. Set `profile` to a
Hermes profile name to talk to one of your bot profiles (`hermes -p <profile>`).

## Security notes

* Passwords are hashed with PBKDF2-SHA256. Tokens are opaque and stored in the DB.
* This is a personal/hobby server: put it behind TLS (the Cloudflare tunnel does
  this) and do not expose the port directly to the public internet without auth.
* The Hermes CLI runs locally on the host; only the host's `hermes` account is
  used for bot replies.

## License

MIT — see LICENSE.
