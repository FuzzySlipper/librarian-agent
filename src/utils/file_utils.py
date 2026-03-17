"""File utilities for safe lore loading and story appending."""

import logging
from pathlib import Path

log = logging.getLogger(__name__)


def load_lore_files(lore_dir: Path) -> dict[str, str]:
    """Load all markdown files from the lore directory tree.

    Returns a dict mapping relative file paths to their content.
    """
    lore: dict[str, str] = {}

    if not lore_dir.exists():
        log.warning("Lore directory does not exist: %s", lore_dir)
        return lore

    for file_path in sorted(lore_dir.rglob("*.md")):
        try:
            content = file_path.read_text(encoding="utf-8")
            relative = str(file_path.relative_to(lore_dir))
            lore[relative] = content
            log.debug("Loaded lore file: %s (%d chars)", relative, len(content))
        except Exception:
            log.exception("Failed to read lore file: %s", file_path)

    log.info("Loaded %d lore files from %s", len(lore), lore_dir)
    return lore


def append_to_story(story_dir: Path, content: str, filename: str = "current-draft.md") -> Path:
    """Append content to the story file. Creates the file if it doesn't exist."""
    story_dir.mkdir(parents=True, exist_ok=True)
    story_path = story_dir / filename

    with open(story_path, "a", encoding="utf-8") as f:
        if story_path.stat().st_size > 0:
            f.write("\n\n")
        f.write(content)

    log.info("Appended %d chars to %s", len(content), story_path)
    return story_path


def estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 characters per token for English text."""
    return len(text) // 4
