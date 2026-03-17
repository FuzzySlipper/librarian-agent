"""FastAPI web server for the Narrative Orchestration System.

Wraps the Orchestrator in an HTTP API with a simple web UI.
Sync SDK calls run in a thread pool to avoid blocking the event loop (ADR-008).
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from functools import partial
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.agents.librarian import Librarian
from src.agents.orchestrator import Mode, Orchestrator
from src.agents.prose_writer import ProseWriter
from src.config import AppConfig, load_config, list_profiles

log = logging.getLogger(__name__)

# Global references set during lifespan
_orchestrator: Orchestrator | None = None
_config: AppConfig | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize agents on startup."""
    global _orchestrator, _config

    config_path = Path(app.state.config_path) if hasattr(app.state, "config_path") else Path("config.yaml")
    env_path = Path(app.state.env_path) if hasattr(app.state, "env_path") else None

    _config = load_config(config_path=config_path, env_path=env_path)
    librarian = Librarian(_config)
    writer = ProseWriter(librarian, _config)
    _orchestrator = Orchestrator(librarian, writer, _config)

    log.info("Agents initialized, server ready")
    yield
    log.info("Server shutting down")


app = FastAPI(title="Narrative System", lifespan=lifespan)


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    content: str
    response_type: str


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """Handle a chat message through the Orchestrator."""
    if _orchestrator is None:
        return JSONResponse(status_code=503, content={"error": "System not initialized"})

    # Run sync Orchestrator in thread pool to avoid blocking
    loop = asyncio.get_event_loop()
    response = await loop.run_in_executor(
        None,
        partial(_orchestrator.handle, request.message),
    )

    return ChatResponse(
        content=response.content,
        response_type=response.response_type,
    )


@app.get("/api/status")
async def status():
    """Health check and system status."""
    if _orchestrator is None or _config is None:
        return {"status": "initializing"}

    return {
        "status": "ready",
        "mode": _orchestrator.mode.value,
        "project": _orchestrator.active_project,
        "file": _orchestrator.active_file,
        "lore_files": len(_orchestrator.librarian.lore),
        "lore_set": _config.lore.active or "(default)",
        "persona": _config.persona.active or "(default)",
        "writing_style": _config.writing_style.active,
        "model": _config.models.orchestrator,
        "conversation_turns": len(_orchestrator.conversation_history) // 2,
    }


@app.get("/api/profiles")
async def profiles():
    """List available persona and lore profiles."""
    if _config is None:
        return JSONResponse(status_code=503, content={"error": "System not initialized"})

    discovered = list_profiles(_config)
    return {
        "personas": discovered["personas"],
        "lore_sets": discovered["lore_sets"],
        "writing_styles": discovered["writing_styles"],
        "active_persona": _config.persona.active or "(default)",
        "active_lore": _config.lore.active or "(default)",
        "active_writing_style": _config.writing_style.active,
    }


class ProfileRequest(BaseModel):
    persona: str | None = None
    lore_set: str | None = None
    writing_style: str | None = None


@app.post("/api/profiles/switch")
async def switch_profile(request: ProfileRequest):
    """Switch active persona, lore set, and/or writing style. Reinitializes agents."""
    global _orchestrator, _config

    if _config is None:
        return JSONResponse(status_code=503, content={"error": "System not initialized"})

    # Update config
    if request.persona is not None:
        _config.persona.active = None if request.persona == "(default)" else request.persona
    if request.lore_set is not None:
        _config.lore.active = None if request.lore_set == "(default)" else request.lore_set
    if request.writing_style is not None:
        _config.writing_style.active = request.writing_style

    # Reinitialize agents with new profile
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _reinitialize_agents)

    return {
        "status": "ok",
        "active_persona": _config.persona.active or "(default)",
        "active_lore": _config.lore.active or "(default)",
        "active_writing_style": _config.writing_style.active,
        "lore_files": len(_orchestrator.librarian.lore) if _orchestrator else 0,
    }


def _reinitialize_agents():
    """Rebuild the agent chain with current config. Runs in thread pool."""
    global _orchestrator
    librarian = Librarian(_config)
    writer = ProseWriter(librarian, _config)
    _orchestrator = Orchestrator(librarian, writer, _config)
    log.info(
        "Agents reinitialized: persona=%s, lore=%s",
        _config.persona.active or "(default)",
        _config.lore.active or "(default)",
    )


class ModeRequest(BaseModel):
    mode: str  # "general", "writer", "roleplay"
    project: str | None = None
    file: str | None = None


@app.post("/api/mode")
async def set_mode(request: ModeRequest):
    """Switch operating mode and optionally set active project/file."""
    if _orchestrator is None:
        return JSONResponse(status_code=503, content={"error": "System not initialized"})

    try:
        mode = Mode(request.mode)
    except ValueError:
        return JSONResponse(status_code=400, content={
            "error": f"Invalid mode: {request.mode}. Must be general, writer, or roleplay."
        })

    result = _orchestrator.set_mode(mode, project=request.project, file=request.file)
    return result


@app.get("/api/mode")
async def get_mode():
    """Get current mode and active project/file."""
    if _orchestrator is None:
        return JSONResponse(status_code=503, content={"error": "System not initialized"})

    return {
        "mode": _orchestrator.mode.value,
        "project": _orchestrator.active_project,
        "file": _orchestrator.active_file,
        "pending_content": _orchestrator.pending_content is not None,
    }


@app.get("/api/projects")
async def get_projects():
    """List available projects for the current mode."""
    if _orchestrator is None:
        return JSONResponse(status_code=503, content={"error": "System not initialized"})

    return _orchestrator.list_projects()


