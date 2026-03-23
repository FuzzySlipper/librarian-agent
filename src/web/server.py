"""FastAPI web server for the Narrative Orchestration System.

Wraps the Orchestrator in an HTTP API with a simple web UI.
Sync SDK calls run in a thread pool to avoid blocking the event loop (ADR-008).
"""

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from functools import partial
from pathlib import Path
from queue import Queue, Empty

from fastapi import FastAPI, Request, UploadFile
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
from src.providers import ProviderRegistry

log = logging.getLogger(__name__)

# Global references set during lifespan
_orchestrator: Orchestrator | None = None
_config: AppConfig | None = None
_registry: ProviderRegistry | None = None
_current_session_id: str | None = None


# ── Session persistence helpers ──────────────────────────────────────

def _sessions_dir() -> Path:
    """Return the sessions directory, creating it if needed."""
    d = Path(_config.paths.data) / "sessions" if _config else Path("build/data/sessions")
    d.mkdir(parents=True, exist_ok=True)
    return d


def _generate_session_id() -> str:
    """Create a timestamp-based session ID."""
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _auto_name_session(history: list[dict]) -> str:
    """Generate a short name from the first user message."""
    for msg in history:
        if msg.get("role") == "user":
            text = msg["content"]
            # First 60 chars, cleaned up
            name = text[:60].strip().replace("\n", " ")
            if len(text) > 60:
                name += "..."
            return name
    return "empty session"


