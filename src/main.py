"""Main entry point for the Narrative Orchestration System.

Stage 4: Full Orchestrator with routing, persona, and tools.
"""

import argparse
import logging
import sys
from pathlib import Path

from src.agents.librarian import Librarian
from src.agents.orchestrator import Orchestrator
from src.agents.prose_writer import ProseWriter
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
    parser.add_argument(
        "--debug", action="store_true", help="Enable debug logging"
    )
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    config = load_config(config_path=args.config, env_path=args.env)

    # Initialize agent chain
    librarian = Librarian(config)
    writer = ProseWriter(librarian, config)
    orchestrator = Orchestrator(librarian, writer, config)

    print("Narrative Orchestration System")
    print(librarian.get_lore_summary())
    print()
    print("Talk naturally. The system routes your input automatically.")
    print("Type 'quit' to exit.\n")

    while True:
        try:
            user_input = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not user_input or user_input.lower() == "quit":
            break

        response = orchestrator.handle(user_input)
        print(f"\n{response.content}\n")


if __name__ == "__main__":
    main()