@app.get("/", response_class=HTMLResponse)
async def index():
    """Serve the chat UI."""
    return HTML_PAGE


# Inline HTML — single-file UI, no build step, mobile-friendly
HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<title>Narrative System</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }

  :root {
    --bg: #1a1a2e;
    --surface: #16213e;
    --surface-alt: #0f3460;
    --text: #e0e0e0;
    --text-muted: #888;
    --accent: #e94560;
    --input-bg: #222244;
    --border: #333355;
  }

  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: var(--bg);
    color: var(--text);
    height: 100dvh;
    display: flex;
    flex-direction: column;
  }

  header {
    padding: 12px 16px;
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-shrink: 0;
  }

  header h1 {
    font-size: 16px;
    font-weight: 600;
  }

  #status {
    font-size: 12px;
    color: var(--text-muted);
  }

  #messages {
    flex: 1;
    overflow-y: auto;
    padding: 16px;
    display: flex;
    flex-direction: column;
    gap: 12px;
    -webkit-overflow-scrolling: touch;
  }

  .message {
    max-width: 85%;
    padding: 10px 14px;
    border-radius: 12px;
    line-height: 1.5;
    font-size: 15px;
    white-space: pre-wrap;
    word-wrap: break-word;
  }

  .message.user {
    background: var(--surface-alt);
    align-self: flex-end;
    border-bottom-right-radius: 4px;
  }

  .message.assistant {
    background: var(--surface);
    align-self: flex-start;
    border-bottom-left-radius: 4px;
  }

  .message.assistant.prose {
    border-left: 3px solid var(--accent);
  }

  .message .type-badge {
    display: inline-block;
    font-size: 10px;
    text-transform: uppercase;
    color: var(--accent);
    margin-bottom: 4px;
    letter-spacing: 0.5px;
  }

  #input-area {
    padding: 12px 16px;
    background: var(--surface);
    border-top: 1px solid var(--border);
    display: flex;
    gap: 8px;
    flex-shrink: 0;
  }

  #input-area textarea {
    flex: 1;
    background: var(--input-bg);
    color: var(--text);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 10px 12px;
    font-size: 15px;
    font-family: inherit;
    resize: none;
    min-height: 44px;
    max-height: 120px;
    line-height: 1.4;
  }

  #input-area textarea:focus {
    outline: none;
    border-color: var(--accent);
  }

  #input-area button {
    background: var(--accent);
    color: white;
    border: none;
    border-radius: 8px;
    padding: 0 16px;
    font-size: 15px;
    font-weight: 600;
    cursor: pointer;
    flex-shrink: 0;
    min-height: 44px;
  }

  #input-area button:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .thinking {
    color: var(--text-muted);
    font-style: italic;
    align-self: flex-start;
    padding: 8px 14px;
  }

  @media (max-width: 600px) {
    .message { max-width: 92%; }
  }
</style>
</head>
<body>

<header>
  <h1>Narrative System</h1>
  <span id="status">connecting...</span>
</header>

<div id="messages"></div>

<div id="input-area">
  <textarea id="input" rows="1" placeholder="Say something..." autofocus></textarea>
  <button id="send" onclick="sendMessage()">Send</button>
</div>

<script>
const messagesEl = document.getElementById('messages');
const inputEl = document.getElementById('input');
const sendBtn = document.getElementById('send');
const statusEl = document.getElementById('status');

// Auto-resize textarea
inputEl.addEventListener('input', () => {
  inputEl.style.height = 'auto';
  inputEl.style.height = Math.min(inputEl.scrollHeight, 120) + 'px';
});

// Enter to send, Shift+Enter for newline
inputEl.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
});

function addMessage(text, role, type) {
  const div = document.createElement('div');
  div.className = `message ${role}` + (type === 'prose' ? ' prose' : '');

  if (role === 'assistant' && type && type !== 'discussion') {
    const badge = document.createElement('div');
    badge.className = 'type-badge';
    badge.textContent = type;
    div.appendChild(badge);
  }

  const content = document.createElement('div');
  content.textContent = text;
  div.appendChild(content);

  messagesEl.appendChild(div);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function setThinking(on) {
  const existing = document.querySelector('.thinking');
  if (existing) existing.remove();
  if (on) {
    const div = document.createElement('div');
    div.className = 'thinking';
    div.textContent = 'thinking...';
    messagesEl.appendChild(div);
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }
}

async function sendMessage() {
  const text = inputEl.value.trim();
  if (!text) return;

  inputEl.value = '';
  inputEl.style.height = 'auto';
  sendBtn.disabled = true;

  addMessage(text, 'user');
  setThinking(true);

  try {
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text }),
    });

    setThinking(false);

    if (!res.ok) {
      addMessage('Error: ' + res.statusText, 'assistant', 'error');
      return;
    }

    const data = await res.json();
    addMessage(data.content, 'assistant', data.response_type);
  } catch (err) {
    setThinking(false);
    addMessage('Connection error: ' + err.message, 'assistant', 'error');
  } finally {
    sendBtn.disabled = false;
    inputEl.focus();
  }
}

// Check status on load
async function checkStatus() {
  try {
    const res = await fetch('/api/status');
    const data = await res.json();
    if (data.status === 'ready') {
      statusEl.textContent = `${data.lore_files} lore files loaded`;
    } else {
      statusEl.textContent = data.status;
    }
  } catch {
    statusEl.textContent = 'offline';
  }
}

checkStatus();
</script>
</body>
</html>"""
