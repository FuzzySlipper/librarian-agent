"""Main entry point for the Narrative Orchestration System.

Stage 2: Librarian interactive mode.
Stage 3: Adds Prose Writer with scene generation.
Stage 4: Will add Orchestrator with full routing.
"""

import argparse
import logging
import sys
from pathlib import Path

from src.agents.librarian import Librarian, _print_result as print_lore
from src.agents.prose_writer import ProseWriter, _load_story_context, _print_result as print_prose
from src.config import load_config


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(description="Narrative Orchestration System")
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    parser.add_argument("--env", type=Path, default=None)
    parser.add_argument("--cli", action="store_true", help="Run in CLI mode")
    args = parser.parse_args()

    config = load_config(config_path=args.config, env_path=args.env)

    librarian = Librarian(config)
    writer = ProseWriter(librarian, config)

    print("Narrative System — Stage 3")
    print(librarian.get_lore_summary())
    print()
    print("Commands:")
    print("  /lore <query>    — Ask the Librarian a lore question")
    print("  /write <scene>   — Generate a scene with the Prose Writer")
    print("  /summary         — Show loaded lore summary")
    print("  quit             — Exit")
    print()
    print("Anything without a command prefix is sent to the Prose Writer.\n")

    story_context = _load_story_context(config.paths.story)

    while True:
        try:
            user_input = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not user_input or user_input.lower() == "quit":
            break

        if user_input.startswith("/lore "):
            query = user_input[6:].strip()
            if query:
                result = librarian.query(query)
                print_lore(result)

        elif user_input.startswith("/write "):
            description = user_input[7:].strip()
            if description:
                result = writer.write_scene(description, story_context)
                print_prose(result)
                story_context = result.generated_text

        elif user_input == "/summary":
            print(librarian.get_lore_summary())
            print()

        else:
            # Default: treat as scene description
            result = writer.write_scene(user_input, story_context)
            print_prose(result)
            story_context = result.generated_text


if __name__ == "__main__":
    main()