def _save_session(session_id: str, history: list[dict], mode: str):
    """Write session to disk."""
    if not history:
        return
    path = _sessions_dir() / f"{session_id}.json"
    data = {
        "id": session_id,
        "name": _auto_name_session(history),
        "mode": mode,
        "turns": len(history) // 2,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "messages": history,
    }
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _auto_save():
    """Save current session if there's history."""
    global _current_session_id
    if _orchestrator is None:
        return
    if not _orchestrator.conversation_history:
        return
    if _current_session_id is None:
        _current_session_id = _generate_session_id()
    _save_session(_current_session_id, _orchestrator.conversation_history, _orchestrator.mode.value)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize agents on startup."""
    global _orchestrator, _config, _registry

    config_path = Path(app.state.config_path) if hasattr(app.state, "config_path") else Path(os.environ.get("CONFIG_PATH", "build/config.yaml"))
    env_path = Path(app.state.env_path) if hasattr(app.state, "env_path") else None

    _config = load_config(config_path=config_path, env_path=env_path)
    _registry = ProviderRegistry(Path(_config.paths.data), user_agent=_config.user_agent)

    librarian = _create_agent_with_registry(Librarian, _config, _config.models.librarian)
    writer = _create_writer_with_registry(librarian, _config)
    _orchestrator = _create_orchestrator_with_registry(librarian, writer, _config)

    # Mount portraits directory for serving images
    portraits_dir = Path(_config.paths.portraits)
    if portraits_dir.is_dir():
        app.mount("/portraits", StaticFiles(directory=str(portraits_dir)), name="portraits")
        log.info("Portraits directory mounted: %s", portraits_dir)

    # Mount backgrounds directory for serving background images
    backgrounds_dir = Path(_config.paths.backgrounds)
    if backgrounds_dir.is_dir():
        app.mount("/backgrounds", StaticFiles(directory=str(backgrounds_dir)), name="backgrounds")
        log.info("Backgrounds directory mounted: %s", backgrounds_dir)

    # Mount generated-images directory for serving generated images
    gen_images_dir = Path(os.environ.get("IMAGE_OUTPUT_DIR", "build/generated-images"))
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
    """Get the AI character portrait. Checks: state file → active character card."""
    # First check state file (can be set per-scene)
    if _orchestrator is not None:
        path = _orchestrator._state_file_path()
        if path is not None and path.exists():
            try:
                import yaml
                state = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                portrait = state.get("portrait")
                if portrait:
                    return f"/portraits/{portrait}"
            except Exception:
                pass

    # Fall back to active AI character card portrait
    if _config and _config.roleplay.ai_character:
        from src.character_cards import load_card
        card = load_card(Path(_config.paths.character_cards) / f"{_config.roleplay.ai_character}.yaml")
        if card and card.get("portrait"):
            return f"/portraits/{card['portrait']}"

    return None


def _get_user_portrait() -> str | None:
    """Get the user character portrait from the active user character card."""
    if _config and _config.roleplay.user_character:
        from src.character_cards import load_card
        card = load_card(Path(_config.paths.character_cards) / f"{_config.roleplay.user_character}.yaml")
        if card and card.get("portrait"):
            return f"/portraits/{card['portrait']}"
    return None


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    content: str
    response_type: str
    portrait: str | None = None
    user_portrait: str | None = None


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

    _auto_save()

    return ChatResponse(
        content=response.content,
        response_type=response.response_type,
        portrait=_get_current_portrait(),
        user_portrait=_get_user_portrait(),
    )


@app.post("/api/chat/stream")
async def chat_stream(request: ChatRequest):
    """SSE endpoint for streaming chat progress events.

    Events:
      - event: status,          data: {"message": "..."}
      - event: tool,            data: {"name": "...", "input": {...}}
      - event: text_delta,      data: {"text": "..."}   — partial text chunk
      - event: reasoning_delta, data: {"text": "..."}   — partial reasoning chunk
      - event: done,            data: {"content": "...", "response_type": "...", "reasoning": "..."}
    """
    if _orchestrator is None:
        return JSONResponse(status_code=503, content={"error": "System not initialized"})

    queue: Queue = Queue()

    def _run_stream():
        """Run the streaming handler in a thread, pushing events to the queue."""
        try:
            for event in _orchestrator.handle_stream(request.message):
                queue.put(event)
                # Auto-save after completed responses and tool executions
                if event.get("event") in ("done", "tool"):
                    _auto_save()
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
                event["user_portrait"] = _get_user_portrait()
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

    # Resolve alias to actual model name if using provider registry
    model_display = _config.models.orchestrator
    if _registry:
        try:
            model_display = _registry.get_model(_config.models.orchestrator)
        except Exception:
            pass  # Fall back to alias/raw model name

    # Estimate token usage
    from src.utils.file_utils import estimate_tokens
    lore_tokens = estimate_tokens(_orchestrator.librarian.system_prompt)
    persona_tokens = estimate_tokens(_orchestrator.persona)
    history_tokens = sum(
        estimate_tokens(m["content"]) if isinstance(m["content"], str)
        else estimate_tokens(str(m["content"]))
        for m in _orchestrator.conversation_history
    )

    # Get context limit from the active provider
    context_limit = 128000
    if _registry:
        alias = _config.models.orchestrator
        if alias in _registry.providers:
            context_limit = _registry.providers[alias].context_limit

    return {
        "status": "ready",
        "mode": _orchestrator.mode.value,
        "project": _orchestrator.active_project,
        "file": _orchestrator.active_file,
        "lore_files": len(_orchestrator.librarian.lore),
        "lore_set": _config.lore.active or "(default)",
        "persona": _config.persona.active or "(default)",
        "writing_style": _config.writing_style.active,
        "model": model_display,
        "conversation_turns": len(_orchestrator.conversation_history) // 2,
        "layout": _config.layout.active,
        "ai_character": _config.roleplay.ai_character,
        "user_character": _config.roleplay.user_character,
        "context_limit": context_limit,
        "lore_tokens": lore_tokens,
        "persona_tokens": persona_tokens,
        "history_tokens": history_tokens,
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

    # Persist and reinitialize
    config_path = Path(os.environ.get("CONFIG_PATH", "build/config.yaml"))
    _save_config_yaml(config_path, _config)

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _reinitialize_agents)

    return {
        "status": "ok",
        "active_persona": _config.persona.active or "(default)",
        "active_lore": _config.lore.active or "(default)",
        "active_writing_style": _config.writing_style.active,
        "lore_files": len(_orchestrator.librarian.lore) if _orchestrator else 0,
    }


def _create_agent_with_registry(agent_cls, config, model_alias):
    """Create an agent, resolving model alias through the registry."""
    if _registry and model_alias in _registry.providers:
        client = _registry.get_client(model_alias)
        model = _registry.get_model(model_alias)
        return agent_cls(config, client=client, model=model)
    return agent_cls(config)


def _create_writer_with_registry(librarian, config):
    """Create ProseWriter with registry-resolved client."""
    alias = config.models.prose_writer
    if _registry and alias in _registry.providers:
        client = _registry.get_client(alias)
        model = _registry.get_model(alias)
        return ProseWriter(librarian, config, client=client, model=model)
    return ProseWriter(librarian, config)


def _create_orchestrator_with_registry(librarian, writer, config):
    """Create Orchestrator with registry-resolved client."""
    alias = config.models.orchestrator
    if _registry and alias in _registry.providers:
        client = _registry.get_client(alias)
        model = _registry.get_model(alias)
        return Orchestrator(librarian, writer, config, client=client, model=model)
    return Orchestrator(librarian, writer, config)


def _reinitialize_agents():
    """Rebuild the agent chain with current config. Runs in thread pool."""
    global _orchestrator
    librarian = _create_agent_with_registry(Librarian, _config, _config.models.librarian)
    writer = _create_writer_with_registry(librarian, _config)
    _orchestrator = _create_orchestrator_with_registry(librarian, writer, _config)
    log.info(
        "Agents reinitialized: persona=%s, lore=%s",
        _config.persona.active or "(default)",
        _config.lore.active or "(default)",
    )


def _resolve_forge_models() -> dict[str, str]:
    """Resolve forge model aliases to actual model IDs via the registry."""
    if not _registry or not _config:
        return {}
    resolved = {}
    for role, alias in [
        ("planner", _config.forge.planner_model or _config.models.orchestrator),
        ("writer", _config.forge.writer_model or _config.models.prose_writer),
        ("reviewer", _config.forge.reviewer_model or _config.models.librarian),
        ("librarian", _config.models.librarian),
    ]:
        resolved[role] = _registry.get_model(alias)
    return resolved


class ModeRequest(BaseModel):
    mode: str  # "general", "writer", "roleplay", "forge"
    project: str | None = None
    file: str | None = None
    character: str | None = None  # For roleplay: AI character card filename


@app.post("/api/mode")
async def set_mode(request: ModeRequest):
    """Switch operating mode and optionally set active project/file."""
    if _orchestrator is None:
        return JSONResponse(status_code=503, content={"error": "System not initialized"})

    try:
        mode = Mode(request.mode)
    except ValueError:
        return JSONResponse(status_code=400, content={
            "error": f"Invalid mode: {request.mode}. Must be general, writer, roleplay, forge, or council."
        })

    # For roleplay, character name becomes the project (chat directory)
    project = request.project
    if mode == Mode.ROLEPLAY and request.character:
        _config.roleplay.ai_character = request.character
        project = request.character
        config_path = Path(os.environ.get("CONFIG_PATH", "build/config.yaml"))
        _save_config_yaml(config_path, _config)

    # Save current session before mode switch clears history
    _auto_save()

    result = _orchestrator.set_mode(mode, project=project, file=request.file)
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
async def get_projects(mode: str | None = None):
    """List available projects for a given mode (or the current mode)."""
    if _orchestrator is None:
        return JSONResponse(status_code=503, content={"error": "System not initialized"})

    return _orchestrator.list_projects(mode=mode)


@app.post("/api/session/new")
async def new_session():
    """Clear conversation history, starting a fresh session."""
    global _current_session_id
    if _orchestrator is None:
        return JSONResponse(status_code=503, content={"error": "System not initialized"})

    # Save current session before clearing
    _auto_save()

    _orchestrator.conversation_history.clear()
    _orchestrator.pending_content = None
    _orchestrator.last_prompt = None
    _current_session_id = None

    return {"status": "ok", "message": "Session cleared"}


@app.get("/api/conversation/history")
async def conversation_history():
    """Get the raw conversation history for debug inspection."""
    if _orchestrator is None:
        return JSONResponse(status_code=503, content={"error": "System not initialized"})

    history = _orchestrator.conversation_history
    # Summarize content blocks for readability
    messages = []
    for msg in history:
        entry = {"role": msg["role"]}
        content = msg.get("content", "")
        if isinstance(content, str):
            entry["content"] = content[:500] + ("..." if len(content) > 500 else "")
            entry["length"] = len(content)
        elif isinstance(content, list):
            # Tool use/result blocks
            blocks = []
            for block in content:
                if hasattr(block, "type"):
                    # LLM response block object
                    b = {"type": block.type}
                    if block.type == "text":
                        b["text"] = block.text[:200] + ("..." if len(block.text) > 200 else "")
                    elif block.type == "tool_use":
                        b["name"] = block.name
                        b["input"] = block.input
                    blocks.append(b)
                elif isinstance(block, dict):
                    b = {"type": block.get("type", "unknown")}
                    if "tool_use_id" in block:
                        b["tool_use_id"] = block["tool_use_id"]
                        c = block.get("content", "")
                        b["content"] = c[:200] + ("..." if len(c) > 200 else "")
                    blocks.append(b)
            entry["blocks"] = blocks
        messages.append(entry)

    return {
        "count": len(history),
        "messages": messages,
    }


class ConversationDeleteRequest(BaseModel):
    index: int  # 0-based index into conversation_history


@app.post("/api/conversation/delete")
async def conversation_delete(request: ConversationDeleteRequest):
    """Delete a message (and its pair) from conversation history by index."""
    if _orchestrator is None:
        return JSONResponse(status_code=503, content={"error": "System not initialized"})

    history = _orchestrator.conversation_history
    idx = request.index
    if idx < 0 or idx >= len(history):
        log.warning("Delete request index %d out of range (history has %d messages)", idx, len(history))
        return JSONResponse(status_code=400, content={
            "error": f"Index {idx} out of range (history has {len(history)} messages)"
        })

    msg = history[idx]
    if msg["role"] == "user":
        # Delete user message and the following assistant message (if it exists)
        end = idx + 2 if idx + 1 < len(history) and history[idx + 1]["role"] == "assistant" else idx + 1
        del history[idx:end]
    else:
        # Delete assistant message and the preceding user message (if it exists)
        start = idx - 1 if idx > 0 and history[idx - 1]["role"] == "user" else idx
        del history[start:idx + 1]

    _auto_save()
    return {"status": "ok", "turns": len(history) // 2}


class ConversationForkRequest(BaseModel):
    up_to_index: int  # Include messages 0..up_to_index


@app.post("/api/conversation/fork")
async def conversation_fork(request: ConversationForkRequest):
    """Fork conversation: save messages up to index as a new session."""
    if _orchestrator is None:
        return JSONResponse(status_code=503, content={"error": "System not initialized"})

    history = _orchestrator.conversation_history
    end = request.up_to_index + 1
    if end < 1 or end > len(history):
        return JSONResponse(status_code=400, content={"error": "Index out of range"})

    forked = history[:end]
    fork_id = _generate_session_id()
    _save_session(fork_id, forked, _orchestrator.mode.value)

    return {"status": "ok", "session_id": fork_id, "turns": len(forked) // 2}


class ConversationUpdateRequest(BaseModel):
    index: int
    content: str


@app.post("/api/conversation/update")
async def conversation_update(request: ConversationUpdateRequest):
    """Update a message's content in conversation history (for variant selection)."""
    if _orchestrator is None:
        return JSONResponse(status_code=503, content={"error": "System not initialized"})

    history = _orchestrator.conversation_history
    if request.index < 0 or request.index >= len(history):
        return JSONResponse(status_code=400, content={"error": "Index out of range"})

    history[request.index]["content"] = request.content
    _auto_save()
    return {"status": "ok"}


