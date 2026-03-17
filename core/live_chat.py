"""LiveChat – real-time WhatsApp-style group chat server using FastAPI + SSE.

Architecture:
- FastAPI backend serves the chat UI and an SSE endpoint (/stream)
- Orchestrator posts each agent message to a shared asyncio.Queue
- Frontend (vanilla JS) connects to /stream and renders bubbles live
- Every new message is also forwarded to Telegram if configured

Run standalone:
    python -m core.live_chat          # starts on http://localhost:7860
"""
from __future__ import annotations
import asyncio
import json
import time
from typing import AsyncIterator, Optional

try:
    from fastapi import FastAPI
    from fastapi.responses import HTMLResponse, StreamingResponse
    import uvicorn
    _FASTAPI_AVAILABLE = True
except ImportError:
    _FASTAPI_AVAILABLE = False


# ── Global message queue (filled by Orchestrator) ─────────────────────────────
_message_queue: asyncio.Queue = asyncio.Queue()
_message_history: list[dict] = []          # full session log
_MAX_HISTORY = 500


def post_message(agent_name: str, position: str, emoji: str, role_color: str,
                 text: str, msg_type: str = "message") -> None:
    """Called from Orchestrator to push a new message into the live feed."""
    payload = {
        "id":         int(time.time() * 1000),
        "agent":      agent_name,
        "position":   position,
        "emoji":      emoji,
        "color":      role_color,
        "text":       text,
        "type":       msg_type,     # message | divider | pr
        "ts":         time.strftime("%H:%M"),
    }
    _message_history.append(payload)
    if len(_message_history) > _MAX_HISTORY:
        _message_history.pop(0)
    # Non-blocking put (event loop may not be running in sync context)
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(_message_queue.put(payload))
        else:
            _message_queue.put_nowait(payload)
    except RuntimeError:
        _message_queue.put_nowait(payload)


def post_divider(label: str) -> None:
    post_message("system", "", "⚡", "#484f58", label, msg_type="divider")


def clear_history() -> None:
    _message_history.clear()
    while not _message_queue.empty():
        try:
            _message_queue.get_nowait()
        except Exception:
            break


# ── SSE stream ────────────────────────────────────────────────────────────────

async def _event_generator() -> AsyncIterator[str]:
    # First, replay history so a fresh browser connection sees past messages
    for msg in list(_message_history):
        yield f"data: {json.dumps(msg)}\n\n"
    # Then stream new messages
    while True:
        try:
            msg = await asyncio.wait_for(_message_queue.get(), timeout=30)
            yield f"data: {json.dumps(msg)}\n\n"
        except asyncio.TimeoutError:
            yield "data: {\"type\": \"ping\"}\n\n"  # keep-alive


# ── HTML UI ───────────────────────────────────────────────────────────────────

