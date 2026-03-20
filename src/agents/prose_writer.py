"""Prose Writer agent — generates scenes, auto-querying the Librarian via tool use.

The Writer receives a scene description and story context, then generates prose.
When it needs lore details, it calls the query_lore tool, which routes to the
Librarian. The tool-use loop continues until the model produces final text.
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from src.agents.librarian import Librarian
from src.config import AppConfig, load_config
from src.llm import LLMClient
from src.models import ProseResult
from src.utils.file_utils import append_to_story

log = logging.getLogger(__name__)

LORE_TOOL = {
    "name": "query_lore",
    "description": (
        "Query the Librarian for lore details relevant to the scene being written. "
        "Use this whenever you need to verify character details, location descriptions, "
        "faction relationships, historical events, or any world-building facts. "
        "Always query before writing details you're unsure about."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "A specific question about the story's world, characters, or events.",
            }
        },
        "required": ["query"],
    },
}

WRITER_SYSTEM_TEMPLATE = """You are a skilled prose writer working on a long-form narrative.

Your job is to write scenes based on the user's description. Follow these rules:

1. Before writing, use the query_lore tool to look up any character details, locations, or world facts you'll need. Query multiple times if the scene involves several characters or locations.
2. Stay faithful to established lore — never contradict what the Librarian returns.
3. Maintain consistency with the story context provided below.

## Writing Style

{writing_style}

{story_context_section}"""


class ProseWriter:
    """Generates scenes, calling the Librarian automatically via tool use."""

    def __init__(self, librarian: Librarian, config: AppConfig, client: LLMClient | None = None, model: str | None = None):
        self.librarian = librarian
        self.config = config
        self.model = model or config.models.prose_writer
        self.client: LLMClient = client or self._default_client()
        self.writing_style = self._load_writing_style()

    @staticmethod
    def _default_client() -> LLMClient:
        from src.llm_anthropic import AnthropicClient
        import anthropic
        return AnthropicClient(anthropic.Anthropic())

    def _load_writing_style(self) -> str:
        """Load the active writing style from file."""
        style_path = self.config.active_writing_style_path
        if style_path.exists():
            content = style_path.read_text(encoding="utf-8").strip()
            log.info("Loaded writing style: %s", style_path.stem)
            return content

        log.warning("Writing style not found at %s, using built-in default", style_path)
        return (
            "Write in third person, past tense. Focus on scene, dialogue, "
            "and character interiority. Show, don't tell. End scenes at "
            "natural stopping points."
        )

    def write_scene(self, description: str, story_context: str = "") -> ProseResult:
        """Generate a scene, automatically querying lore as needed."""
        log.info("Writing scene: %s", description[:100])

        system_prompt = self._build_system_prompt(story_context)
        messages: list[dict] = [{"role": "user", "content": description}]
        lore_queries: list[str] = []

        # Tool-use loop: model may call query_lore multiple times
        while True:
            response = self.client.create(
                model=self.model,
                max_tokens=self.config.prose_writer.max_tokens_per_scene,
                system=system_prompt,
                messages=messages,
                tools=[LORE_TOOL],
            )

            if response.stop_reason == "end_turn":
                break

            if response.stop_reason == "tool_use":
                # Append assistant's response (contains tool_use blocks)
                messages.append({"role": "assistant", "content": response.content})

                # Process all tool calls in this response
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        query = block.input["query"]
                        lore_queries.append(query)
                        log.info("Lore query: %s", query)

                        lore_bundle = self.librarian.query(query)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps({
                                "passages": lore_bundle.relevant_passages,
                                "sources": lore_bundle.source_files,
                                "confidence": lore_bundle.confidence,
                            }),
                        })

                messages.append({"role": "user", "content": tool_results})
                continue

            # Unexpected stop reason — break to avoid infinite loop
            log.warning("Unexpected stop_reason: %s", response.stop_reason)
            break

        # Extract the final text from the response
        generated_text = self._extract_text(response)

        result = ProseResult(
            generated_text=generated_text,
            lore_queries_made=lore_queries,
            word_count=len(generated_text.split()),
        )

        # Auto-append to story file if configured
        if self.config.prose_writer.auto_append_to_story:
            append_to_story(self.config.paths.story, generated_text)
            log.info("Appended %d words to story file", result.word_count)

        return result

    def _build_system_prompt(self, story_context: str) -> str:
        """Build the writer's system prompt with optional story context."""
        if story_context.strip():
            context_section = (
                "## Story So Far (maintain consistency with this):\n\n"
                f"{story_context}"
            )
        else:
            context_section = (
                "## Story Context:\n\n"
                "No prior story context. This is the beginning of the narrative."
            )

        return WRITER_SYSTEM_TEMPLATE.format(
            writing_style=self.writing_style,
            story_context_section=context_section,
        )

    def _extract_text(self, response) -> str:
        """Extract text content from the final response."""
        parts = []
        for block in response.content:
            if block.type == "text":
                parts.append(block.text)
        return "\n\n".join(parts)


def _load_story_context(story_dir: Path, max_chars: int = 8000) -> str:
    """Load the tail end of the current story draft for context."""
    draft = story_dir / "current-draft.md"
    if not draft.exists():
        return ""

    content = draft.read_text(encoding="utf-8")
    if len(content) <= max_chars:
        return content

    # Return the last max_chars characters, breaking at a paragraph boundary
    truncated = content[-max_chars:]
    # Find the first paragraph break to avoid starting mid-sentence
    newline_pos = truncated.find("\n\n")
    if newline_pos != -1 and newline_pos < len(truncated) // 2:
        truncated = truncated[newline_pos + 2:]

    return truncated


def main() -> None:
    """CLI entry point for the Prose Writer."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(description="Generate prose scenes")
    parser.add_argument("--scene", "-s", type=str, help="Scene description to write")
    parser.add_argument("--config", type=Path, default=Path("build/config.yaml"))
    parser.add_argument("--env", type=Path, default=None)
    parser.add_argument("--no-append", action="store_true", help="Don't append to story file")
    parser.add_argument("--interactive", "-i", action="store_true", help="Interactive mode")
    args = parser.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Error: ANTHROPIC_API_KEY not set.", file=sys.stderr)
        sys.exit(1)

    config = load_config(config_path=args.config, env_path=args.env)
    if args.no_append:
        config.prose_writer.auto_append_to_story = False

    librarian = Librarian(config)
    writer = ProseWriter(librarian, config)

    story_context = _load_story_context(config.paths.story)

    if args.interactive:
        print("Prose Writer interactive mode. Describe a scene, or 'quit' to exit.\n")
        while True:
            try:
                description = input("Scene> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not description or description.lower() == "quit":
                break
            result = writer.write_scene(description, story_context)
            _print_result(result)
            # Update context with what we just wrote
            story_context = result.generated_text
        return

    if args.scene:
        result = writer.write_scene(args.scene, story_context)
        _print_result(result)
        return

    parser.print_help()


def _print_result(result: ProseResult) -> None:
    """Pretty-print a ProseResult."""
    print(f"\n{'─' * 60}")
    print(result.generated_text)
    print(f"{'─' * 60}")
    print(f"Words: {result.word_count}")
    if result.lore_queries_made:
        print(f"Lore queries: {len(result.lore_queries_made)}")
        for q in result.lore_queries_made:
            print(f"  - {q}")
    print()


if __name__ == "__main__":
    main()