@app.get("/api/sessions")
async def list_sessions():
    """List saved sessions, newest first."""
    sessions = []
    sdir = _sessions_dir()
    for path in sorted(sdir.glob("*.json"), reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            sessions.append({
                "id": data.get("id", path.stem),
                "name": data.get("name", "untitled"),
                "mode": data.get("mode", "general"),
                "turns": data.get("turns", 0),
                "updated_at": data.get("updated_at", ""),
                "is_current": data.get("id") == _current_session_id,
            })
        except Exception:
            continue
    return {"sessions": sessions}


@app.post("/api/sessions/{session_id}/load")
async def load_session(session_id: str):
    """Load a saved session, replacing current conversation."""
    global _current_session_id
    if _orchestrator is None:
        return JSONResponse(status_code=503, content={"error": "System not initialized"})

    # Save current session first
    _auto_save()

    path = _sessions_dir() / f"{session_id}.json"
    if not path.exists():
        return JSONResponse(status_code=404, content={"error": "Session not found"})

    data = json.loads(path.read_text(encoding="utf-8"))
    messages = data.get("messages", [])

    _orchestrator.conversation_history.clear()
    _orchestrator.conversation_history.extend(messages)
    _orchestrator.pending_content = None
    _orchestrator.last_prompt = None
    _current_session_id = session_id

    return {
        "status": "ok",
        "messages": messages,
        "mode": data.get("mode", "general"),
    }


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    """Delete a saved session."""
    global _current_session_id
    path = _sessions_dir() / f"{session_id}.json"
    if not path.exists():
        return JSONResponse(status_code=404, content={"error": "Session not found"})

    path.unlink()
    if _current_session_id == session_id:
        _current_session_id = None

    return {"status": "ok"}


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
    """List all lore files and categories for the active lore project."""
    if _config is None:
        return JSONResponse(status_code=503, content={"error": "System not initialized"})

    lore_path = Path(_config.active_lore_path)
    if not lore_path.exists():
        return {"files": [], "categories": [], "active_project": _config.lore.active}

    files = []
    for p in sorted(lore_path.rglob("*.md")):
        rel = str(p.relative_to(lore_path))
        try:
            content = p.read_text(encoding="utf-8")
            tokens = len(content) // 4
        except Exception:
            content = ""
            tokens = 0
        files.append({"path": rel, "tokens": tokens, "size": len(content)})

    # Include all subdirectories (even empty ones) so UI can show them
    categories = sorted(
        d.name for d in lore_path.iterdir() if d.is_dir()
    )

    return {
        "files": files,
        "categories": categories,
        "active_project": _config.lore.active,
        "lore_path": str(lore_path),
    }


_LORE_DEFAULT_CATEGORIES = ["characters", "locations", "events", "factions"]


class LoreProjectRequest(BaseModel):
    name: str


@app.get("/api/lore/projects")
async def list_lore_projects():
    """List available lore projects."""
    if _config is None:
        return JSONResponse(status_code=503, content={"error": "System not initialized"})

    from src.config import list_profiles
    profiles = list_profiles(_config)

    return {
        "projects": profiles["lore_sets"],
        "active": _config.lore.active or "(default)",
    }


@app.post("/api/lore/projects")
async def create_lore_project(request: LoreProjectRequest):
    """Create a new lore project with standard directory structure."""
    global _orchestrator

    if _config is None:
        return JSONResponse(status_code=503, content={"error": "System not initialized"})

    # Sanitize name
    name = request.name.strip().lower().replace(" ", "-")
    name = "".join(c for c in name if c.isalnum() or c in "-_")
    if not name:
        return JSONResponse(status_code=400, content={"error": "Invalid project name"})

    project_dir = _config.paths.lore / name
    if project_dir.exists():
        return JSONResponse(status_code=409, content={"error": "Project already exists"})

    project_dir.mkdir(parents=True, exist_ok=True)
    for subdir in _LORE_DEFAULT_CATEGORIES:
        (project_dir / subdir).mkdir(exist_ok=True)

    # Create starter world-overview.md
    overview = project_dir / "world-overview.md"
    overview.write_text(
        "# World Overview\n\n"
        "Describe your world, setting, tone, and themes here.\n",
        encoding="utf-8",
    )

    # Activate the new project
    _config.lore.active = name
    config_path = Path(os.environ.get("CONFIG_PATH", "build/config.yaml"))
    _save_config_yaml(config_path, _config)

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _reinitialize_agents)

    return {"status": "ok", "name": name}


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


