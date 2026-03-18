"""Artifact service — generates and stores in-world artifacts.

Artifacts are prose outputs formatted as in-world items (newspaper articles,
text messages, social media posts, letters, etc.) that display in a side panel
rather than the main chat stream.

Artifacts are generated through the orchestrator using the same prose writer
and lore context as main content, but with additional formatting instructions.
Output is stored in a separate MD file and never enters conversation history.
"""

import logging
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

# Where artifact files are stored
ARTIFACTS_DIR = Path("artifacts")

# Current active artifact (displayed in panel)
_current_artifact: dict | None = None


def get_current() -> dict | None:
    """Get the current artifact for panel display."""
    return _current_artifact


def set_current(artifact: dict) -> None:
    """Set the current artifact and save to file."""
    global _current_artifact
    _current_artifact = artifact
    _save_artifact(artifact)


def clear_current() -> None:
    """Clear the current artifact from the panel."""
    global _current_artifact
    _current_artifact = None


def list_artifacts() -> list[dict]:
    """List saved artifact files."""
    if not ARTIFACTS_DIR.is_dir():
        return []

    artifacts = []
    for path in sorted(ARTIFACTS_DIR.glob("*.md"), reverse=True):
        try:
            content = path.read_text(encoding="utf-8")
            # Extract format from first line if it's a metadata comment
            fmt = "prose"
            if content.startswith("<!-- format:"):
                fmt = content.split(":", 1)[1].split("-->")[0].strip()
            artifacts.append({
                "name": path.stem,
                "format": fmt,
                "path": str(path),
                "size": len(content),
            })
        except Exception:
            pass

    return artifacts


def _save_artifact(artifact: dict) -> None:
    """Save an artifact to a markdown file."""
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    fmt = artifact.get("format", "prose")
    filename = f"{timestamp}-{fmt}.md"
    path = ARTIFACTS_DIR / filename

    content = f"<!-- format:{fmt} -->\n\n{artifact.get('content', '')}"
    path.write_text(content, encoding="utf-8")
    log.info("Artifact saved: %s", path)


# Format templates — instructions appended to the user's prompt
# when generating artifacts of each type.
FORMAT_INSTRUCTIONS = {
    "newspaper": (
        "Format this as an in-world newspaper article. Include a headline, "
        "byline with a fictional reporter name and publication, date, and "
        "write in journalistic style with an inverted pyramid structure. "
        "Use only information consistent with the world's lore."
    ),
    "letter": (
        "Format this as a handwritten letter or formal correspondence. "
        "Include appropriate salutation, body, and closing. Match the tone "
        "and formality to the characters involved and the world's setting."
    ),
    "texts": (
        "Format this as a series of text/chat messages between characters. "
        "Use a simple format with character names followed by their messages. "
        "Keep messages short and conversational. Include timestamps if appropriate."
    ),
    "social": (
        "Format this as a social media post or feed. Include username/handle, "
        "post content, and engagement metrics (likes, shares, comments). "
        "Adapt the platform style to what fits the world's technology level."
    ),
    "journal": (
        "Format this as a personal journal or diary entry. Write in first person "
        "from the character's perspective. Include the date and capture their "
        "private thoughts, emotions, and observations."
    ),
    "report": (
        "Format this as an official report, briefing, or dossier. Use formal "
        "language, headers, and structured sections. Include classification "
        "level, author, and date as appropriate for the world."
    ),
    "wanted": (
        "Format this as a wanted poster or bounty notice. Include a physical "
        "description, list of crimes/charges, reward amount, and any warnings. "
        "Match the style to the world's setting."
    ),
    "prose": (
        "Generate this as a standalone prose piece. Format it cleanly with "
        "no meta-commentary — just the content itself."
    ),
}


def build_artifact_prompt(user_prompt: str, fmt: str) -> str:
    """Build the full prompt to send to the orchestrator for artifact generation.

    Returns a prompt that instructs the orchestrator to:
    1. Use write_prose to generate the content
    2. Apply format-specific instructions
    3. Return ONLY the artifact content
    """
    format_instructions = FORMAT_INSTRUCTIONS.get(
        fmt, FORMAT_INSTRUCTIONS["prose"]
    )

    return (
        f"Generate an in-world artifact. Use write_prose to create this content, "
        f"querying lore as needed for accuracy.\n\n"
        f"**Format:** {fmt}\n"
        f"**Instructions:** {format_instructions}\n\n"
        f"**User's request:** {user_prompt}\n\n"
        f"IMPORTANT: In your response, include ONLY the artifact content itself. "
        f"No commentary, no 'here is your artifact', no explanation — just the "
        f"formatted artifact text as if it were the real in-world document."
    )
