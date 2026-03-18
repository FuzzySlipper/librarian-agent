"""StoryForge planner agent — stage 2 design phase.

Reads the premise and existing lore, then produces:
  - outline.md (full plot arc)
  - style.md (narrative voice spec)
  - bible.md (timeline, relationships, key facts)
  - ch-NN-brief.md (chapter implementation specs)
  - Character bios written to lore/

Runs as a tool-use loop (like ProseWriter) so the planner can write
multiple files across multiple tool calls in a single session.
"""

import json
import logging
from pathlib import Path
from typing import Callable, Generator

import anthropic

log = logging.getLogger(__name__)


# ── Tools available to the planner ───────────────────────────────────

PLANNER_TOOLS = [
    {
        "name": "write_plan_file",
        "description": (
            "Write a file to the forge project's plan/ directory. "
            "Use for: outline.md, style.md, bible.md."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "filename": {"type": "string", "description": "Filename (e.g. 'outline.md')"},
                "content": {"type": "string", "description": "Full file content."},
            },
            "required": ["filename", "content"],
        },
    },
    {
        "name": "write_chapter_brief",
        "description": (
            "Write a chapter brief to the chapters/ directory. "
            "Filename should be ch-NN-brief.md (e.g. ch-01-brief.md)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "filename": {"type": "string", "description": "e.g. 'ch-01-brief.md'"},
                "content": {"type": "string", "description": "Full chapter brief content."},
            },
            "required": ["filename", "content"],
        },
    },
    {
        "name": "write_lore_file",
        "description": (
            "Write a lore entry (character bio, location, etc.) to the lore directory. "
            "Provide a relative path like 'characters/elena-vasquez.md'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative path within lore dir."},
                "content": {"type": "string", "description": "Full lore entry content."},
            },
            "required": ["path", "content"],
        },
    },
]


def _load_system_prompt(prompts_dir: Path) -> str:
    """Load the planner system prompt from forge-prompts/planner.md."""
    prompt_file = prompts_dir / "planner.md"
    if prompt_file.exists():
        return prompt_file.read_text(encoding="utf-8")
    # Fallback built-in prompt
    return _DEFAULT_PLANNER_PROMPT


_DEFAULT_PLANNER_PROMPT = """\
You are a master story architect. Your job is to take a story premise and \
existing world lore, then design a complete story structure ready for \
chapter-by-chapter writing by separate writing agents.

You MUST produce ALL of the following by calling the appropriate tools:

1. **outline.md** (write_plan_file) — Complete plot arc broken into chapters. \
Include: inciting incident, rising action, midpoint, climax, resolution. \
For each chapter, one paragraph summarizing what happens.

2. **style.md** (write_plan_file) — Detailed narrative voice specification: \
POV (first/third/omniscient), tense (past/present), tone, prose characteristics, \
dialogue style, pacing preferences, any stylistic quirks. This becomes the \
writing prompt for the chapter writing agents, so be very specific.

3. **bible.md** (write_plan_file) — Story bible reference document: \
timeline of events, character relationship map, key world rules, important \
objects/locations, any constraints the writing agents need to know.

4. **Chapter briefs** (write_chapter_brief) — One per chapter, named ch-01-brief.md, \
ch-02-brief.md, etc. Each brief is an IMPLEMENTATION SPEC, not a summary. Include:
   - Required plot beats and events that MUST happen
   - Characters present and their emotional arcs in this chapter
   - Foreshadowing to plant (but NOT future plot spoilers)
   - What the reader should know and feel by chapter end
   - Connection to the previous chapter's ending
   - Any specific scenes or set pieces
   - Approximate target length guidance

5. **Character bios** (write_lore_file) — For every significant character, \
write a detailed lore entry to characters/<name>.md. Include physical \
description (this prevents visual drift), personality, motivations, speech \
patterns, and key relationships. Physical details are especially important \
as writing agents will reference these.

Think of chapter briefs as work orders for a contractor — specific enough that \
the writing agent can produce the chapter without needing to ask questions, \
but creative enough to leave room for good prose.
"""


def run_planner(
    *,
    premise: str,
    lore_context: str,
    plan_dir: Path,
    chapters_dir: Path,
    lore_dir: Path,
    prompts_dir: Path,
    model: str,
    stats_callback: Callable | None = None,
) -> Generator[dict, None, None]:
    """Run the planner agent tool-use loop.

    Yields events as the planner writes files.
    """
    system_prompt = _load_system_prompt(prompts_dir)

    user_prompt = f"## Story Premise\n\n{premise}"
    if lore_context.strip():
        user_prompt += f"\n\n## Existing World Lore\n{lore_context}"

    user_prompt += (
        "\n\nNow design the complete story structure. Use the tools to write "
        "all required files. Start with the outline, then style, then bible, "
        "then character bios, then chapter briefs."
    )

    client = anthropic.Anthropic()
    messages: list[dict] = [{"role": "user", "content": user_prompt}]

    while True:
        response = client.messages.create(
            model=model,
            max_tokens=16384,
            system=system_prompt,
            messages=messages,
            tools=PLANNER_TOOLS,
        )

        if stats_callback:
            stats_callback(
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                agent_calls=1,
            )

        if response.stop_reason == "end_turn":
            break

        if response.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": response.content})

            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue

                result_text = _execute_planner_tool(
                    block.name, block.input, plan_dir, chapters_dir, lore_dir,
                )
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result_text,
                })
                yield {"event": "file_written", "tool": block.name,
                       "path": block.input.get("filename") or block.input.get("path", "")}

            messages.append({"role": "user", "content": tool_results})
            continue

        log.warning("Planner: unexpected stop_reason: %s", response.stop_reason)
        break


def _execute_planner_tool(
    name: str, input_data: dict, plan_dir: Path, chapters_dir: Path, lore_dir: Path,
) -> str:
    """Execute a planner tool call and return a result string."""
    try:
        if name == "write_plan_file":
            filename = input_data["filename"]
            # Sanitize
            if "/" in filename or ".." in filename:
                return json.dumps({"error": "Invalid filename"})
            path = plan_dir / filename
            path.write_text(input_data["content"], encoding="utf-8")
            return json.dumps({"status": "ok", "path": str(path)})

        elif name == "write_chapter_brief":
            filename = input_data["filename"]
            if ".." in filename:
                return json.dumps({"error": "Invalid filename"})
            path = chapters_dir / filename
            path.write_text(input_data["content"], encoding="utf-8")
            return json.dumps({"status": "ok", "path": str(path)})

        elif name == "write_lore_file":
            rel_path = input_data["path"]
            if ".." in rel_path:
                return json.dumps({"error": "Invalid path"})
            path = lore_dir / rel_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(input_data["content"], encoding="utf-8")
            return json.dumps({"status": "ok", "path": str(path)})

        else:
            return json.dumps({"error": f"Unknown tool: {name}"})

    except Exception as e:
        log.error("Planner tool %s failed: %s", name, e)
        return json.dumps({"error": str(e)})