@app.delete("/api/lore/{file_path:path}")
async def delete_lore_file(file_path: str):
    """Delete a lore file. Reinitializes agents."""
    global _orchestrator

    if _config is None:
        return JSONResponse(status_code=503, content={"error": "System not initialized"})

    lore_path = Path(_config.active_lore_path)
    resolved = (lore_path / file_path).resolve()

    try:
        resolved.relative_to(lore_path.resolve())
    except ValueError:
        return JSONResponse(status_code=403, content={"error": "Invalid path"})

    if not resolved.exists():
        return JSONResponse(status_code=404, content={"error": "File not found"})

    resolved.unlink()

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _reinitialize_agents)

    return {"status": "ok", "path": file_path}


# ── Persona / prompt endpoints ────────────────────────────────────────


@app.get("/api/persona")
async def list_persona():
    """List all persona prompt files with token estimates."""
    if _config is None:
        return JSONResponse(status_code=503, content={"error": "System not initialized"})

    persona_path = Path(_config.paths.persona)
    if not persona_path.exists():
        return {"files": [], "persona_path": str(persona_path)}

    files = []
    for p in sorted(persona_path.rglob("*.md")):
        rel = str(p.relative_to(persona_path))
        try:
            content = p.read_text(encoding="utf-8")
            tokens = len(content) // 4
        except Exception:
            content = ""
            tokens = 0
        files.append({"path": rel, "tokens": tokens, "size": len(content)})

    return {"files": files, "persona_path": str(persona_path)}


