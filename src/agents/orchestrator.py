"""Orchestrator agent — the user's conversational partner and router.

The Orchestrator is the only agent the user talks to directly. It classifies
intent, routes to the Librarian or Prose Writer as needed, manages persona,
and provides filesystem tools for content management within mounted volumes.

For technical queries, it delegates to a clean agent call without persona
overhead (ADR-006). For code changes, it writes structured requests to the
code-requests directory (ADR-004).
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path

import anthropic

from src.agents.librarian import Librarian
from src.agents.prose_writer import ProseWriter, _load_story_context
from src.config import AppConfig
from src.models import Response
from src.utils.file_utils import estimate_tokens

log = logging.getLogger(__name__)

# Tools available to the Orchestrator within mounted volumes
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
        "name": "write_scene",
        "description": (
            "Generate a prose scene using the Prose Writer. The Writer will "
            "automatically query lore as needed. The scene is appended to the story file."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "description": {
                    "type": "string",
                    "description": "What should happen in the scene.",
                },
                "tone_notes": {
                    "type": "string",
                    "description": "Optional tone/style guidance for this scene.",
                },
            },
            "required": ["description"],
        },
    },
    {
        "name": "read_file",
        "description": "Read the contents of a file within the content directories (lore, story, code-requests).",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative path within the content directory."},
                "directory": {
                    "type": "string",
                    "enum": ["lore", "story", "code-requests"],
                    "description": "Which content directory to read from.",
                },
            },
            "required": ["path", "directory"],
        },
    },
    {
        "name": "write_file",
        "description": "Write or update a file within the content directories (lore, story, code-requests).",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative path within the content directory."},
                "directory": {
                    "type": "string",
                    "enum": ["lore", "story", "code-requests"],
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
                    "enum": ["lore", "story", "code-requests"],
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
        "description": "Search for text within files in a content directory. Returns matching lines with file paths.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Text to search for (case-insensitive)."},
                "directory": {
                    "type": "string",
                    "enum": ["lore", "story", "code-requests"],
                    "description": "Which content directory to search.",
                },
            },
            "required": ["query", "directory"],
        },
    },
    {
        "name": "request_code_change",
        "description": (
            "Write a formal code change request for the development team. "
            "Use this when the user describes a problem or feature that requires "
            "changes to the system's code rather than its content."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Short title for the change request."},
                "problem": {"type": "string", "description": "What problem or need this addresses."},
                "suggested_approach": {
                    "type": "string",
                    "description": "How the change might be implemented.",
                },
                "priority": {
                    "type": "string",
                    "enum": ["low", "medium", "high"],
                    "description": "Priority level.",
                },
                "affected_files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of likely affected source files.",
                },
            },
            "required": ["title", "problem"],
        },
    },
    {
        "name": "delegate_technical",
        "description": (
            "Route a factual or technical question to a focused agent without "
            "personality context, for higher accuracy. Use this for questions about "
            "technology, code, troubleshooting, or factual queries unrelated to the story."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The technical question to answer."},
                "reason": {"type": "string", "description": "Why this should be delegated."},
            },
            "required": ["query"],
        },
    },
]


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

        log.info(
            "Orchestrator initialized (persona: %d tokens, model: %s)",
            estimate_tokens(self.persona),
            self.model,
        )

    def _load_persona(self) -> str:
        """Load persona files with tiered token budgeting (ADR-005)."""
        persona_dir = Path("persona")
        if not persona_dir.exists():
            log.warning("No persona directory found, using minimal persona")
            return "You are a helpful creative writing collaborator."

        # Load tiers in priority order
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
                    tier_file,
                    total_tokens,
                    tokens,
                    budget,
                )
                break

            sections.append(content)
            total_tokens += tokens
            log.debug("Loaded persona tier %s (%d tokens)", tier_file, tokens)

        log.info("Persona loaded: %d tokens across %d tiers", total_tokens, len(sections))
        return "\n\n".join(sections)

    def _build_system_prompt(self, story_context: str) -> str:
        """Build the full system prompt with persona and context."""
        parts = [
            self.persona,
            "\n\n## Your Capabilities\n\n"
            "You have access to tools for:\n"
            "- Querying lore (character details, locations, world facts)\n"
            "- Writing prose scenes (automatically queries lore as needed)\n"
            "- Reading, writing, listing, and searching files in the content directories\n"
            "- Writing code change requests for the development team\n"
            "- Delegating technical questions to a focused agent for accuracy\n\n"
            "Use these tools proactively. Don't ask the user to do things you can do yourself.\n"
            "When writing scenes, always use the write_scene tool rather than writing prose directly.\n"
            "For technical/factual questions unrelated to the story, use delegate_technical.",
        ]

        if story_context:
            parts.append(
                f"\n\n## Current Story Context (most recent):\n\n{story_context}"
            )

        return "\n".join(parts)

    def handle(self, user_input: str) -> Response:
        """Process user input through the tool-use loop."""
        story_context = _load_story_context(self.config.paths.story)
        system_prompt = self._build_system_prompt(story_context)

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
                        result, rtype = self._execute_tool(block.name, block.input, story_context)
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

        # Store assistant response in conversation history
        self.conversation_history.append({"role": "assistant", "content": response_text})

        # Log the response
        self._log_response(user_input, response_text, response_type)

        return Response(
            content=response_text,
            response_type=response_type,
        )

    def _execute_tool(
        self,
        name: str,
        input_data: dict,
        story_context: str,
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

        elif name == "write_scene":
            result = self.writer.write_scene(
                input_data["description"],
                story_context,
            )
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

    def _resolve_path(self, directory: str, relative_path: str) -> Path | None:
        """Resolve a path within allowed content directories."""
        dir_map = {
            "lore": self.config.paths.lore,
            "story": self.config.paths.story,
            "code-requests": self.config.paths.code_requests,
        }
        base = dir_map.get(directory)
        if base is None:
            return None

        resolved = (base / relative_path).resolve()
        # Ensure we haven't escaped the base directory
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
            return json.dumps({"content": content, "path": str(input_data["path"])})
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
        dir_map = {
            "lore": self.config.paths.lore,
            "story": self.config.paths.story,
            "code-requests": self.config.paths.code_requests,
        }
        base = dir_map.get(input_data["directory"])
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
        dir_map = {
            "lore": self.config.paths.lore,
            "story": self.config.paths.story,
            "code-requests": self.config.paths.code_requests,
        }
        base = dir_map.get(input_data["directory"])
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
        """Run a clean technical query without persona overhead."""
        log.info("Delegating technical query: %s", input_data["query"][:100])
        response = self.client.messages.create(
            model=self.model,
            max_tokens=2048,
            system="You are a helpful technical assistant. Answer accurately and concisely.",
            messages=[{"role": "user", "content": input_data["query"]}],
        )
        return response.content[0].text

    def _extract_text(self, response: anthropic.types.Message) -> str:
        parts = []
        for block in response.content:
            if block.type == "text":
                parts.append(block.text)
        return "\n\n".join(parts)

    def _log_response(self, user_input: str, response_text: str, response_type: str) -> None:
        """Log the exchange to a response log file (ADR-009)."""
        log_dir = self.config.paths.story / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)

        date_str = datetime.now().strftime("%Y-%m-%d")
        log_file = log_dir / f"session-{date_str}.md"

        timestamp = datetime.now().strftime("%H:%M:%S")
        entry = (
            f"\n\n---\n\n"
            f"**[{timestamp}] User ({response_type}):**\n\n{user_input}\n\n"
            f"**[{timestamp}] Orchestrator:**\n\n{response_text}\n"
        )

        with open(log_file, "a", encoding="utf-8") as f:
            f.write(entry)
