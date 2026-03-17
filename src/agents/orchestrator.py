"""Orchestrator agent — the user's conversational partner and router.

The Orchestrator operates in three modes:

- **General**: Free-form conversation, routes to Librarian/Writer as needed.
- **Writer**: Long-form writing with project files. Prose is shown to the user
  for accept/reject/regenerate before being written to the project file.
- **Roleplay**: Chat-style back-and-forth. Responses auto-append to the chat
  file. User can regenerate (replace last entry) or delete it.

Mode switching happens via the API. Each mode adjusts the system prompt
and state management, but shares the same tool-use loop.
"""

import json
import logging
from datetime import datetime
from enum import Enum
from pathlib import Path

import anthropic

from src.agents.librarian import Librarian
from src.agents.prose_writer import ProseWriter, _load_story_context
from src.config import AppConfig
from src.models import Response
from src.utils.file_utils import estimate_tokens

log = logging.getLogger(__name__)


class Mode(str, Enum):
    GENERAL = "general"
    WRITER = "writer"
    ROLEPLAY = "roleplay"


# ── Tool definitions ──────────────────────────────────────────────────

ORCHESTRATOR_TOOLS = [
    {
        "name": "query_lore",
        "description": (
            "Ask the Librarian a question about the story's world, characters, "
            "locations, factions, or events. Returns sourced passages from lore files."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "A specific lore question."}
            },
            "required": ["query"],
        },
    },
    {
        "name": "write_prose",
        "description": (
            "Generate prose using the Prose Writer. The Writer will "
            "automatically query lore as needed. Returns the generated text."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "description": {
                    "type": "string",
                    "description": "What should be written — scene description, continuation prompt, etc.",
                },
                "tone_notes": {
                    "type": "string",
                    "description": "Optional tone/style guidance for this piece.",
                },
            },
            "required": ["description"],
        },
    },
    {
        "name": "read_file",
        "description": "Read the contents of a file within the content directories.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative path within the content directory."},
                "directory": {
                    "type": "string",
                    "enum": ["lore", "story", "writing", "chats", "code-requests"],
                    "description": "Which content directory to read from.",
                },
            },
            "required": ["path", "directory"],
        },
    },
    {
        "name": "write_file",
        "description": "Write or update a file within the content directories.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative path within the content directory."},
                "directory": {
                    "type": "string",
                    "enum": ["lore", "story", "writing", "chats", "code-requests"],
                    "description": "Which content directory to write to.",
                },
                "content": {"type": "string", "description": "File content to write."},
            },
            "required": ["path", "directory", "content"],
        },
    },
    {
        "name": "list_files",
        "description": "List files in a content directory or subdirectory.",
        "input_schema": {
            "type": "object",
            "properties": {
                "directory": {
                    "type": "string",
                    "enum": ["lore", "story", "writing", "chats", "code-requests"],
                    "description": "Which content directory to list.",
                },
                "subdirectory": {
                    "type": "string",
                    "description": "Optional subdirectory within the content directory.",
                },
            },
            "required": ["directory"],
        },
    },
    {
        "name": "search_files",
        "description": "Search for text within files in a content directory.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Text to search for (case-insensitive)."},
                "directory": {
                    "type": "string",
                    "enum": ["lore", "story", "writing", "chats", "code-requests"],
                    "description": "Which content directory to search.",
                },
            },
            "required": ["query", "directory"],
        },
    },
    {
        "name": "request_code_change",
        "description": (
            "Write a formal code change request for the development team."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "problem": {"type": "string"},
                "suggested_approach": {"type": "string"},
                "priority": {"type": "string", "enum": ["low", "medium", "high"]},
                "affected_files": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["title", "problem"],
        },
    },
    {
        "name": "delegate_technical",
        "description": (
            "Route a factual or technical question to a focused agent without "
            "personality context, for higher accuracy."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "reason": {"type": "string"},
            },
            "required": ["query"],
        },
    },
]

# ── Mode-specific system prompt sections ──────────────────────────────

