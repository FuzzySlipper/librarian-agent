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
import random
import re
from datetime import datetime
from enum import Enum
from pathlib import Path

import yaml

from src.agents.librarian import Librarian
from src.agents.prose_writer import ProseWriter, _load_story_context
from src.config import AppConfig
from src.llm import LLMClient, LLMResponse
from src.models import Response
from src.utils.file_utils import estimate_tokens

log = logging.getLogger(__name__)


class Mode(str, Enum):
    GENERAL = "general"
    WRITER = "writer"
    ROLEPLAY = "roleplay"
    FORGE = "forge"
    COUNCIL = "council"


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
                    "enum": ["lore", "story", "writing", "chats", "code-requests", "forge"],
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
                    "enum": ["lore", "story", "writing", "chats", "code-requests", "forge"],
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
                    "enum": ["lore", "story", "writing", "chats", "code-requests", "forge"],
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
                    "enum": ["lore", "story", "writing", "chats", "code-requests", "forge"],
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
    {
        "name": "roll_dice",
        "description": (
            "Roll dice using standard notation (e.g. '2d6', '1d20+5', '3d8-2'). "
            "Use for combat, random events, plot progression, chance encounters, "
            "or any time randomness should influence the narrative. Returns individual "
            "rolls and total. No LLM involved — pure RNG."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "notation": {
                    "type": "string",
                    "description": "Dice notation, e.g. '2d6', '1d20+5', '4d6kh3' (keep highest 3).",
                },
                "reason": {
                    "type": "string",
                    "description": "What this roll is for — helps the model interpret the result in context.",
                },
            },
            "required": ["notation"],
        },
    },
    {
        "name": "get_story_state",
        "description": (
            "Read the current story/session state — plot threads, character conditions, "
            "relationship trackers, tension levels, etc. Also includes the event log: "
            "a chronological record of all updates with a monotonic counter (_event_counter) "
            "and recent event history (_events). Use the counter for pacing logic — e.g. "
            "'major plot events should be at least 20 updates apart'. State is stored in a "
            "companion .state.yaml file alongside the active story/chat file, separate from prose."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "update_story_state",
        "description": (
            "Update the story/session state. Use this to track plot progression, "
            "character status changes, relationship shifts, tension levels, quest "
            "progress, or any narrative metadata. Each update increments the event "
            "counter and adds to the event log. State persists across turns in a "
            "companion .state.yaml file — never injected into the main prompt."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "updates": {
                    "type": "object",
                    "description": (
                        "Key-value pairs to merge into the state. Nested objects are "
                        "supported. Example: {\"characters\": {\"elena\": {\"mood\": \"suspicious\"}}, "
                        "\"tension\": 7}"
                    ),
                },
                "remove_keys": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Top-level keys to remove from state, if any.",
                },
            },
            "required": ["updates"],
        },
    },
    {
        "name": "generate_image",
        "description": (
            "Generate an image from a text description. Use this when a scene, "
            "character, location, or moment would benefit from visual depiction. "
            "Returns the image URL or an error if image generation is not configured."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Detailed visual description of the image to generate.",
                },
            },
            "required": ["prompt"],
        },
    },
]

WEB_SEARCH_TOOL = {
    "name": "web_search",
    "description": (
        "Search the web for real-world information — facts, research, references, "
        "current events, or anything outside the story's lore corpus. Use this for "
        "questions the Librarian can't answer because they're about the real world."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Web search query.",
            },
        },
        "required": ["query"],
    },
}

# ── Mode-specific system prompt sections ──────────────────────────────

GENERAL_MODE_PROMPT = """## Mode: General

You are in general conversation mode. Route requests naturally:
- Use write_prose for any creative writing requests
- Use query_lore for world/character questions
- Use delegate_technical for technical/factual questions unrelated to the story
- Use filesystem tools to help manage content
- Discuss story planning, give feedback, or brainstorm freely
- Use roll_dice when randomness should affect outcomes
- Use get_story_state / update_story_state to track ongoing plot threads and character status"""

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
{character_section}
The user sends messages as their character or describes actions. Your workflow:
1. Use write_prose to generate the response/continuation
2. The generated text is automatically appended to the chat file
3. Present it in your response

Special commands the user might say:
- "regenerate" / "try again" → Remove the last entry from the file, generate a new one with the same context
- "delete that" / "remove last" → Remove the last entry from the file without regenerating
- "undo" → Same as delete

