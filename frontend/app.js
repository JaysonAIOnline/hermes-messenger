const API = (window.BACKEND || "").replace(/\/$/, "");
let token = localStorage.getItem("hm_token") || "";
let me = null;
let ws = null;
let active = null; // {id, name, type, conversation_id}

const $ = (s) => document.querySelector(s);

function show(el, on) { el.classList.toggle("hidden", !on); }

async function api(path, opts = {}) {
  opts.headers = Object.assign({}, opts.headers, { "Content-Type": "application/json" });
  if (token) opts.headers.Authorization = "Bearer " + token;
  const r = await fetch(API + path, opts);
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
  return r.json();
}

// ---------- Auth ----------
function setMode(signup) {
  $("#tab-login").classList.toggle("active", !signup);
  $("#tab-signup").classList.toggle("active", signup);
  $("#auth-btn").textContent = signup ? "Sign up" : "Login";
  $("#auth-msg").textContent = "";
  window.__signup = signup;
}
$("#tab-login").onclick = () => setMode(false);
$("#tab-signup").onclick = () => setMode(true);

$("#auth-btn").onclick = async () => {
  const username = $("#username").value.trim();
  const password = $("#password").value;
  $("#auth-msg").textContent = "";
  try {
    const data = window.__signup
      ? await api("/api/auth/signup", { method: "POST", body: JSON.stringify({ username, password }) })
      : await api("/api/auth/login", { method: "POST", body: JSON.stringify({ username, password }) });
    token = data.token;
    me = data.username;
    localStorage.setItem("hm_token", token);
    enterApp();
  } catch (e) {
    $("#auth-msg").textContent = e.message;
  }
};

$("#logout").onclick = () => {
  token = ""; localStorage.removeItem("hm_token");
  if (ws) ws.close();
  show($("#app"), false); show($("#auth"), true);
};

// ---------- App ----------
async function enterApp() {
  show($("#auth"), false); show($("#app"), true);
  $("#me").textContent = me;
  connectWs();
  await loadContacts();
}

function connectWs() {
  const backend = window.BACKEND || (location.protocol + "//" + location.host);
  const u = new URL(backend);
  const proto = u.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${u.host}/ws?token=${token}`);
  ws.onmessage = (ev) => {
    const m = JSON.parse(ev.data);
    if (m.type === "ready") renderContacts(m.contacts);
    else if (m.type === "message") onMessage(m);
    else if (m.type === "typing") $("#typing").textContent = "bot is typing…";
  };
  ws.onclose = () => { setTimeout(connectWs, 2000); };
}

let CONTACTS = [];
async function loadContacts() {
  try { const d = await api("/api/contacts"); renderContacts(d.contacts); }
  catch (e) { console.error(e); }
}
function renderContacts(list) {
  CONTACTS = list;
  const q = ($("#search").value || "").toLowerCase();
  $("#contacts").innerHTML = "";
  list.filter(c => c.name.toLowerCase().includes(q)).forEach(c => {
    const li = document.createElement("li");
    li.className = "contact " + c.type;
    li.innerHTML = `<span class="avatar">${c.type === "bot" ? "🤖" : "👤"}</span><span>${c.name}</span>`;
    li.onclick = () => openContact(c);
    $("#contacts").appendChild(li);
  });
}
$("#search").oninput = () => renderContacts(CONTACTS);

async function openContact(c) {
  active = c;
  $("#chat-head").textContent = (c.type === "bot" ? "🤖 " : "") + c.name;
  $("#input").disabled = false; $("#send").disabled = false;
  $("#messages").innerHTML = "";
  try {
    const d = await api("/api/conversations");
    let conv = d.conversations.find(x => x.kind === (c.type === "bot" ? "bot" : "user") && x.other === c.id.slice(2));
    if (conv) { active.conversation_id = conv.id; }
    if (active.conversation_id) {
      const dm = await api(`/api/conversations/${active.conversation_id}/messages`);
      dm.messages.forEach(addBubble);
    }
  } catch (e) { console.error(e); }
}

function addBubble(m) {
  const div = document.createElement("div");
  const mine = m.sender_id && String(m.sender_id) === String(myUid());
  div.className = "bubble " + (mine ? "mine" : (m.sender_id === 0 ? "bot" : "theirs"));
  div.textContent = m.body;
  $("#messages").appendChild(div);
  $("#messages").scrollTop = $("#messages").scrollHeight;
}
function myUid() { return me; } // used only for styling; server is source of truth

function onMessage(m) {
  if (active && m.conversation_id === active.conversation_id) addBubble(m);
  $("#typing").textContent = "";
}

$("#composer").onsubmit = (e) => {
  e.preventDefault();
  send();
};
$("#send").onclick = send;
async function send() {
  const body = $("#input").value.trim();
  if (!body || !active) return;
  $("#input").value = "";
  const payload = { to: active.id, body, kind: active.type };
  // optimistic local bubble
  addBubble({ sender_id: me, body, conversation_id: active.conversation_id || 0 });
  try {
    if (ws && ws.readyState === 1) {
      ws.send(JSON.stringify({ type: "send", to: active.id, body }));
    } else {
      await api("/api/send", { method: "POST", body: JSON.stringify(payload) });
    }
  } catch (e) { console.error(e); }
}

if (token) { /* auto-login would need /api/me; for now require re-login */ }
