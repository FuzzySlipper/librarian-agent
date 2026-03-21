"""Character card system for roleplay mode.

Character cards define the AI character being roleplayed and the user's
in-story persona. Each card is a YAML file with structured fields:
name, portrait, personality, description, scenario, greeting.

Cards are stored in build/character-cards/ and the active pair (AI + user)
is set via config or API.

Supports importing SillyTavern / TavernAI character card PNGs (V1/V2/V3),
which embed base64-encoded JSON in a PNG tEXt chunk with keyword "chara".
"""

import base64
import json
import logging
import shutil
import struct
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


# ── PNG character card import (SillyTavern / TavernAI format) ──


def _read_png_text_chunks(data: bytes) -> dict[str, str]:
    """Extract tEXt chunks from a PNG file. Returns {keyword: text}."""
    chunks: dict[str, str] = {}
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        return chunks

    pos = 8
    while pos < len(data):
        if pos + 8 > len(data):
            break
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        chunk_type = data[pos + 4:pos + 8]
        chunk_data = data[pos + 8:pos + 8 + length]
        pos += 12 + length  # 4 length + 4 type + data + 4 crc

        if chunk_type == b"tEXt" and b"\x00" in chunk_data:
            null_idx = chunk_data.index(b"\x00")
            keyword = chunk_data[:null_idx].decode("latin-1")
            text = chunk_data[null_idx + 1:].decode("latin-1")
            chunks[keyword] = text
        elif chunk_type == b"IEND":
            break

    return chunks


def _parse_tavern_json(raw: str) -> dict | None:
    """Decode base64 and parse tavern card JSON."""
    try:
        decoded = base64.b64decode(raw)
        return json.loads(decoded)
    except Exception:
        return None


def import_tavern_card(
    png_path: Path,
    cards_dir: Path,
    portraits_dir: Path,
) -> dict:
    """Import a SillyTavern/TavernAI character card PNG.

    Extracts the embedded JSON metadata, converts to our YAML format,
    and copies the PNG as a portrait.

    Returns the created card data dict.
    Raises ValueError on invalid/missing card data.
    """
    png_data = png_path.read_bytes()
    text_chunks = _read_png_text_chunks(png_data)

    # Try V3 first, then V2/V1
    card_json = None
    for keyword in ("ccv3", "chara"):
        if keyword in text_chunks:
            card_json = _parse_tavern_json(text_chunks[keyword])
            if card_json:
                break

    if not card_json:
        raise ValueError("No character card data found in PNG")

    # V2/V3 have a nested "data" object; V1 has fields at root
    data = card_json.get("data", card_json)

    name = data.get("name", "").strip()
    if not name:
        # Fall back to filename
        name = png_path.stem.replace("_", " ").replace("-", " ").title()

    # Sanitize filename
    safe_name = name.lower().replace(" ", "-")
    safe_name = "".join(c for c in safe_name if c.isalnum() or c in "-_")
    if not safe_name:
        safe_name = "imported"

    # Copy PNG as portrait
    portraits_dir.mkdir(parents=True, exist_ok=True)
    portrait_filename = f"{safe_name}.png"
    portrait_dest = portraits_dir / portrait_filename
    # Avoid overwriting — add suffix if needed
    counter = 1
    while portrait_dest.exists():
        portrait_filename = f"{safe_name}-{counter}.png"
        portrait_dest = portraits_dir / portrait_filename
        counter += 1
    shutil.copy2(png_path, portrait_dest)

    # Build our card format
    card = {
        "name": name,
        "portrait": portrait_filename,
        "personality": data.get("personality", ""),
        "description": data.get("description", ""),
        "scenario": data.get("scenario", ""),
        "greeting": data.get("first_mes", "") or data.get("greeting", ""),
    }

    # Save as YAML
    cards_dir.mkdir(parents=True, exist_ok=True)
    card_path = cards_dir / f"{safe_name}.yaml"
    counter = 1
    while card_path.exists():
        card_path = cards_dir / f"{safe_name}-{counter}.yaml"
        counter += 1
    save_card(card_path, card)

    log.info(
        "Imported tavern card '%s' → %s (portrait: %s)",
        name, card_path.name, portrait_filename,
    )

    return {
        **card,
        "_filename": card_path.stem,
        "_portrait_filename": portrait_filename,
    }
