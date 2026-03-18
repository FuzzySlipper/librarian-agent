"""FastAPI web server for the Narrative Orchestration System.

Wraps the Orchestrator in an HTTP API with a simple web UI.
Sync SDK calls run in a thread pool to avoid blocking the event loop (ADR-008).
"""

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from functools import partial
from pathlib import Path
from queue import Queue, Empty

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.agents.librarian import Librarian
from src.agents.orchestrator import Mode, Orchestrator
from src.agents.prose_writer import ProseWriter
from src.config import AppConfig, load_config, list_profiles
from src.services.artifacts import (
    build_artifact_prompt, get_current as get_current_artifact,
    set_current as set_current_artifact, clear_current as clear_current_artifact,
    list_artifacts, FORMAT_INSTRUCTIONS,
)
from src.services.council import run_council, format_council_for_orchestrator
from src.services.imagegen import generate_image
from src.services.tts import generate_speech, get_provider_list as get_tts_providers

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

    # Mount portraits directory for serving images
    portraits_dir = Path(_config.paths.portraits)
    if portraits_dir.is_dir():
        app.mount("/portraits", StaticFiles(directory=str(portraits_dir)), name="portraits")
        log.info("Portraits directory mounted: %s", portraits_dir)

    # Mount generated-images directory for serving generated images
    gen_images_dir = Path("generated-images")
    gen_images_dir.mkdir(exist_ok=True)
    app.mount("/generated-images", StaticFiles(directory=str(gen_images_dir)), name="generated-images")
    log.info("Generated images directory mounted: %s", gen_images_dir)

    # Mount layout-images directory for layout background images
    layout_images_dir = Path(_config.paths.layout_images)
    if layout_images_dir.is_dir():
        app.mount("/layout-images", StaticFiles(directory=str(layout_images_dir)), name="layout-images")
        log.info("Layout images directory mounted: %s", layout_images_dir)

    log.info("Agents initialized, server ready")
    yield
    log.info("Server shutting down")


app = FastAPI(title="Narrative System", lifespan=lifespan)

# Serve React frontend static files if available (Docker build copies to static/)
_static_dir = Path(__file__).resolve().parent.parent.parent / "static"
_has_static = _static_dir.is_dir()
if _has_static:
    _assets_dir = _static_dir / "assets"
    if _assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(_assets_dir)), name="static-assets")


def _get_current_portrait() -> str | None:
    """Read the current portrait from the orchestrator's state file."""
    if _orchestrator is None:
        return None
    path = _orchestrator._state_file_path()
    if path is None or not path.exists():
        return None
    try:
        import yaml
        state = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        portrait = state.get("portrait")
        if portrait:
            return f"/portraits/{portrait}"
    except Exception:
        pass
    return None


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    content: str
    response_type: str
    portrait: str | None = None


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
        portrait=_get_current_portrait(),
    )


@app.post("/api/chat/stream")
async def chat_stream(request: ChatRequest):
    """SSE endpoint for streaming chat progress events.

    Events:
      - event: status, data: {"message": "..."}
      - event: tool,   data: {"name": "...", "input": {...}}
      - event: done,   data: {"content": "...", "response_type": "..."}
    """
    if _orchestrator is None:
        return JSONResponse(status_code=503, content={"error": "System not initialized"})

    queue: Queue = Queue()

    def _run_stream():
        """Run the streaming handler in a thread, pushing events to the queue."""
        try:
            for event in _orchestrator.handle_stream(request.message):
                queue.put(event)
        except Exception as e:
            queue.put({"event": "error", "message": str(e)})
        finally:
            queue.put(None)  # Sentinel

    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, _run_stream)

    async def event_generator():
        while True:
            try:
                event = await loop.run_in_executor(None, partial(queue.get, timeout=60))
            except Empty:
                yield "event: ping\ndata: {}\n\n"
                continue

            if event is None:
                break

            event_type = event.pop("event", "status")
            # Attach current portrait to done events
            if event_type == "done":
                event["portrait"] = _get_current_portrait()
            yield f"event: {event_type}\ndata: {json.dumps(event)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
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


@app.post("/api/session/new")
async def new_session():
    """Clear conversation history, starting a fresh session."""
    if _orchestrator is None:
        return JSONResponse(status_code=503, content={"error": "System not initialized"})

    _orchestrator.conversation_history.clear()
    _orchestrator.pending_content = None
    _orchestrator.last_prompt = None

    return {"status": "ok", "message": "Session cleared"}