Otherwise, every exchange appends to the file naturally, building the ongoing narrative.

Use roll_dice for combat outcomes, random encounters, or any time chance should shape the story.
Use update_story_state to track relationship changes, plot progression, character injuries, mood shifts,
or anything that should persist and inform future responses. Check state with get_story_state.
The state file is separate from the prose — it won't clutter the narrative.

The state file includes an event counter (_update_count in the story state summary above).
Use this for pacing: check get_story_state to see how many updates have passed since major events,
and pace plot progression accordingly. For example, if a plot thread is marked as "building" and
30+ updates have passed, it may be time to escalate.

{file_context}"""

FORGE_MODE_PROMPT = """## Mode: StoryForge Planning

You are in StoryForge planning mode — helping the user design a long-form story \
that will be written autonomously by AI agents chapter by chapter.

Current project: {project_name}

## Workflow

This is the PREP phase. Your job is to help the user define the story concept. \
The workflow after prep:

1. `/forge design {project_name}` — runs the planner agent to create the full \
story architecture (outline, style guide, bible, chapter briefs, character bios). \
User reviews the output files.
2. `/forge start {project_name}` — begins automated chapter writing with \
review/revision loops. Pauses after chapter 1 for review.

## What YOU do in this phase

Work through these areas conversationally — ask questions, make suggestions, \
refine their ideas:

1. **Premise & hook** — What is this story about? What makes it compelling?
2. **Main characters** — Who are the protagonists, antagonists, key supporting cast?
3. **World & setting** — Where and when does this take place? What are the rules?
4. **Tone & style** — Dark? Funny? Literary? Fast-paced? What POV and tense?
5. **Structure** — How many chapters? Complete arc or episodic? Length targets?

## Writing files

Save the premise and story concept to the forge plan directory:
- Use write_file with directory "forge", path "{project_name}/plan/premise.md"
- Update this file as decisions evolve

Create lore entries for characters, locations, and world details:
- Use write_file with directory "lore" to write to characters/, locations/, etc.
- Be concrete — full physical descriptions, personalities, motivations

**IMPORTANT: Do NOT write or edit manifest.yaml.** The manifest is managed \
automatically by the forge pipeline. Only write to plan/ files and lore files.

Be creative and opinionated when filling in gaps — you are a co-author, not \
just a transcriber. Make bold, specific choices that serve the story.

When the user is satisfied with the plan, they can say "proceed" to advance \
to the automated design phase, or run /forge start {project_name}."""


COUNCIL_MODE_PROMPT = """## Mode: Council

You are in council mode. Every message the user sends is automatically routed \
through a council of AI perspectives before reaching you. You will receive the \
council members' responses and must synthesize them into a coherent, helpful answer.

When you receive council responses:
1. Identify points of **agreement** across members
2. Note any **disagreements** or alternative perspectives
3. Highlight **unique insights** from individual members
4. Provide your **synthesis** — the best answer drawing from all perspectives
5. Be transparent about where council members disagreed

If the council members have no relevant expertise on the topic, say so and \
provide your own best answer instead of pretending the council was helpful.

Maintain your persona and voice while synthesizing — you are the narrator \
presenting the council's wisdom, not a neutral aggregator."""