GENERAL_MODE_PROMPT = """## Mode: General

You are in general conversation mode. Route requests naturally:
- Use write_prose for any creative writing requests
- Use query_lore for world/character questions
- Use delegate_technical for technical/factual questions unrelated to the story
- Use filesystem tools to help manage content
- Discuss story planning, give feedback, or brainstorm freely"""

WRITER_MODE_PROMPT = """## Mode: Writer

You are in long-form writing mode. The user is working on a writing project.

Current project: {project_name}
Current file: {current_file}

The user sends prompts describing what to write next. Your workflow:
1. Use write_prose to generate the content (it auto-queries lore as needed)
2. Present the generated text to the user in your response
3. Wait for the user's reaction:
   - If they accept (say "good", "accept", "keep it", "yes", etc.) → the text will be appended to the project file
   - If they say "regenerate", "try again", "redo" → generate again with the same intent
   - If they send a new prompt → discard the pending text and generate from the new prompt
   - If they provide feedback like "make it darker" or "less dialogue" → regenerate with their notes

IMPORTANT: Do NOT write to the project file until the user accepts. Present the text for review first.
You have access to the current file contents below to maintain continuity.

{file_context}"""

ROLEPLAY_MODE_PROMPT = """## Mode: Roleplay

You are in roleplay/chat mode. The user is engaged in an interactive narrative.

Current chat: {project_name}
Current file: {current_file}

The user sends messages as their character or describes actions. Your workflow:
1. Use write_prose to generate the response/continuation
2. The generated text is automatically appended to the chat file
3. Present it in your response

Special commands the user might say:
- "regenerate" / "try again" → Remove the last entry from the file, generate a new one with the same context
- "delete that" / "remove last" → Remove the last entry from the file without regenerating
- "undo" → Same as delete

Otherwise, every exchange appends to the file naturally, building the ongoing narrative.

{file_context}"""