@app.get("/api/portraits")
async def list_portraits():
    """List available portrait images."""
    if _config is None:
        return JSONResponse(status_code=503, content={"error": "System not initialized"})

    portraits_dir = Path(_config.paths.portraits)
    if not portraits_dir.exists():
        return {"portraits": [], "current": None}

    image_exts = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}
    portraits = []
    for p in sorted(portraits_dir.iterdir()):
        if p.is_file() and p.suffix.lower() in image_exts:
            portraits.append({
                "filename": p.name,
                "url": f"/portraits/{p.name}",
            })

    return {
        "portraits": portraits,
        "current": _get_current_portrait(),
    }


@app.get("/api/lore")
async def list_lore():
    """List all lore files."""
    if _config is None:
        return JSONResponse(status_code=503, content={"error": "System not initialized"})

    lore_path = Path(_config.active_lore_path)
    if not lore_path.exists():
        return {"files": []}

    files = []
    for p in sorted(lore_path.rglob("*.md")):
        rel = str(p.relative_to(lore_path))
        try:
            content = p.read_text(encoding="utf-8")
            # Rough token estimate
            tokens = len(content) // 4
        except Exception:
            content = ""
            tokens = 0
        files.append({"path": rel, "tokens": tokens, "size": len(content)})

    return {"files": files, "lore_path": str(lore_path)}


@app.get("/api/lore/{file_path:path}")
async def read_lore(file_path: str):
    """Read a single lore file."""
    if _config is None:
        return JSONResponse(status_code=503, content={"error": "System not initialized"})

    lore_path = Path(_config.active_lore_path)
    resolved = (lore_path / file_path).resolve()

    # Prevent path traversal
    try:
        resolved.relative_to(lore_path.resolve())
    except ValueError:
        return JSONResponse(status_code=403, content={"error": "Invalid path"})

    if not resolved.exists():
        return JSONResponse(status_code=404, content={"error": "File not found"})

    content = resolved.read_text(encoding="utf-8")
    return {"path": file_path, "content": content, "tokens": len(content) // 4}


class LoreWriteRequest(BaseModel):
    content: str


@app.put("/api/lore/{file_path:path}")
async def write_lore(file_path: str, request: LoreWriteRequest):
    """Write a lore file. Reinitializes the Librarian to pick up changes."""
    global _orchestrator

    if _config is None:
        return JSONResponse(status_code=503, content={"error": "System not initialized"})

    lore_path = Path(_config.active_lore_path)
    resolved = (lore_path / file_path).resolve()

    try:
        resolved.relative_to(lore_path.resolve())
    except ValueError:
        return JSONResponse(status_code=403, content={"error": "Invalid path"})

    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(request.content, encoding="utf-8")

    # Reinitialize agents so Librarian picks up the lore change
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _reinitialize_agents)

    return {"status": "ok", "path": file_path, "tokens": len(request.content) // 4}


# ── Layout endpoints ──────────────────────────────────────────────────


@app.get("/api/layouts")
async def list_layouts():
    """List available layout configs."""
    if _config is None:
        return JSONResponse(status_code=503, content={"error": "System not initialized"})

    layouts_dir = Path(_config.paths.layouts)
    if not layouts_dir.is_dir():
        return {"layouts": []}

    names = sorted(p.stem for p in layouts_dir.glob("*.md"))
    return {"layouts": names}


@app.get("/api/layouts/{name}")
async def get_layout(name: str):
    """Get a layout config by name. Returns the raw MD content."""
    if _config is None:
        return JSONResponse(status_code=503, content={"error": "System not initialized"})

    layouts_dir = Path(_config.paths.layouts)
    path = (layouts_dir / f"{name}.md").resolve()

    # Prevent path traversal
    try:
        path.relative_to(layouts_dir.resolve())
    except ValueError:
        return JSONResponse(status_code=403, content={"error": "Invalid path"})

    if not path.exists():
        return JSONResponse(status_code=404, content={"error": f"Layout '{name}' not found"})

    return {"name": name, "content": path.read_text(encoding="utf-8")}


# ── Artifact endpoints ────────────────────────────────────────────────


class ArtifactRequest(BaseModel):
    prompt: str
    format: str = "prose"


@app.post("/api/artifact")
async def generate_artifact(request: ArtifactRequest):
    """Generate an in-world artifact via the orchestrator. SSE stream."""
    if _orchestrator is None:
        return JSONResponse(status_code=503, content={"error": "System not initialized"})

    artifact_prompt = build_artifact_prompt(request.prompt, request.format)
    queue: Queue = Queue()

    def _run():
        try:
            queue.put({"event": "status", "message": f"Generating {request.format} artifact..."})
            final_content = ""
            for event in _orchestrator.handle_stream(artifact_prompt):
                if event.get("event") == "done":
                    final_content = event.get("content", "")
                    # Store the artifact
                    set_current_artifact({
                        "content": final_content,
                        "format": request.format,
                        "prompt": request.prompt,
                    })
                    # Override the event to mark as artifact
                    event["response_type"] = "artifact"
                queue.put(event)
        except Exception as e:
            queue.put({"event": "error", "message": str(e)})
        finally:
            queue.put(None)

    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, _run)

    async def event_generator():
        while True:
            try:
                event = await loop.run_in_executor(None, partial(queue.get, timeout=120))
            except Empty:
                yield "event: ping\ndata: {}\n\n"
                continue

            if event is None:
                break

            event_type = event.pop("event", "status")
            if event_type == "done":
                event["portrait"] = _get_current_portrait()
            yield f"event: {event_type}\ndata: {json.dumps(event)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/artifact/current")