@app.get("/api/persona/{file_path:path}")
async def read_persona(file_path: str):
    """Read a single persona file."""
    if _config is None:
        return JSONResponse(status_code=503, content={"error": "System not initialized"})

    persona_path = Path(_config.paths.persona)
    resolved = (persona_path / file_path).resolve()

    try:
        resolved.relative_to(persona_path.resolve())
    except ValueError:
        return JSONResponse(status_code=403, content={"error": "Invalid path"})

    if not resolved.exists():
        return JSONResponse(status_code=404, content={"error": "File not found"})

    content = resolved.read_text(encoding="utf-8")
    return {"path": file_path, "content": content, "tokens": len(content) // 4}


class PersonaWriteRequest(BaseModel):
    content: str


@app.put("/api/persona/{file_path:path}")
async def write_persona(file_path: str, request: PersonaWriteRequest):
    """Write a persona file. Reinitializes agents to pick up changes."""
    global _orchestrator

    if _config is None:
        return JSONResponse(status_code=503, content={"error": "System not initialized"})

    persona_path = Path(_config.paths.persona)
    resolved = (persona_path / file_path).resolve()

    try:
        resolved.relative_to(persona_path.resolve())
    except ValueError:
        return JSONResponse(status_code=403, content={"error": "Invalid path"})

    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(request.content, encoding="utf-8")

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _reinitialize_agents)

    return {"status": "ok", "path": file_path, "tokens": len(request.content) // 4}


# ── Writing style endpoints ───────────────────────────────────────────


@app.get("/api/writing-styles")
async def list_writing_styles():
    """List all writing style files."""
    if _config is None:
        return JSONResponse(status_code=503, content={"error": "System not initialized"})

    styles_dir = Path(_config.paths.writing_styles)
    if not styles_dir.exists():
        return {"files": [], "active": _config.writing_style.active}

    files = []
    for p in sorted(styles_dir.glob("*.md")):
        try:
            content = p.read_text(encoding="utf-8")
            tokens = len(content) // 4
        except Exception:
            content = ""
            tokens = 0
        files.append({"path": p.name, "name": p.stem, "tokens": tokens, "size": len(content)})

    return {"files": files, "active": _config.writing_style.active}


@app.get("/api/writing-styles/{name}")
async def read_writing_style(name: str):
    """Read a writing style file."""
    if _config is None:
        return JSONResponse(status_code=503, content={"error": "System not initialized"})

    path = Path(_config.paths.writing_styles) / f"{name}.md"
    if not path.exists():
        return JSONResponse(status_code=404, content={"error": "Style not found"})

    content = path.read_text(encoding="utf-8")
    return {"name": name, "content": content, "tokens": len(content) // 4}


class StyleWriteRequest(BaseModel):
    content: str


@app.put("/api/writing-styles/{name}")
async def write_writing_style(name: str, request: StyleWriteRequest):
    """Write a writing style file. Reinitializes agents."""
    global _orchestrator

    if _config is None:
        return JSONResponse(status_code=503, content={"error": "System not initialized"})

    styles_dir = Path(_config.paths.writing_styles)
    styles_dir.mkdir(parents=True, exist_ok=True)
    path = styles_dir / f"{name}.md"
    path.write_text(request.content, encoding="utf-8")

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _reinitialize_agents)

    return {"status": "ok", "name": name, "tokens": len(request.content) // 4}


# ── Character card endpoints ─────────────────────────────────────────


@app.post("/api/character-cards/import")
async def import_character_card(file: UploadFile):
    """Import a SillyTavern/TavernAI character card PNG."""
    if _config is None:
        return JSONResponse(status_code=503, content={"error": "System not initialized"})

    if not file.filename or not file.filename.lower().endswith(".png"):
        return JSONResponse(status_code=400, content={"error": "Only PNG files are supported"})

    from src.character_cards import import_tavern_card
    import tempfile

    # Save uploaded file to a temp location
    content = await file.read()
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        result = import_tavern_card(
            png_path=tmp_path,
            cards_dir=Path(_config.paths.character_cards),
            portraits_dir=Path(_config.paths.portraits),
        )
        return {
            "status": "ok",
            "card": {
                "filename": result["_filename"],
                "name": result["name"],
                "portrait": result.get("portrait"),
            },
        }
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    finally:
        tmp_path.unlink(missing_ok=True)


@app.get("/api/character-cards")
async def list_character_cards():
    """List all character cards and active selections."""
    if _config is None:
        return JSONResponse(status_code=503, content={"error": "System not initialized"})

    from src.character_cards import list_cards
    cards_dir = Path(_config.paths.character_cards)
    cards = list_cards(cards_dir)

    return {
        "cards": cards,
        "active_ai": _config.roleplay.ai_character,
        "active_user": _config.roleplay.user_character,
    }


@app.get("/api/character-cards/{name}")
async def read_character_card(name: str):
    """Read a single character card."""
    if _config is None:
        return JSONResponse(status_code=503, content={"error": "System not initialized"})

    from src.character_cards import load_card
    path = Path(_config.paths.character_cards) / f"{name}.yaml"
    card = load_card(path)
    if card is None:
        return JSONResponse(status_code=404, content={"error": "Card not found"})
    return card


class CharacterCardRequest(BaseModel):
    name: str
    portrait: str = ""
    personality: str = ""
    description: str = ""
    scenario: str = ""
    greeting: str = ""


@app.post("/api/character-cards")
async def create_character_card(request: CharacterCardRequest):
    """Create a new character card."""
    if _config is None:
        return JSONResponse(status_code=503, content={"error": "System not initialized"})

    from src.character_cards import save_card
    # Sanitize filename
    filename = request.name.strip().lower().replace(" ", "-")
    filename = "".join(c for c in filename if c.isalnum() or c in "-_")
    if not filename:
        return JSONResponse(status_code=400, content={"error": "Invalid name"})

    cards_dir = Path(_config.paths.character_cards)
    path = cards_dir / f"{filename}.yaml"
    if path.exists():
        return JSONResponse(status_code=409, content={"error": "Card already exists"})

    save_card(path, request.model_dump())
    return {"status": "ok", "filename": filename}


@app.put("/api/character-cards/{name}")
async def update_character_card(name: str, request: CharacterCardRequest):
    """Update a character card."""
    if _config is None:
        return JSONResponse(status_code=503, content={"error": "System not initialized"})

    from src.character_cards import save_card
    path = Path(_config.paths.character_cards) / f"{name}.yaml"
    save_card(path, request.model_dump())
    return {"status": "ok", "filename": name}


@app.delete("/api/character-cards/{name}")
async def delete_character_card(name: str):
    """Delete a character card."""
    if _config is None:
        return JSONResponse(status_code=503, content={"error": "System not initialized"})

    path = Path(_config.paths.character_cards) / f"{name}.yaml"
    if not path.exists():
        return JSONResponse(status_code=404, content={"error": "Card not found"})
    path.unlink()

    # Clear if it was active
    if _config.roleplay.ai_character == name:
        _config.roleplay.ai_character = None
    if _config.roleplay.user_character == name:
        _config.roleplay.user_character = None

    return {"status": "ok"}


class ActivateCardsRequest(BaseModel):
    ai_character: str | None = None
    user_character: str | None = None


@app.post("/api/character-cards/activate")
async def activate_character_cards(request: ActivateCardsRequest):
    """Set the active AI and/or user character cards for roleplay."""
    if _config is None:
        return JSONResponse(status_code=503, content={"error": "System not initialized"})

    if request.ai_character is not None:
        _config.roleplay.ai_character = request.ai_character or None
    if request.user_character is not None:
        _config.roleplay.user_character = request.user_character or None

    config_path = Path(os.environ.get("CONFIG_PATH", "build/config.yaml"))
    _save_config_yaml(config_path, _config)

    return {
        "status": "ok",
        "active_ai": _config.roleplay.ai_character,
        "active_user": _config.roleplay.user_character,
    }


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


class LayoutSetRequest(BaseModel):
    name: str


@app.post("/api/layout")
async def set_default_layout(request: LayoutSetRequest):
    """Set the default layout and persist to config.yaml."""
    if _config is None:
        return JSONResponse(status_code=503, content={"error": "System not initialized"})

    _config.layout.active = request.name
    config_path = Path(os.environ.get("CONFIG_PATH", "build/config.yaml"))
    _save_config_yaml(config_path, _config)

    return {"status": "ok", "layout": request.name}


class LayoutSaveRequest(BaseModel):
    content: str


@app.put("/api/layouts/{name}")
async def save_layout(name: str, request: LayoutSaveRequest):
    """Save/update a layout config file."""
    if _config is None:
        return JSONResponse(status_code=503, content={"error": "System not initialized"})

    layouts_dir = Path(_config.paths.layouts)
    layouts_dir.mkdir(parents=True, exist_ok=True)
    path = (layouts_dir / f"{name}.md").resolve()

    try:
        path.relative_to(layouts_dir.resolve())
    except ValueError:
        return JSONResponse(status_code=403, content={"error": "Invalid path"})

    path.write_text(request.content, encoding="utf-8")
    return {"status": "ok", "name": name}


@app.get("/api/backgrounds")
async def list_backgrounds():
    """List available background images."""
    if _config is None:
        return JSONResponse(status_code=503, content={"error": "System not initialized"})

    bg_dir = Path(_config.paths.backgrounds)
    if not bg_dir.is_dir():
        return {"backgrounds": []}

    image_exts = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}
    backgrounds = []
    for p in sorted(bg_dir.iterdir()):
        if p.is_file() and p.suffix.lower() in image_exts:
            backgrounds.append({
                "filename": p.name,
                "url": f"/backgrounds/{p.name}",
            })

    return {"backgrounds": backgrounds}



# ── Provider endpoints ────────────────────────────────────────────────


@app.get("/api/providers")
async def list_providers():
    """List configured providers (keys masked), with agent assignments."""
    if _registry is None:
        return JSONResponse(status_code=503, content={"error": "System not initialized"})

    # Build alias → agent names mapping from config
    assignments: dict[str, list[str]] = {}
    if _config:
        for agent_name, alias in [
            ("orchestrator", _config.models.orchestrator),
            ("prose_writer", _config.models.prose_writer),
            ("librarian", _config.models.librarian),
        ]:
            assignments.setdefault(alias, []).append(agent_name)

    providers = _registry.list_providers()
    for p in providers:
        p["used_by"] = assignments.get(p["alias"], [])

    return {"providers": providers}


class ProviderCreateRequest(BaseModel):
    alias: str
    name: str
    type: str
    base_url: str | None = None
    models_url: str | None = None
    api_key: str | None = None
    selected_model: str = ""
    options: dict | None = None


@app.post("/api/providers")
async def create_provider(request: ProviderCreateRequest):
    """Create a new provider config."""
    if _registry is None:
        return JSONResponse(status_code=503, content={"error": "System not initialized"})
    try:
        _registry.add(
            alias=request.alias,
            name=request.name,
            ptype=request.type,
            base_url=request.base_url,
            models_url=request.models_url,
            api_key=request.api_key,
            selected_model=request.selected_model,
            options=request.options,
        )

        # Reinitialize agents so they pick up new provider
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _reinitialize_agents)

        return {"status": "ok"}
    except ValueError as e:
        return JSONResponse(status_code=409, content={"error": str(e)})


