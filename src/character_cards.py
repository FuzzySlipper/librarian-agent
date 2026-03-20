"""Character card system for roleplay mode.

Character cards define the AI character being roleplayed and the user's
in-story persona. Each card is a YAML file with structured fields:
name, portrait, personality, description, scenario, greeting.

Cards are stored in build/character-cards/ and the active pair (AI + user)
is set via config or API.
"""

import logging
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

# Standard fields in a character card
CARD_FIELDS = ["name", "portrait", "personality", "description", "scenario", "greeting"]


def load_card(path: Path) -> dict | None:
    """Load a character card from a YAML file."""
    if not path.exists():
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        data["_filename"] = path.stem
        return data
    except Exception as e:
        log.warning("Failed to load character card %s: %s", path, e)
        return None


def save_card(path: Path, data: dict) -> None:
    """Save a character card to a YAML file."""
    # Strip internal fields before saving
    clean = {k: v for k, v in data.items() if not k.startswith("_")}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump(clean, default_flow_style=False, allow_unicode=True, sort_keys=False), encoding="utf-8")


def list_cards(cards_dir: Path) -> list[dict]:
    """List all character cards in the directory."""
    if not cards_dir.is_dir():
        return []
    cards = []
    for p in sorted(cards_dir.glob("*.yaml")):
        card = load_card(p)
        if card:
            cards.append({
                "filename": p.stem,
                "name": card.get("name", p.stem),
                "portrait": card.get("portrait"),
            })
    return cards


def card_to_prompt(card: dict) -> str:
    """Convert a character card to text suitable for injection into a system prompt."""
    parts = []
    if card.get("name"):
        parts.append(f"**Name:** {card['name']}")
    if card.get("description"):
        parts.append(f"**Description:** {card['description']}")
    if card.get("personality"):
        parts.append(f"**Personality:** {card['personality']}")
    if card.get("scenario"):
        parts.append(f"**Scenario:** {card['scenario']}")
    return "\n".join(parts)


def new_card_template(name: str = "New Character") -> dict:
    """Return a blank character card template."""
    return {
        "name": name,
        "portrait": "",
        "personality": "",
        "description": "",
        "scenario": "",
        "greeting": "",
    }