_HTML = """
<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AgentGroup – Live Chat</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:#0d1117;color:#e6edf3;font-family:'Inter',sans-serif;height:100vh;display:flex;flex-direction:column}

  /* Header */
  .header{
    background:rgba(13,17,23,0.9);backdrop-filter:blur(12px);
    border-bottom:1px solid rgba(255,255,255,0.06);
    padding:14px 20px;display:flex;align-items:center;gap:12px;
    position:sticky;top:0;z-index:100;
  }
  .header h1{font-size:1.1rem;font-weight:700;color:#e6edf3}
  .header h1 span{color:#a78bfa}
  .online-dot{width:8px;height:8px;background:#3fb950;border-radius:50%;animation:pulse 2s infinite}
  @keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}
  .agent-badges{display:flex;gap:6px;margin-left:auto;flex-wrap:wrap}
  .badge{
    font-size:.68rem;padding:3px 10px;border-radius:999px;
    border:1px solid rgba(255,255,255,0.1);color:#8b949e;
    display:flex;align-items:center;gap:4px;
  }
  .badge.active{color:#e6edf3;border-color:var(--c)}

  /* Chat area */
  .chat{
    flex:1;overflow-y:auto;padding:20px 16px;
    scrollbar-width:thin;scrollbar-color:rgba(88,70,180,0.4) transparent;
  }
  .chat::-webkit-scrollbar{width:4px}
  .chat::-webkit-scrollbar-thumb{background:rgba(88,70,180,0.4);border-radius:2px}

  /* Divider */
  .divider{
    text-align:center;color:#484f58;font-size:.72rem;
    margin:14px 0;letter-spacing:.08em;text-transform:uppercase;
    border-top:1px solid rgba(33,38,45,0.8);padding-top:8px;
  }

  /* Message row */
  .msg{display:flex;gap:10px;margin-bottom:18px;animation:slideIn .3s cubic-bezier(.22,.68,0,1.2)}
  @keyframes slideIn{from{opacity:0;transform:translateY(12px) scale(.97)}to{opacity:1;transform:none}}

  /* Avatar */
  .avatar{
    width:38px;height:38px;border-radius:50%;
    display:flex;align-items:center;justify-content:center;
    font-size:18px;flex-shrink:0;
    background:linear-gradient(135deg,#1a1f2e,#2d3748);
    position:relative;
  }
  .avatar::before{
    content:'';position:absolute;inset:-2px;border-radius:50%;
    background:conic-gradient(var(--c,#7c3aed),transparent 60%,var(--c,#7c3aed));
    animation:spin 4s linear infinite;z-index:-1;
  }
  @keyframes spin{to{transform:rotate(360deg)}}

  /* Bubble */
  .bubble{
    background:rgba(22,27,34,0.75);border:1px solid rgba(48,54,61,0.7);
    backdrop-filter:blur(6px);border-radius:0 14px 14px 14px;
    padding:10px 14px;max-width:680px;
  }
  .bubble:hover{border-color:rgba(167,139,250,0.25);transform:translateY(-1px);transition:.15s}
  .sender{
    font-weight:700;font-size:.82rem;color:var(--c,#a78bfa);
    display:flex;align-items:center;gap:6px;margin-bottom:4px;
  }
  .role-tag{
    font-size:.65rem;color:#7d8590;background:rgba(33,38,45,0.8);
    border:1px solid rgba(48,54,61,0.6);border-radius:4px;
    padding:1px 6px;font-weight:400;
  }
  .ts{font-size:.65rem;color:#484f58;margin-left:auto}
  .body{font-size:.84rem;line-height:1.65;color:#cdd5de;white-space:pre-wrap}

  /* PR link */
  .pr-banner{
    background:rgba(63,185,80,0.1);border:1px solid rgba(63,185,80,0.3);
    border-radius:10px;padding:10px 16px;margin:10px 0;
    font-size:.85rem;color:#3fb950;
  }
  .pr-banner a{color:#3fb950}

  /* Thinking indicator */
  .thinking{display:flex;gap:4px;margin-top:6px}
  .thinking span{
    width:6px;height:6px;background:#a78bfa;border-radius:50%;
    animation:bounce 1.2s infinite;
  }
  .thinking span:nth-child(2){animation-delay:.2s}
  .thinking span:nth-child(3){animation-delay:.4s}
  @keyframes bounce{0%,80%,100%{transform:scale(0)}40%{transform:scale(1)}}

  /* Status bar */
  .statusbar{
    background:rgba(13,17,23,0.9);border-top:1px solid rgba(255,255,255,0.04);
    padding:8px 20px;font-size:.72rem;color:#484f58;
    display:flex;align-items:center;gap:8px;
  }
  #status-text{color:#8b949e}
</style>
</head>
<body>

<div class="header">
  <div class="online-dot"></div>
  <h1>🤖 AgentGroup <span>Live</span></h1>
  <div class="agent-badges" id="badges"></div>
</div>

<div class="chat" id="chat"></div>

<div class="statusbar">
  <span>⚡</span>
  <span id="status-text">Connecting…</span>
  <span id="msg-count" style="margin-left:auto">0 messages</span>
</div>

<script>
const chat    = document.getElementById('chat');
const statusEl= document.getElementById('status-text');
const countEl = document.getElementById('msg-count');
const badges  = document.getElementById('badges');
let   msgCount = 0;
const knownAgents = {};

function autoScroll(){
  chat.scrollTo({top: chat.scrollHeight, behavior:'smooth'});
}

function addDivider(text){
  const d = document.createElement('div');
  d.className = 'divider';
  d.textContent = text;
  chat.appendChild(d);
  autoScroll();
}

function addMessage(m){
  if(m.type === 'divider'){ addDivider(m.text); return; }
  if(m.type === 'pr'){
    const b = document.createElement('div');
    b.className = 'pr-banner';
    b.innerHTML = `🚀 PR opened: <a href="${m.text}" target="_blank">${m.text}</a>`;
    chat.appendChild(b); autoScroll(); return;
  }
  // Register agent badge
  if(m.agent !== 'system' && !knownAgents[m.agent]){
    knownAgents[m.agent] = m.color;
    const b = document.createElement('div');
    b.className = 'badge active';
    b.style.setProperty('--c', m.color);
    b.innerHTML = `<span>${m.emoji}</span>${m.agent}`;
    badges.appendChild(b);
  }
  const row = document.createElement('div');
  row.className = 'msg';
  row.innerHTML = `
    <div class="avatar" style="--c:${m.color}">${m.emoji}</div>
    <div class="bubble">
      <div class="sender" style="--c:${m.color}">
        ${m.agent}
        <span class="role-tag">${m.position}</span>
        <span class="ts">${m.ts}</span>
      </div>
      <div class="body">${escapeHtml(m.text)}</div>
    </div>`;
  chat.appendChild(row);
  msgCount++;
  countEl.textContent = msgCount + ' messages';
  autoScroll();
}

function escapeHtml(t){
  return t.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

// SSE connection
function connect(){
  const es = new EventSource('/stream');
  es.onopen = () => { statusEl.textContent = 'Connected — waiting for agents…'; };
  es.onmessage = e => {
    const m = JSON.parse(e.data);
    if(m.type === 'ping') return;
    addMessage(m);
  };
  es.onerror = () => {
    statusEl.textContent = 'Reconnecting…';
    es.close();
    setTimeout(connect, 2000);
  };
}
connect();
</script>
</body>
</html>
"""


# ── FastAPI app ───────────────────────────────────────────────────────────────

def create_app() -> "FastAPI":
    if not _FASTAPI_AVAILABLE:
        raise ImportError("fastapi and uvicorn are required for live chat. "
                          "Install with: pip install fastapi uvicorn")
    app = FastAPI(title="AgentGroup Live Chat")

    @app.get("/", response_class=HTMLResponse)
    async def index():
        return HTMLResponse(_HTML)

    @app.get("/stream")
    async def stream():
        return StreamingResponse(
            _event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    @app.get("/history")
    async def history():
        from fastapi.responses import JSONResponse
        return JSONResponse(_message_history)

    @app.post("/clear")
    async def clear():
        clear_history()
        return {"ok": True}

    return app


def run_server(host: str = "0.0.0.0", port: int = 7860) -> None:
    """Start the live chat server (blocking)."""
    app = create_app()
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    run_server()