class Orchestrator:
    """Routes user intent. The only agent the user talks to directly."""

    def __init__(
        self,
        librarian: Librarian,
        writer: ProseWriter,
        config: AppConfig,
        client=None,
        model: str | None = None,
    ):
        self.librarian = librarian
        self.writer = writer
        self.config = config
        self.model = model or config.models.orchestrator
        self.client: LLMClient = client or self._default_client()
        self.persona = self._load_persona()
        self.conversation_history: list[dict] = []

        # Mode state
        self.mode: Mode = Mode.GENERAL
        self.active_project: str | None = None  # e.g. "pale-city-novel"
        self.active_file: str | None = None     # e.g. "chapter-03.md"
        self.pending_content: str | None = None  # Writer mode: awaiting accept/reject
        self.last_prompt: str | None = None      # For regenerate
        self.forge_project: str | None = None    # Active forge project name

        # Web search (optional)
        self.web_search = None
        if config.web_search.provider:
            from src.web_search import WebSearch
            self.web_search = WebSearch(config.web_search)

        # Build tools list — add web_search only if configured
        self.tools = list(ORCHESTRATOR_TOOLS)
        if self.web_search and self.web_search.enabled:
            self.tools.append(WEB_SEARCH_TOOL)

        log.info(
            "Orchestrator initialized (persona: %d tokens, model: %s, web_search: %s)",
            estimate_tokens(self.persona),
            self.model,
            config.web_search.provider or "disabled",
        )

    @staticmethod
    def _default_client() -> LLMClient:
        raise RuntimeError("No LLM client configured. Set up a provider in the Model settings.")

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

        # Track forge project name
        if mode == Mode.FORGE and project:
            self.forge_project = project

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
        elif self.mode == Mode.FORGE:
            return self.config.paths.forge
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

    def list_projects(self, mode: str | None = None) -> dict:
        """List available projects for the given mode (or current mode)."""
        if mode:
            base = self._base_dir_for_mode(mode)
        else:
            base = self._mode_base_dir()
        if base is None or not base.exists():
            return {"projects": []}

        projects = []
        for d in sorted(base.iterdir()):
            if d.is_dir():
                files = sorted(f.name for f in d.glob("*.md"))
                projects.append({"name": d.name, "files": files})

        return {"projects": projects}

    def _base_dir_for_mode(self, mode: str) -> Path | None:
        """Base content directory for a given mode string."""
        mode_lower = mode.lower()
        if mode_lower == "writer":
            return self.config.paths.writing
        elif mode_lower == "roleplay":
            return self.config.paths.chats
        elif mode_lower == "forge":
            return self.config.paths.forge
        return None

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

    def _build_character_section(self) -> str:
        """Build the character card section for roleplay mode."""
        from src.character_cards import load_card, card_to_prompt
        parts = []

        ai_name = self.config.roleplay.ai_character
        if ai_name:
            card = load_card(self.config.paths.character_cards / f"{ai_name}.yaml")
            if card:
                parts.append(f"\n## Your Character\nYou are playing the following character:\n{card_to_prompt(card)}")
                if card.get("greeting") and not self.conversation_history:
                    parts.append(f"\nUse this as your opening message if starting a new conversation:\n{card['greeting']}")

        user_name = self.config.roleplay.user_character
        if user_name:
            card = load_card(self.config.paths.character_cards / f"{user_name}.yaml")
            if card:
                parts.append(f"\n## The User's Character\nThe user is playing:\n{card_to_prompt(card)}")

        return "\n".join(parts)

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
            character_section = self._build_character_section()
            parts.append(ROLEPLAY_MODE_PROMPT.format(
                project_name=self.active_project or "(none)",
                current_file=self.active_file or "(none)",
                file_context=file_context,
                character_section=character_section,
            ))

        elif self.mode == Mode.FORGE:
            project_name = self.forge_project or "(none)"
            parts.append(FORGE_MODE_PROMPT.format(project_name=project_name))
            # Include any existing premise for context
            if self.forge_project:
                premise_path = self.config.paths.forge / self.forge_project / "plan" / "premise.md"
                if premise_path.exists():
                    premise = premise_path.read_text(encoding="utf-8")
                    parts.append(f"## Current Premise\n\n{premise}")

        elif self.mode == Mode.COUNCIL:
            parts.append(COUNCIL_MODE_PROMPT)

        # Inject story state if it exists (outside the cached system prompt)
        state_content = self._load_state_summary()
        if state_content:
            parts.append(f"\n## Story State\n\n{state_content}")

        parts.append(
            "\n## Tools\n\n"
            "Use tools proactively. Don't ask the user to do things you can do yourself.\n"
            "For technical/factual questions unrelated to the story, use delegate_technical.\n"
            "Use roll_dice when randomness should influence events (combat, chance encounters, etc.).\n"
            "Use get_story_state / update_story_state to track plot threads, character conditions, "
            "and narrative metadata — this persists across turns without cluttering the prose."
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
            response = self.client.create(
                model=self.model,
                max_tokens=self.config.orchestrator.max_tokens,
                system=system_prompt,
                messages=messages,
                tools=self.tools,
            )

            if response.stop_reason == "end_turn":
                response_text = self._extract_text(response)
                break

            if response.stop_reason == "tool_use":
                asst_msg = {"role": "assistant", "content": response.content}
                # Preserve reasoning for providers that require it on tool call messages
                if response.reasoning:
                    asst_msg["reasoning"] = response.reasoning
                messages.append(asst_msg)

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

            if response.stop_reason == "max_tokens":
                log.warning("Hit max_tokens limit — returning partial output")
            else:
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

    def _call_llm_streaming(self, system_prompt, messages, tools=None):
        """Call the LLM with streaming, yielding text/reasoning deltas and a final response.

        Yields dicts:
          {"type": "text_delta", "text": "..."}
          {"type": "reasoning_delta", "text": "..."}
          {"type": "done", "response": LLMResponse}
        """
        yield from self.client.create_stream(
            model=self.model,
            max_tokens=self.config.orchestrator.max_tokens,
            system=system_prompt,
            messages=messages,
            tools=tools,
        )

    def handle_stream(self, user_input: str):
        """Process user input, yielding progress events as dicts.

        Yields dicts with 'event' key:
          - {"event": "status", "message": "..."}     — progress update
          - {"event": "tool", "name": "...", "input": {...}}  — tool being called
          - {"event": "text_delta", "text": "..."}    — partial text chunk
          - {"event": "reasoning_delta", "text": "..."}  — partial reasoning chunk
          - {"event": "done", "content": "...", "response_type": "...", "reasoning": "..."}  — final result
        """
        # Handle mode-specific commands before the LLM
        intercepted = self._handle_mode_commands(user_input)
        if intercepted:
            yield {"event": "done", "content": intercepted.content, "response_type": intercepted.response_type}
            return

        # Council mode: gather perspectives first, then synthesize
        if self.mode == Mode.COUNCIL:
            yield from self._handle_council_stream(user_input)
            return

        yield {"event": "status", "message": "Building prompt..."}

        system_prompt = self._build_system_prompt()
        self.conversation_history.append({"role": "user", "content": user_input})
        messages = list(self.conversation_history)

        response_text = ""
        reasoning_text = ""
        response_type = "discussion"
        loop_count = 0

        while True:
            loop_count += 1
            yield {"event": "status", "message": f"Thinking... (step {loop_count})"}

            response = None
            for chunk in self._call_llm_streaming(system_prompt, messages, self.tools):
                if chunk["type"] == "text_delta":
                    yield {"event": "text_delta", "text": chunk["text"]}
                elif chunk["type"] == "reasoning_delta":
                    yield {"event": "reasoning_delta", "text": chunk["text"]}
                elif chunk["type"] == "done":
                    response = chunk["response"]

            if response is None:
                log.error("Streaming completed without final response")
                break

            # Collect reasoning from response
            if response.reasoning:
                reasoning_text = response.reasoning

            if response.stop_reason == "end_turn":
                response_text = self._extract_text(response)
                break

            if response.stop_reason == "tool_use":
                asst_msg = {"role": "assistant", "content": response.content}
                # Preserve reasoning for providers that require it on tool call messages
                if response.reasoning:
                    asst_msg["reasoning"] = response.reasoning
                messages.append(asst_msg)
                tool_results = []

                for block in response.content:
                    if block.type == "tool_use":
                        yield {"event": "tool", "name": block.name, "input": block.input}

                        # Friendly status messages
                        tool_labels = {
                            "query_lore": "Querying lore...",
                            "write_prose": "Writing prose...",
                            "read_file": f"Reading {block.input.get('path', 'file')}...",
                            "write_file": f"Writing {block.input.get('path', 'file')}...",
                            "list_files": "Listing files...",
                            "search_files": "Searching files...",
                            "request_code_change": "Creating code request...",
                            "delegate_technical": "Looking that up...",
                            "roll_dice": f"Rolling {block.input.get('notation', 'dice')}...",
                            "get_story_state": "Checking story state...",
                            "update_story_state": "Updating story state...",
                            "generate_image": "Generating image...",
                            "web_search": f"Searching: {block.input.get('query', '...')[:50]}...",
                        }
                        yield {"event": "status", "message": tool_labels.get(block.name, f"Using {block.name}...")}

                        # Collect sub-status messages from tools (e.g. prose writer lore lookups)
                        sub_statuses: list[str] = []
                        def _sub_status(msg: str) -> None:
                            sub_statuses.append(msg)

                        result, rtype = self._execute_tool(block.name, block.input, status_callback=_sub_status)
                        # Yield any sub-status messages that accumulated
                        for ss in sub_statuses:
                            yield {"event": "status", "message": ss}
                        if rtype:
                            response_type = rtype
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result,
                        })

                messages.append({"role": "user", "content": tool_results})
                continue

            if response.stop_reason == "max_tokens":
                log.warning("Hit max_tokens limit — returning partial output")
            else:
                log.warning("Unexpected stop_reason: %s", response.stop_reason)
            response_text = self._extract_text(response)
            break

        response_text, response_type = self._post_generation(response_text, response_type, user_input)
        self.conversation_history.append({"role": "assistant", "content": response_text})
        self._log_response(user_input, response_text, response_type)

        done_event = {"event": "done", "content": response_text, "response_type": response_type}
        if reasoning_text:
            done_event["reasoning"] = reasoning_text
        yield done_event

    def _handle_council_stream(self, user_input: str):
        """Council mode: gather perspectives, then synthesize via normal LLM loop."""
        from src.services.council import run_council, format_council_for_orchestrator

        yield {"event": "status", "message": "Gathering council perspectives..."}

        council_dir = self.config.paths.council
        result = run_council(user_input, council_dir)

        member_count = len(result.get("members", []))
        error_count = sum(1 for m in result.get("members", []) if m.get("error"))
        yield {"event": "status", "message": f"Council: {member_count - error_count} responded, synthesizing..."}

        # Format council responses into a prompt for synthesis
        formatted = format_council_for_orchestrator(result)

        # Now run the normal LLM loop with the council's input
        yield {"event": "status", "message": "Building prompt..."}

        system_prompt = self._build_system_prompt()
        self.conversation_history.append({"role": "user", "content": user_input})
        # Use the formatted council output as the actual message to synthesize
        messages = list(self.conversation_history[:-1]) + [
            {"role": "user", "content": formatted},
        ]

        response_text = ""
        reasoning_text = ""
        response_type = "council"
        loop_count = 0

        while True:
            loop_count += 1
            yield {"event": "status", "message": f"Synthesizing... (step {loop_count})"}

            response = None
            for chunk in self._call_llm_streaming(system_prompt, messages, self.tools):
                if chunk["type"] == "text_delta":
                    yield {"event": "text_delta", "text": chunk["text"]}
                elif chunk["type"] == "reasoning_delta":
                    yield {"event": "reasoning_delta", "text": chunk["text"]}
                elif chunk["type"] == "done":
                    response = chunk["response"]

            if response is None:
                break

            if response.reasoning:
                reasoning_text = response.reasoning

            if response.stop_reason == "end_turn":
                response_text = self._extract_text(response)
                break

            if response.stop_reason == "tool_use":
                asst_msg = {"role": "assistant", "content": response.content}
                # Preserve reasoning for providers that require it on tool call messages
                if response.reasoning:
                    asst_msg["reasoning"] = response.reasoning
                messages.append(asst_msg)
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        yield {"event": "tool", "name": block.name, "input": block.input}
                        result_text, rtype = self._execute_tool(block.name, block.input)
                        if rtype:
                            response_type = rtype
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result_text,
                        })
                messages.append({"role": "user", "content": tool_results})
                continue

            response_text = self._extract_text(response)
            break

        self.conversation_history.append({"role": "assistant", "content": response_text})
        self._log_response(user_input, response_text, response_type)

        done_event = {"event": "done", "content": response_text, "response_type": response_type}
        if reasoning_text:
            done_event["reasoning"] = reasoning_text
        yield done_event

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

        if self.mode == Mode.FORGE:
            if lower in ("proceed", "start", "go"):
                return Response(
                    content=(
                        f"Planning complete! Run `/forge start {self.forge_project}` "
                        f"to kick off the automated design and writing pipeline."
                    ),
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
        self._record_event("prose_appended", {"chars": len(content)})

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
        self._record_event("entry_removed")

    # ── Tool execution ────────────────────────────────────────────────

    def _execute_tool(
        self,
        name: str,
        input_data: dict,
        status_callback: "Callable[[str], None] | None" = None,
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
                result = self.writer.write_scene(input_data["description"], context, status_callback=status_callback)
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

        elif name == "roll_dice":
            return self._tool_roll_dice(input_data), None

        elif name == "get_story_state":
            return self._tool_get_story_state(), None

        elif name == "update_story_state":
            return self._tool_update_story_state(input_data), None

        elif name == "generate_image":
            return self._tool_generate_image(input_data), None

        elif name == "web_search":
            return self._tool_web_search(input_data), None

        else:
            return json.dumps({"error": f"Unknown tool: {name}"}), None

    # ── Filesystem tool implementations ───────────────────────────────

    def _dir_map(self) -> dict[str, Path]:
        """Map directory names to paths."""
        return {
            "lore": self.config.active_lore_path,
            "story": self.config.paths.story,
            "writing": self.config.paths.writing,
            "chats": self.config.paths.chats,
            "code-requests": self.config.paths.code_requests,
            "forge": self.config.paths.forge,
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
        rel_path = input_data["path"]
        # Guard: prevent writing to forge manifest files
        if rel_path.endswith("manifest.yaml") or rel_path.endswith("manifest.yml"):
            return json.dumps({"error": "manifest.yaml is managed by the forge pipeline. Write to plan/ files instead."})
        path = self._resolve_path(input_data["directory"], rel_path)
        if path is None:
            return json.dumps({"error": "Invalid path or directory."})
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(input_data["content"], encoding="utf-8")
            return json.dumps({"status": "ok", "path": rel_path})
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
        response = self.client.create(
            model=self.model,
            max_tokens=2048,
            system="You are a helpful technical assistant. Answer accurately and concisely.",
            messages=[{"role": "user", "content": input_data["query"]}],
        )
        return response.content[0].text

    # ── Dice and state tools ─────────────────────────────────────────

    def _tool_roll_dice(self, input_data: dict) -> str:
        """Parse dice notation and return results. Pure RNG, no LLM."""
        notation = input_data["notation"].strip().lower()
        reason = input_data.get("reason", "")

        try:
            result = _parse_and_roll(notation)
        except ValueError as e:
            return json.dumps({"error": str(e)})

        result["reason"] = reason
        log.info("Dice roll: %s = %d (%s)", notation, result["total"], reason)
        self._record_event("dice_roll", {"notation": notation, "total": result["total"], "reason": reason})
        return json.dumps(result)

    def _record_event(self, event_type: str, details: dict | None = None) -> None:
        """Record an event in the state file's event log.

        Maintains:
          _event_counter: monotonic int, incremented on every event
          _events: list of recent events (capped at 50), each with counter, timestamp, type, details
        """
        path = self._state_file_path()
        if path is None:
            return

        try:
            state: dict = {}
            if path.exists():
                existing = yaml.safe_load(path.read_text(encoding="utf-8"))
                if isinstance(existing, dict):
                    state = existing

            counter = state.get("_event_counter", 0) + 1
            state["_event_counter"] = counter
            state["_last_updated"] = datetime.now().isoformat()

            event_entry = {
                "n": counter,
                "t": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "type": event_type,
            }
            if details:
                event_entry["details"] = details

            events = state.get("_events", [])
            events.append(event_entry)
            # Keep only the last 50 events to avoid unbounded growth
            state["_events"] = events[-50:]

            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                yaml.dump(state, default_flow_style=False, allow_unicode=True),
                encoding="utf-8",
            )
        except Exception as e:
            log.warning("Failed to record event: %s", e)

    def _load_state_summary(self) -> str:
        """Load the state file contents as a YAML string for prompt injection."""
        path = self._state_file_path()
        if path is None or not path.exists():
            return ""
        try:
            content = path.read_text(encoding="utf-8")
            # Skip if empty or just metadata
            state = yaml.safe_load(content)
            if not state or (len(state) == 1 and "_last_updated" in state):
                return ""
            # Expose the event counter but not the full event log
            display = {k: v for k, v in state.items() if not k.startswith("_")}
            counter = state.get("_event_counter", 0)
            if counter:
                display["_update_count"] = counter
            return yaml.dump(display, default_flow_style=False, allow_unicode=True).strip()
        except Exception:
            return ""

    def _state_file_path(self) -> Path | None:
        """Get the companion .state.yaml path for the active file."""
        active = self._active_file_path()
        if active is None:
            # No active file — use a session-level state file
            if self.mode == Mode.WRITER:
                base = self.config.paths.writing
            elif self.mode == Mode.ROLEPLAY:
                base = self.config.paths.chats
            else:
                base = self.config.paths.story

            project = self.active_project or "_general"
            return base / project / "_session.state.yaml"

        # Companion file: chapter-03.md → chapter-03.state.yaml
        return active.with_suffix(".state.yaml")

    def _tool_get_story_state(self) -> str:
        """Read the companion state file."""
        path = self._state_file_path()
        if path is None or not path.exists():
            return json.dumps({"state": {}, "note": "No state file yet. Use update_story_state to create one."})

        try:
            content = path.read_text(encoding="utf-8")
            state = yaml.safe_load(content) or {}
            return json.dumps({"state": state, "path": str(path.name)})
        except Exception as e:
            return json.dumps({"error": f"Failed to read state: {e}"})

    def _tool_update_story_state(self, input_data: dict) -> str:
        """Merge updates into the companion state file."""
        path = self._state_file_path()
        if path is None:
            return json.dumps({"error": "No active context for state tracking."})

        try:
            # Load existing state
            state: dict = {}
            if path.exists():
                existing = yaml.safe_load(path.read_text(encoding="utf-8"))
                if isinstance(existing, dict):
                    state = existing

            # Remove keys if requested
            for key in input_data.get("remove_keys", []):
                state.pop(key, None)

            # Deep merge updates
            _deep_merge(state, input_data.get("updates", {}))

            # Add metadata
            state["_last_updated"] = datetime.now().isoformat()

            # Write back
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(yaml.dump(state, default_flow_style=False, allow_unicode=True), encoding="utf-8")

            log.info("Story state updated: %s", path.name)
            self._record_event("state_updated", {"keys": list(input_data.get("updates", {}).keys())})
            return json.dumps({"status": "ok", "state": state, "path": str(path.name)})
        except Exception as e:
            return json.dumps({"error": f"Failed to update state: {e}"})

    def _tool_generate_image(self, input_data: dict) -> str:
        """Generate an image via the imagegen service."""
        from src.services.imagegen import generate_image
        result = generate_image(input_data["prompt"])
        if result.success:
            return json.dumps({
                "status": "ok",
                "image_url": result.image_url,
                "image_path": result.image_path,
            })
        return json.dumps({"status": "not_configured", "error": result.error})

    def _tool_web_search(self, input_data: dict) -> str:
        """Search the web via the configured search provider."""
        if not self.web_search or not self.web_search.enabled:
            return json.dumps({"error": "Web search not configured"})
        from src.web_search import format_results_for_llm
        response = self.web_search.search(input_data["query"])
        return format_results_for_llm(response)

    # ── Utilities ─────────────────────────────────────────────────────

    def _extract_text(self, response: LLMResponse) -> str:
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


# ── Module-level helpers ─────────────────────────────────────────────

def _parse_and_roll(notation: str) -> dict:
    """Parse dice notation like '2d6', '1d20+5', '4d6kh3' and return results.

    Supports:
      - NdS: roll N dice with S sides
      - +/-M: add/subtract modifier
      - kh/klN: keep highest/lowest N dice
    """
    m = re.match(
        r"(\d+)d(\d+)"           # NdS
        r"(?:(kh|kl)(\d+))?"     # optional keep highest/lowest
        r"([+-]\d+)?$",          # optional modifier
        notation.strip(),
    )
    if not m:
        raise ValueError(f"Invalid dice notation: {notation}. Use format like '2d6', '1d20+5', '4d6kh3'.")

    count = int(m.group(1))
    sides = int(m.group(2))
    keep_mode = m.group(3)       # 'kh' or 'kl' or None
    keep_count = int(m.group(4)) if m.group(4) else None
    modifier = int(m.group(5)) if m.group(5) else 0

    if count < 1 or count > 100:
        raise ValueError("Dice count must be 1-100.")
    if sides < 2 or sides > 1000:
        raise ValueError("Dice sides must be 2-1000.")

    rolls = [random.randint(1, sides) for _ in range(count)]

    kept = rolls
    dropped: list[int] = []
    if keep_mode and keep_count:
        sorted_rolls = sorted(rolls, reverse=(keep_mode == "kh"))
        kept = sorted_rolls[:keep_count]
        dropped = sorted_rolls[keep_count:]

    total = sum(kept) + modifier

    result: dict = {
        "notation": notation,
        "rolls": rolls,
        "total": total,
    }
    if keep_mode:
        result["kept"] = kept
        result["dropped"] = dropped
    if modifier:
        result["modifier"] = modifier
        result["subtotal"] = sum(kept)

    return result


def _deep_merge(base: dict, updates: dict) -> None:
    """Recursively merge updates into base dict, mutating base."""
    for key, value in updates.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