class ProviderUpdateRequest(BaseModel):
    name: str | None = None
    type: str | None = None
    base_url: str | None = None
    models_url: str | None = None
    api_key: str | None = None
    selected_model: str | None = None
    context_limit: int | None = None
    options: dict | None = None


@app.put("/api/providers/{alias}")
async def update_provider(alias: str, request: ProviderUpdateRequest):
    """Update a provider config."""
    if _registry is None:
        return JSONResponse(status_code=503, content={"error": "System not initialized"})
    try:
        updates = {k: v for k, v in request.model_dump().items() if v is not None}
        _registry.update(alias, **updates)

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _reinitialize_agents)

        return {"status": "ok"}
    except KeyError as e:
        return JSONResponse(status_code=404, content={"error": str(e)})


@app.delete("/api/providers/{alias}")
async def delete_provider(alias: str):
    """Remove a provider config."""
    if _registry is None:
        return JSONResponse(status_code=503, content={"error": "System not initialized"})
    try:
        _registry.remove(alias)
        return {"status": "ok"}
    except KeyError as e:
        return JSONResponse(status_code=404, content={"error": str(e)})


@app.post("/api/providers/{alias}/models")
async def fetch_provider_models(alias: str):
    """Fetch available models from a configured provider."""
    if _registry is None:
        return JSONResponse(status_code=503, content={"error": "System not initialized"})
    try:
        loop = asyncio.get_event_loop()
        models = await loop.run_in_executor(None, _registry.fetch_models, alias)
        return {"models": models}
    except KeyError as e:
        return JSONResponse(status_code=404, content={"error": str(e)})
    except Exception as e:
        return JSONResponse(status_code=502, content={"error": f"Failed to fetch models: {e}"})