class Orchestrator:
    """Routes user intent. The only agent the user talks to directly."""

    def __init__(
        self,
        librarian: Librarian,
        writer: ProseWriter,
        config: AppConfig,
    ):
        self.librarian = librarian
        self.writer = writer
        self.config = config
        self.model = config.models.orchestrator
        self.client = anthropic.Anthropic()
        self.persona = self._load_persona()
        self.conversation_history: list[dict] = []

        # Mode state
        self.mode: Mode = Mode.GENERAL
        self.active_project: str | None = None  # e.g. "pale-city-novel"
        self.active_file: str | None = None     # e.g. "chapter-03.md"
        self.pending_content: str | None = None  # Writer mode: awaiting accept/reject
        self.last_prompt: str | None = None      # For regenerate

        log.info(
            "Orchestrator initialized (persona: %d tokens, model: %s)",
            estimate_tokens(self.persona),
            self.model,
        )

    # ── Mode management ───────────────────────────────────────────────

    def set_mode(
        self,
        mode: Mode,
        project: str | None = None,
        file: str | None = None,
    ) -> dict:
        """Switch operating mode and optionally set active project/file."""
        self.mode = mode
        self.pending_content = None
        self.last_prompt = None
        self.conversation_history.clear()

        if project is not None:
            self.active_project = project
        if file is not None:
            self.active_file = file

        # Ensure project directory exists for writer/roleplay modes
        if mode in (Mode.WRITER, Mode.ROLEPLAY):
            base_dir = self._mode_base_dir()
            if base_dir and self.active_project:
                project_dir = base_dir / self.active_project
                project_dir.mkdir(parents=True, exist_ok=True)

        log.info("Mode set to %s (project=%s, file=%s)", mode, self.active_project, self.active_file)
        return {
            "mode": mode.value,
            "project": self.active_project,
            "file": self.active_file,
        }

    def _mode_base_dir(self) -> Path | None:
        """Base content directory for the current mode."""
        if self.mode == Mode.WRITER:
            return self.config.paths.writing
        elif self.mode == Mode.ROLEPLAY:
            return self.config.paths.chats
        return None

    def _active_file_path(self) -> Path | None:
        """Full path to the active project file."""
        base = self._mode_base_dir()
        if base and self.active_project and self.active_file:
            return base / self.active_project / self.active_file
        return None

    def _load_active_file_context(self, max_chars: int = 8000) -> str:
        """Load content from the active file for context."""
        path = self._active_file_path()
        if path is None or not path.exists():
            return ""
        content = path.read_text(encoding="utf-8")
        if len(content) <= max_chars:
            return content
        # Return tail, break at paragraph boundary
        truncated = content[-max_chars:]
        nl = truncated.find("\n\n")
        if nl != -1 and nl < len(truncated) // 2:
            truncated = truncated[nl + 2:]
        return truncated

    def list_projects(self) -> dict:
        """List available projects for the current mode."""
        base = self._mode_base_dir()
        if base is None or not base.exists():
            return {"projects": []}

        projects = []
        for d in sorted(base.iterdir()):
            if d.is_dir():
                files = sorted(f.name for f in d.glob("*.md"))
                projects.append({"name": d.name, "files": files})

        return {"projects": projects}

    # ── Persona loading ───────────────────────────────────────────────

    def _load_persona(self) -> str:
        """Load persona files with tiered token budgeting (ADR-005)."""
        persona_dir = self.config.active_persona_path
        if not persona_dir.exists():
            log.warning("No persona directory found at %s, using minimal persona", persona_dir)
            return "You are a helpful creative writing collaborator."

        tiers = ["core.md", "quirks.md", "references.md", "extended.md"]
        budget = self.config.persona.max_tokens
        sections: list[str] = []
        total_tokens = 0

        for tier_file in tiers:
            path = persona_dir / tier_file
            if not path.exists():
                continue
            content = path.read_text(encoding="utf-8")
            tokens = estimate_tokens(content)

            if total_tokens + tokens > budget:
                log.warning(
                    "Persona budget exceeded at %s (%d + %d > %d tokens). "
                    "Skipping remaining tiers.",
                    tier_file, total_tokens, tokens, budget,
                )
                break

            sections.append(content)
            total_tokens += tokens

        log.info("Persona loaded: %d tokens across %d tiers", total_tokens, len(sections))
        return "\n\n".join(sections)

    # ── System prompt building ────────────────────────────────────────

    def _build_system_prompt(self) -> str:
        """Build the full system prompt based on current mode."""
        parts = [self.persona]

        if self.mode == Mode.GENERAL:
            story_context = _load_story_context(self.config.paths.story)
            parts.append(GENERAL_MODE_PROMPT)
            if story_context:
                parts.append(f"\n## Current Story Context:\n\n{story_context}")

        elif self.mode == Mode.WRITER:
            file_content = self._load_active_file_context()
            file_context = (
                f"## Current File Contents:\n\n{file_content}"
                if file_content
                else "## Current File Contents:\n\n(empty — this is a new file)"
            )
            parts.append(WRITER_MODE_PROMPT.format(
                project_name=self.active_project or "(none)",
                current_file=self.active_file or "(none)",
                file_context=file_context,
            ))

        elif self.mode == Mode.ROLEPLAY:
            file_content = self._load_active_file_context()
            file_context = (
                f"## Current Chat Contents:\n\n{file_content}"
                if file_content
                else "## Current Chat Contents:\n\n(empty — new conversation)"
            )
            parts.append(ROLEPLAY_MODE_PROMPT.format(
                project_name=self.active_project or "(none)",
                current_file=self.active_file or "(none)",
                file_context=file_context,
            ))

        parts.append(
            "\n## Tools\n\n"
            "Use tools proactively. Don't ask the user to do things you can do yourself.\n"
            "For technical/factual questions unrelated to the story, use delegate_technical."
        )

        return "\n\n".join(parts)

    # ── Main handler ──────────────────────────────────────────────────

    def handle(self, user_input: str) -> Response:
        """Process user input through the tool-use loop."""

        # Handle mode-specific commands before the LLM
        intercepted = self._handle_mode_commands(user_input)
        if intercepted:
            return intercepted

        system_prompt = self._build_system_prompt()

        self.conversation_history.append({"role": "user", "content": user_input})
        messages = list(self.conversation_history)

        response_text = ""
        response_type = "discussion"

        # Tool-use loop
        while True:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=system_prompt,
                messages=messages,
                tools=ORCHESTRATOR_TOOLS,
            )

            if response.stop_reason == "end_turn":
                response_text = self._extract_text(response)
                break

            if response.stop_reason == "tool_use":
                messages.append({"role": "assistant", "content": response.content})

                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        result, rtype = self._execute_tool(block.name, block.input)
                        if rtype:
                            response_type = rtype
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result,
                        })

                messages.append({"role": "user", "content": tool_results})
                continue

            log.warning("Unexpected stop_reason: %s", response.stop_reason)
            response_text = self._extract_text(response)
            break

        # Handle post-generation state for writer/roleplay modes
        response_text, response_type = self._post_generation(response_text, response_type, user_input)

        self.conversation_history.append({"role": "assistant", "content": response_text})
        self._log_response(user_input, response_text, response_type)

        return Response(
            content=response_text,
            response_type=response_type,
        )

    # ── Mode-specific command interception ────────────────────────────

    def _handle_mode_commands(self, user_input: str) -> Response | None:
        """Handle special commands before sending to the LLM."""
        lower = user_input.strip().lower()

        if self.mode == Mode.WRITER:
            # Accept pending content
            if self.pending_content and lower in (
                "accept", "yes", "good", "keep it", "keep", "ok", "okay", "lgtm",
            ):
                self._append_to_active_file(self.pending_content)
                self.pending_content = None
                return Response(
                    content="Written to file.",
                    response_type="confirmation",
                )

            # Regenerate
            if lower in ("regenerate", "try again", "redo", "again"):
                self.pending_content = None
                if self.last_prompt:
                    # Will fall through to handle() with the original prompt
                    return None  # Let it proceed with last_prompt re-sent below
                return Response(
                    content="Nothing to regenerate — send a writing prompt first.",
                    response_type="discussion",
                )

        if self.mode == Mode.ROLEPLAY:
            if lower in ("regenerate", "try again", "redo"):
                self._remove_last_entry()
                self.pending_content = None
                if self.last_prompt:
                    return None  # Fall through to regenerate
                return Response(
                    content="Removed last entry. Send a prompt to generate a new one.",
                    response_type="confirmation",
                )

            if lower in ("delete that", "remove last", "undo", "delete"):
                self._remove_last_entry()
                return Response(
                    content="Last entry removed.",
                    response_type="confirmation",
                )

        return None

    def _post_generation(self, response_text: str, response_type: str, user_input: str) -> tuple[str, str]:
        """Handle post-generation state based on mode."""
        if self.mode == Mode.WRITER and response_type == "prose":
            # Store pending content, don't write yet
            self.pending_content = self._extract_prose_from_response(response_text)
            self.last_prompt = user_input
            response_type = "prose_pending"

        elif self.mode == Mode.ROLEPLAY and response_type == "prose":
            # Auto-append to chat file
            prose = self._extract_prose_from_response(response_text)
            if prose:
                self._append_to_active_file(prose)
                self.last_prompt = user_input

        return response_text, response_type

    def _extract_prose_from_response(self, response_text: str) -> str | None:
        """Extract generated prose from the response text.

        The Orchestrator wraps prose in its own commentary. The actual
        prose was generated by write_prose tool and is typically the
        longest block of text. For now, return the full response text
        and let the system prompt guide the model to present prose cleanly.
        """
        # TODO: Could be smarter about extracting just the prose from
        # the Orchestrator's commentary, but for now the system prompt
        # tells the model to present prose clearly.
        return response_text if response_text.strip() else None

    # ── File operations for modes ─────────────────────────────────────

    def _append_to_active_file(self, content: str) -> None:
        """Append content to the active project file."""
        path = self._active_file_path()
        if path is None:
            log.warning("No active file to append to")
            return

        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            if path.exists() and path.stat().st_size > 0:
                f.write("\n\n")
            f.write(content)

        log.info("Appended %d chars to %s", len(content), path)

    def _remove_last_entry(self) -> None:
        """Remove the last entry (double-newline-separated block) from the active file."""
        path = self._active_file_path()
        if path is None or not path.exists():
            log.warning("No active file to remove from")
            return

        content = path.read_text(encoding="utf-8")
        if not content.strip():
            return

        # Split on double newlines, remove the last block
        parts = content.rsplit("\n\n", 1)
        if len(parts) > 1:
            new_content = parts[0]
        else:
            new_content = ""

        path.write_text(new_content, encoding="utf-8")
        log.info("Removed last entry from %s", path)

    # ── Tool execution ────────────────────────────────────────────────

    def _execute_tool(
        self,
        name: str,
        input_data: dict,
    ) -> tuple[str, str | None]:
        """Execute a tool call and return (result_string, optional_response_type)."""
        log.info("Tool call: %s", name)

        if name == "query_lore":
            bundle = self.librarian.query(input_data["query"])
            return json.dumps({
                "passages": bundle.relevant_passages,
                "sources": bundle.source_files,
                "confidence": bundle.confidence,
            }), "lore_answer"

        elif name == "write_prose":
            # Get context from active file if in writer/roleplay mode, else from story
            if self.mode in (Mode.WRITER, Mode.ROLEPLAY):
                context = self._load_active_file_context()
            else:
                context = _load_story_context(self.config.paths.story)

            # Temporarily disable auto-append — we handle file writing ourselves
            old_auto = self.config.prose_writer.auto_append_to_story
            self.config.prose_writer.auto_append_to_story = False
            try:
                result = self.writer.write_scene(input_data["description"], context)
            finally:
                self.config.prose_writer.auto_append_to_story = old_auto

            return json.dumps({
                "generated_text": result.generated_text,
                "word_count": result.word_count,
                "lore_queries": result.lore_queries_made,
            }), "prose"

        elif name == "read_file":
            return self._tool_read_file(input_data), None

        elif name == "write_file":
            return self._tool_write_file(input_data), None

        elif name == "list_files":
            return self._tool_list_files(input_data), None

        elif name == "search_files":
            return self._tool_search_files(input_data), None

        elif name == "request_code_change":
            return self._tool_request_code_change(input_data), "confirmation"

        elif name == "delegate_technical":
            return self._tool_delegate_technical(input_data), "discussion"

        else:
            return json.dumps({"error": f"Unknown tool: {name}"}), None

    # ── Filesystem tool implementations ───────────────────────────────

    def _dir_map(self) -> dict[str, Path]:
        """Map directory names to paths."""
        return {
            "lore": self.config.paths.lore,
            "story": self.config.paths.story,
            "writing": self.config.paths.writing,
            "chats": self.config.paths.chats,
            "code-requests": self.config.paths.code_requests,
        }

    def _resolve_path(self, directory: str, relative_path: str) -> Path | None:
        base = self._dir_map().get(directory)
        if base is None:
            return None
        resolved = (base / relative_path).resolve()
        try:
            resolved.relative_to(base.resolve())
        except ValueError:
            return None
        return resolved

    def _tool_read_file(self, input_data: dict) -> str:
        path = self._resolve_path(input_data["directory"], input_data["path"])
        if path is None:
            return json.dumps({"error": "Invalid path or directory."})
        if not path.exists():
            return json.dumps({"error": f"File not found: {input_data['path']}"})
        try:
            content = path.read_text(encoding="utf-8")
            return json.dumps({"content": content, "path": input_data["path"]})
        except Exception as e:
            return json.dumps({"error": str(e)})

    def _tool_write_file(self, input_data: dict) -> str:
        path = self._resolve_path(input_data["directory"], input_data["path"])
        if path is None:
            return json.dumps({"error": "Invalid path or directory."})
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(input_data["content"], encoding="utf-8")
            return json.dumps({"status": "ok", "path": input_data["path"]})
        except Exception as e:
            return json.dumps({"error": str(e)})

    def _tool_list_files(self, input_data: dict) -> str:
        base = self._dir_map().get(input_data["directory"])
        if base is None:
            return json.dumps({"error": "Invalid directory."})

        subdir = input_data.get("subdirectory", "")
        target = base / subdir if subdir else base

        if not target.exists():
            return json.dumps({"files": [], "note": "Directory does not exist."})

        files = []
        for p in sorted(target.rglob("*")):
            if p.is_file():
                files.append(str(p.relative_to(base)))

        return json.dumps({"files": files, "count": len(files)})

    def _tool_search_files(self, input_data: dict) -> str:
        base = self._dir_map().get(input_data["directory"])
        if base is None:
            return json.dumps({"error": "Invalid directory."})

        query = input_data["query"].lower()
        matches: list[dict] = []

        for file_path in base.rglob("*.md"):
            try:
                content = file_path.read_text(encoding="utf-8")
                for i, line in enumerate(content.splitlines(), 1):
                    if query in line.lower():
                        matches.append({
                            "file": str(file_path.relative_to(base)),
                            "line": i,
                            "text": line.strip(),
                        })
            except Exception:
                continue

        return json.dumps({"matches": matches[:50], "total": len(matches)})

    def _tool_request_code_change(self, input_data: dict) -> str:
        title = input_data["title"]
        slug = title.lower().replace(" ", "-")[:50]
        date = datetime.now().strftime("%Y-%m-%d")
        filename = f"{date}-{slug}.md"

        content_parts = [
            "---",
            f"title: {title}",
            f"priority: {input_data.get('priority', 'medium')}",
            "requested_by: orchestrator",
            f"date: {date}",
            "status: pending",
            "---",
            "",
            "## Problem",
            "",
            input_data["problem"],
        ]

        if input_data.get("suggested_approach"):
            content_parts.extend(["", "## Suggested Approach", "", input_data["suggested_approach"]])

        if input_data.get("affected_files"):
            content_parts.extend(["", "## Files Likely Affected", ""])
            for f in input_data["affected_files"]:
                content_parts.append(f"- {f}")

        file_content = "\n".join(content_parts) + "\n"

        code_requests_dir = self.config.paths.code_requests
        code_requests_dir.mkdir(parents=True, exist_ok=True)
        file_path = code_requests_dir / filename
        file_path.write_text(file_content, encoding="utf-8")

        log.info("Code change request written: %s", filename)
        return json.dumps({"status": "ok", "file": filename})

    def _tool_delegate_technical(self, input_data: dict) -> str:
        log.info("Delegating technical query: %s", input_data["query"][:100])
        response = self.client.messages.create(
            model=self.model,
            max_tokens=2048,
            system="You are a helpful technical assistant. Answer accurately and concisely.",
            messages=[{"role": "user", "content": input_data["query"]}],
        )
        return response.content[0].text

    # ── Utilities ─────────────────────────────────────────────────────

    def _extract_text(self, response: anthropic.types.Message) -> str:
        parts = []
        for block in response.content:
            if block.type == "text":
                parts.append(block.text)
        return "\n\n".join(parts)

    def _log_response(self, user_input: str, response_text: str, response_type: str) -> None:
        log_dir = self.config.paths.story / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)

        date_str = datetime.now().strftime("%Y-%m-%d")
        log_file = log_dir / f"session-{date_str}.md"

        timestamp = datetime.now().strftime("%H:%M:%S")
        entry = (
            f"\n\n---\n\n"
            f"**[{timestamp}] User ({self.mode.value}/{response_type}):**\n\n{user_input}\n\n"
            f"**[{timestamp}] Orchestrator:**\n\n{response_text}\n"
        )

        with open(log_file, "a", encoding="utf-8") as f:
            f.write(entry)
