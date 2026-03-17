"""Main entry point for the Narrative Orchestration System.

Stage 2: Runs the Librarian in interactive mode.
Stage 3: Will add Prose Writer.
Stage 4: Will add Orchestrator with full routing.
"""

import argparse
import logging
import sys
from pathlib import Path

from src.agents.librarian import Librarian, _print_result
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

    # Stage 2: Librarian-only interactive mode
    print("Narrative System — Stage 2 (Librarian)")
    print("Type a lore query, or 'quit' to exit.\n")

    librarian = Librarian(config)
    print(librarian.get_lore_summary())
    print()

    while True:
        try:
            query = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not query or query.lower() == "quit":
            break
        result = librarian.query(query)
        _print_result(result)


if __name__ == "__main__":
    main()