async def current_artifact():
    """Get the current artifact for panel display."""
    artifact = get_current_artifact()
    if artifact is None:
        return {"artifact": None}
    return {"artifact": artifact}


@app.post("/api/artifact/clear")
async def clear_artifact():
    """Clear the current artifact from the panel."""
    clear_current_artifact()
    return {"status": "ok"}


@app.get("/api/artifact/formats")
async def artifact_formats():
    """List available artifact format types."""
    return {"formats": list(FORMAT_INSTRUCTIONS.keys())}


@app.get("/api/artifact/history")
async def artifact_history():
    """List saved artifacts."""
    return {"artifacts": list_artifacts()}


# ── Council endpoint ──────────────────────────────────────────────────


class CouncilRequest(BaseModel):
    query: str


@app.post("/api/council")
async def council_query(request: CouncilRequest):
    """Run a query through the council and return raw results + orchestrator synthesis.

    The council fan-out runs in a thread pool, then results are fed to the
    orchestrator for synthesis via handle_stream.
    """
    if _orchestrator is None or _config is None:
        return JSONResponse(status_code=503, content={"error": "System not initialized"})

    council_dir = Path(_config.paths.council)

    queue: Queue = Queue()

    def _run():
        try:
            # Step 1: Fan out to council members
            queue.put({"event": "status", "message": "Gathering council responses..."})
            council_result = run_council(request.query, council_dir)

            member_count = len(council_result.get("members", []))
            errors = sum(1 for m in council_result.get("members", []) if m.get("error"))
            queue.put({"event": "status", "message": f"Council returned ({member_count} members, {errors} errors). Synthesizing..."})

            # Step 2: Feed to orchestrator for synthesis
            orchestrator_prompt = format_council_for_orchestrator(council_result)
            for event in _orchestrator.handle_stream(orchestrator_prompt):
                queue.put(event)
        except Exception as e:
            queue.put({"event": "error", "message": str(e)})
        finally:
            queue.put(None)

    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, _run)

    async def event_generator():
        while True:
            try:
                event = await loop.run_in_executor(None, partial(queue.get, timeout=120))
            except Empty:
                yield "event: ping\ndata: {}\n\n"
                continue

            if event is None:
                break

            event_type = event.pop("event", "status")
            if event_type == "done":
                event["portrait"] = _get_current_portrait()
            yield f"event: {event_type}\ndata: {json.dumps(event)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ── Image generation endpoint ────────────────────────────────────────


class ImageRequest(BaseModel):
    prompt: str


@app.post("/api/imagine")
async def imagine(request: ImageRequest):
    """Generate an image from a text prompt. TBD backend."""
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, partial(generate_image, request.prompt))

    if result.success:
        return {
            "status": "ok",
            "image_url": result.image_url,
            "image_path": result.image_path,
            "prompt": result.prompt,
        }
    else:
        return JSONResponse(
            status_code=501,
            content={"status": "not_configured", "error": result.error, "prompt": result.prompt},
        )


# ── TTS endpoints ─────────────────────────────────────────────────────


class TTSRequest(BaseModel):
    text: str


@app.post("/api/tts")
async def tts(request: TTSRequest):
    """Generate speech audio from text. Returns audio stream."""
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, partial(generate_speech, request.text))

    if result.success and result.audio_data:
        from fastapi.responses import Response as RawResponse
        return RawResponse(
            content=result.audio_data,
            media_type=result.content_type,
        )
    else:
        return JSONResponse(
            status_code=501 if "not configured" in (result.error or "").lower() or "No server" in (result.error or "") else 502,
            content={"error": result.error or "TTS generation failed"},
        )


@app.get("/api/tts/providers")
async def tts_providers():
    """List configured TTS providers (so frontend knows if browser-only or server-backed)."""
    providers = get_tts_providers()
    return {
        "providers": providers,
        "has_browser": "browser" in providers,
        "has_server": any(p != "browser" for p in providers),
    }


@app.get("/", response_class=HTMLResponse)
async def index():
    """Serve the chat UI — React build if available, otherwise inline fallback."""
    if _has_static:
        return (_static_dir / "index.html").read_text()
    return HTML_PAGE


# Inline HTML fallback — used when frontend isn't built
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
