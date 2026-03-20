"""Librarian agent — loads lore files and answers queries from cached content.

The Librarian loads all lore markdown files at startup into its system prompt.
Anthropic's prompt caching means the lore is only charged once, and subsequent
queries are cheap. When lore outgrows the context window, this switches to a
two-phase index lookup (see ADR-002 in DECISIONS.md).
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from src.config import AppConfig, load_config
from src.llm import LLMClient
from src.models import LoreBundle
from src.utils.file_utils import estimate_tokens, load_lore_files

log = logging.getLogger(__name__)

LIBRARIAN_SYSTEM_TEMPLATE = """You are the Librarian, a precise lore retrieval system for a creative writing project.

You have been given the complete lore corpus below. When asked a question:

1. Search the lore for relevant information
2. Return ONLY information that exists in the lore files — never invent details
3. Quote or closely paraphrase the source material
4. Cite which file each piece of information comes from
5. If the answer is not in the lore, say so clearly and set confidence to "low"

Respond in JSON format:
{{
    "relevant_passages": ["passage 1 from the lore", "passage 2 from the lore"],
    "source_files": ["characters/elena-vasquez.md", "locations/the-pale-city.md"],
    "confidence": "high"
}}

Use "high" confidence when the lore directly answers the question.
Use "medium" when you're inferring from partial information.
Use "low" when the lore doesn't contain the answer.

---

LORE CORPUS:

{lore_content}"""


class Librarian:
    """Loads lore files once, answers queries from cached content."""

    def __init__(self, config: AppConfig, client: LLMClient | None = None, model: str | None = None):
        self.config = config
        self.model = model or config.models.librarian
        self.client: LLMClient = client or self._default_client()
        self.lore_path = config.active_lore_path
        self.lore = load_lore_files(self.lore_path)
        self.system_prompt = self._build_system_prompt()

        token_est = estimate_tokens(self.system_prompt)
        log.info(
            "Librarian initialized: %d lore files from %s, ~%d tokens in system prompt",
            len(self.lore),
            self.lore_path,
            token_est,
        )

    @staticmethod
    def _default_client() -> LLMClient:
        from src.llm_anthropic import AnthropicClient
        import anthropic
        return AnthropicClient(anthropic.Anthropic())

    def _build_system_prompt(self) -> str:
        """Build system prompt with all lore content embedded."""
        sections: list[str] = []
        for filepath, content in self.lore.items():
            sections.append(f"### File: {filepath}\n\n{content}")

        lore_content = "\n\n---\n\n".join(sections) if sections else "(No lore files found)"
        return LIBRARIAN_SYSTEM_TEMPLATE.format(lore_content=lore_content)

    def query(self, query: str) -> LoreBundle:
        """Query the lore corpus and return structured results."""
        log.debug("Librarian query: %s", query)

        response = self.client.create(
            model=self.model,
            max_tokens=self.config.librarian.max_tokens_per_query,
            system=[{
                "type": "text",
                "text": self.system_prompt,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": query}],
        )

        raw_text = response.content[0].text

        return self._parse_response(raw_text)

    def _parse_response(self, raw_text: str) -> LoreBundle:
        """Parse the LLM's JSON response into a LoreBundle."""
        try:
            # Try to extract JSON from the response
            text = raw_text.strip()
            # Handle case where model wraps JSON in markdown code blocks
            if text.startswith("```"):
                text = text.split("\n", 1)[1]  # Remove opening ```json
                text = text.rsplit("```", 1)[0]  # Remove closing ```
                text = text.strip()

            data = json.loads(text)
            return LoreBundle(**data)
        except (json.JSONDecodeError, KeyError, ValueError):
            log.warning("Failed to parse Librarian response as JSON, wrapping as raw passage")
            return LoreBundle(
                relevant_passages=[raw_text],
                source_files=[],
                confidence="medium",
            )

    def get_lore_summary(self) -> str:
        """Return a summary of loaded lore for diagnostics."""
        lines = [f"Loaded {len(self.lore)} lore files:"]
        for filepath in sorted(self.lore):
            char_count = len(self.lore[filepath])
            lines.append(f"  {filepath} ({char_count:,} chars)")
        lines.append(f"Total system prompt: ~{estimate_tokens(self.system_prompt):,} tokens")
        return "\n".join(lines)


def main() -> None:
    """CLI entry point for testing the Librarian."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(description="Query the Librarian")
    parser.add_argument("--query", "-q", type=str, help="Lore query to run")
    parser.add_argument("--config", type=Path, default=Path("build/config.yaml"), help="Config file path")
    parser.add_argument("--env", type=Path, default=None, help="Path to .env file")
    parser.add_argument("--summary", action="store_true", help="Print lore summary and exit")
    parser.add_argument("--interactive", "-i", action="store_true", help="Interactive query mode")
    args = parser.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Error: ANTHROPIC_API_KEY not set. Create a .env file or export it.", file=sys.stderr)
        sys.exit(1)

    config = load_config(config_path=args.config, env_path=args.env)
    librarian = Librarian(config)

    if args.summary:
        print(librarian.get_lore_summary())
        return

    if args.interactive:
        print("Librarian interactive mode. Type 'quit' to exit.\n")
        while True:
            try:
                query = input("Query> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not query or query.lower() == "quit":
                break
            result = librarian.query(query)
            _print_result(result)
        return

    if args.query:
        result = librarian.query(args.query)
        _print_result(result)
        return

    parser.print_help()


def _print_result(result: LoreBundle) -> None:
    """Pretty-print a LoreBundle to stdout."""
    print(f"\nConfidence: {result.confidence}")
    if result.source_files:
        print(f"Sources: {', '.join(result.source_files)}")
    print()
    for i, passage in enumerate(result.relevant_passages, 1):
        print(f"[{i}] {passage}")
    print()


if __name__ == "__main__":
    main()