class FetchModelsRequest(BaseModel):
    type: str
    base_url: str | None = None
    models_url: str | None = None
    api_key: str | None = None


@app.post("/api/providers/fetch-models")
async def fetch_models_adhoc(request: FetchModelsRequest):
    """Fetch models without a saved provider (for the new-provider form)."""
    if _registry is None:
        return JSONResponse(status_code=503, content={"error": "System not initialized"})
    try:
        loop = asyncio.get_event_loop()
        models = await loop.run_in_executor(
            None, _registry.fetch_models_adhoc, request.type, request.api_key, request.base_url, request.models_url,
        )
        return {"models": models}
    except Exception as e:
        return JSONResponse(status_code=502, content={"error": f"Failed to fetch models: {e}"})


@app.get("/api/providers/templates")
async def provider_templates():
    """Return built-in provider templates for the UI."""
    return {
        "templates": [
            {"name": "Anthropic", "type": "anthropic", "base_url": None, "models_url": "https://api.anthropic.com/v1/models"},
            {"name": "OpenAI", "type": "openai", "base_url": "https://api.openai.com/v1", "models_url": "https://api.openai.com/v1/models"},
            {"name": "Custom (OpenAI-compatible)", "type": "openai", "base_url": "", "models_url": ""},
        ]
    }


# ── Agent model assignment endpoints ──────────────────────────────────


@app.get("/api/agents/models")
async def get_agent_models():
    """Return current agent-to-provider alias mapping."""
    if _config is None:
        return JSONResponse(status_code=503, content={"error": "System not initialized"})
    return {
        "assignments": {
            "orchestrator": _config.models.orchestrator,
            "prose_writer": _config.models.prose_writer,
            "librarian": _config.models.librarian,
        },
    }


class AgentModelUpdate(BaseModel):
    orchestrator: str | None = None
    prose_writer: str | None = None
    librarian: str | None = None


@app.put("/api/agents/models")
async def update_agent_models(request: AgentModelUpdate):
    """Update agent-to-provider alias mapping and persist to config.yaml."""
    if _config is None:
        return JSONResponse(status_code=503, content={"error": "System not initialized"})

    changed = False
    if request.orchestrator is not None and request.orchestrator != _config.models.orchestrator:
        _config.models.orchestrator = request.orchestrator
        changed = True
    if request.prose_writer is not None and request.prose_writer != _config.models.prose_writer:
        _config.models.prose_writer = request.prose_writer
        changed = True
    if request.librarian is not None and request.librarian != _config.models.librarian:
        _config.models.librarian = request.librarian
        changed = True

    if changed:
        # Persist to config.yaml
        config_path = Path(os.environ.get("CONFIG_PATH", "build/config.yaml"))
        _save_config_yaml(config_path, _config)

        # Reinitialize agents with new assignments
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _reinitialize_agents)

    return {
        "status": "ok",
        "assignments": {
            "orchestrator": _config.models.orchestrator,
            "prose_writer": _config.models.prose_writer,
            "librarian": _config.models.librarian,
        },
    }


def _save_config_yaml(config_path: Path, config: AppConfig):
    """Write current config back to config.yaml, preserving structure."""
    import yaml

    # Read existing file to preserve comments and ordering
    if config_path.exists():
        with open(config_path) as f:
            raw = yaml.safe_load(f) or {}
    else:
        raw = {}

    def _ensure_dict(key: str) -> dict:
        """Ensure raw[key] is a dict, even if it was null/missing in YAML."""
        if not isinstance(raw.get(key), dict):
            raw[key] = {}
        return raw[key]

    # Update models section
    models = _ensure_dict("models")
    models["orchestrator"] = config.models.orchestrator
    models["prose_writer"] = config.models.prose_writer
    models["librarian"] = config.models.librarian

    # Update layout
    layout = _ensure_dict("layout")
    layout["active"] = config.layout.active

    # Update lore
    lore = _ensure_dict("lore")
    lore["active"] = config.lore.active

    # Update roleplay character cards
    roleplay = _ensure_dict("roleplay")
    roleplay["ai_character"] = config.roleplay.ai_character
    roleplay["user_character"] = config.roleplay.user_character

    # Update web search (if configured)
    if config.web_search.provider:
        search = _ensure_dict("web_search")
        search["provider"] = config.web_search.provider

    try:
        with open(config_path, "w") as f:
            yaml.dump(raw, f, default_flow_style=False, sort_keys=False)
    except Exception:
        log.exception("Failed to save config to %s", config_path)


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
                event["user_portrait"] = _get_user_portrait()
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
                event["user_portrait"] = _get_user_portrait()
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


# ── StoryForge endpoints ─────────────────────────────────────────────


class ForgeCreateRequest(BaseModel):
    name: str


@app.post("/api/forge/create")
async def forge_create(request: ForgeCreateRequest):
    """Create a new forge project and switch to forge planning mode."""
    if _orchestrator is None or _config is None:
        return JSONResponse(status_code=503, content={"error": "System not initialized"})

    from src.services.forge import ForgeProject

    project = ForgeProject(request.name, _config)
    loop = asyncio.get_event_loop()
    manifest = await loop.run_in_executor(None, project.create)

    # Switch orchestrator to forge mode
    _orchestrator.set_mode(Mode.FORGE, project=request.name)

    return {
        "status": "ok",
        "project": request.name,
        "manifest": manifest.model_dump(),
    }


@app.get("/api/forge/projects")
async def forge_list():
    """List all forge projects with their current stage."""
    if _config is None:
        return JSONResponse(status_code=503, content={"error": "System not initialized"})

    from src.services.forge import list_forge_projects

    projects = list_forge_projects(_config)
    return {"projects": projects}


@app.get("/api/forge/{project}/status")
async def forge_status(project: str):
    """Get detailed status for a forge project."""
    if _config is None:
        return JSONResponse(status_code=503, content={"error": "System not initialized"})

    from src.services.forge import ForgeProject

    fp = ForgeProject(project, _config)
    try:
        manifest = fp.load()
        return {"status": "ok", "manifest": manifest.model_dump()}
    except FileNotFoundError:
        return JSONResponse(status_code=404, content={"error": f"Project not found: {project}"})


@app.post("/api/forge/{project}/design")
async def forge_design(project: str):
    """Run only the design phase (planner). Returns SSE stream."""
    if _orchestrator is None or _config is None:
        return JSONResponse(status_code=503, content={"error": "System not initialized"})

    from src.services.forge import ForgeProject

    fp = ForgeProject(project, _config)

    queue: Queue = Queue()

    def _run_design():
        try:
            # Get client from provider registry so forge uses configured provider
            # Also resolve model aliases to actual model IDs
            client = _registry.get_client(_config.models.orchestrator) if _registry else None
            resolved_models = _resolve_forge_models() if _registry else {}
            librarian_client = _registry.get_client(_config.models.librarian) if _registry else client
            librarian_model = resolved_models.get("librarian")
            librarian = Librarian(_config, client=librarian_client, model=librarian_model)
            for event in fp.run_design(librarian, client=client, resolved_models=resolved_models):
                queue.put(event)
        except Exception as e:
            queue.put({"event": "error", "message": str(e)})
        finally:
            queue.put(None)

    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, _run_design)

    async def event_generator():
        while True:
            try:
                event = await loop.run_in_executor(None, partial(queue.get, timeout=120))
            except Empty:
                yield "event: ping\ndata: {}\n\n"
                continue

            if event is None:
                break

            event_type = event.pop("event", "progress")
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


@app.post("/api/forge/{project}/start")
async def forge_start(project: str):
    """Start or resume the writing pipeline (design must be done). Returns SSE stream."""
    if _orchestrator is None or _config is None:
        return JSONResponse(status_code=503, content={"error": "System not initialized"})

    from src.services.forge import ForgeProject

    fp = ForgeProject(project, _config)

    queue: Queue = Queue()

    def _run_pipeline():
        """Run the forge pipeline in a thread, pushing events to the queue."""
        try:
            client = _registry.get_client(_config.models.orchestrator) if _registry else None
            resolved_models = _resolve_forge_models() if _registry else {}
            librarian_client = _registry.get_client(_config.models.librarian) if _registry else client
            librarian_model = resolved_models.get("librarian")
            librarian = Librarian(_config, client=librarian_client, model=librarian_model)
            for event in fp.run_pipeline(librarian, client=client, resolved_models=resolved_models):
                queue.put(event)
        except Exception as e:
            queue.put({"event": "error", "message": str(e)})
        finally:
            queue.put(None)

    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, _run_pipeline)

    async def event_generator():
        while True:
            try:
                event = await loop.run_in_executor(None, partial(queue.get, timeout=120))
            except Empty:
                yield "event: ping\ndata: {}\n\n"
                continue

            if event is None:
                break

            event_type = event.pop("event", "progress")
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


@app.post("/api/forge/{project}/pause")
async def forge_pause(project: str):
    """Pause a running forge pipeline."""
    if _config is None:
        return JSONResponse(status_code=503, content={"error": "System not initialized"})

    from src.services.forge import ForgeProject

    fp = ForgeProject(project, _config)
    try:
        manifest = fp.load()
        manifest.paused = True
        fp.manifest = manifest
        fp._save_manifest()
        return {"status": "ok", "paused": True}
    except FileNotFoundError:
        return JSONResponse(status_code=404, content={"error": f"Project not found: {project}"})


@app.post("/api/forge/{project}/approve")
async def forge_approve(project: str):
    """Approve chapter 1 and unpause the pipeline."""
    if _config is None:
        return JSONResponse(status_code=503, content={"error": "System not initialized"})

    from src.services.forge import ForgeProject

    fp = ForgeProject(project, _config)
    try:
        manifest = fp.load()
        manifest.paused = False
        fp.manifest = manifest
        fp._save_manifest()
        return {"status": "ok", "paused": False, "message": "Pipeline unpaused. Run /forge start to continue."}
    except FileNotFoundError:
        return JSONResponse(status_code=404, content={"error": f"Project not found: {project}"})


@app.get("/api/forge/{project}/chapter/{num}")
async def forge_chapter(project: str, num: int):
    """Read a chapter draft."""
    if _config is None:
        return JSONResponse(status_code=503, content={"error": "System not initialized"})

    ch_key = f"ch-{num:02d}"
    draft_path = _config.paths.forge / project / "chapters" / f"{ch_key}-draft.md"

    if not draft_path.exists():
        return JSONResponse(status_code=404, content={"error": f"Chapter {num} not found"})

    content = draft_path.read_text(encoding="utf-8")
    return {"chapter": num, "key": ch_key, "content": content, "word_count": len(content.split())}


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
