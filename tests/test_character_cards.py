"""Tests for character card system including ST import."""

import base64
import json
import struct
from pathlib import Path

import pytest
import yaml


def test_new_card_template():
    from src.character_cards import new_card_template

    card = new_card_template("Test Character")
    assert card["name"] == "Test Character"
    assert card["portrait"] == ""
    assert card["personality"] == ""
    assert card["greeting"] == ""


def test_save_and_load_card(tmp_path):
    from src.character_cards import save_card, load_card

    card = {
        "name": "Elena",
        "portrait": "elena.png",
        "personality": "Brave and curious",
        "description": "Tall with dark hair",
        "scenario": "A fantasy world",
        "greeting": "Hello, traveler!",
    }

    path = tmp_path / "elena.yaml"
    save_card(path, card)
    assert path.exists()

    loaded = load_card(path)
    assert loaded["name"] == "Elena"
    assert loaded["personality"] == "Brave and curious"
    assert loaded["greeting"] == "Hello, traveler!"
    assert loaded["_filename"] == "elena"


def test_list_cards(tmp_path):
    from src.character_cards import save_card, list_cards

    save_card(tmp_path / "alice.yaml", {"name": "Alice", "portrait": "alice.png"})
    save_card(tmp_path / "bob.yaml", {"name": "Bob", "portrait": ""})

    cards = list_cards(tmp_path)
    assert len(cards) == 2
    names = {c["name"] for c in cards}
    assert names == {"Alice", "Bob"}


def test_list_cards_empty_dir(tmp_path):
    from src.character_cards import list_cards

    cards = list_cards(tmp_path)
    assert cards == []


def test_list_cards_nonexistent_dir(tmp_path):
    from src.character_cards import list_cards

    cards = list_cards(tmp_path / "nonexistent")
    assert cards == []


def test_card_to_prompt():
    from src.character_cards import card_to_prompt

    card = {
        "name": "Elena",
        "personality": "Brave and curious",
        "description": "Tall with dark hair",
        "scenario": "A fantasy world",
    }

    prompt = card_to_prompt(card)
    assert "**Name:** Elena" in prompt
    assert "**Personality:** Brave and curious" in prompt
    assert "**Description:** Tall with dark hair" in prompt
    assert "**Scenario:** A fantasy world" in prompt


def _make_png_with_chara(chara_data: dict) -> bytes:
    """Create a minimal PNG with a tEXt chunk containing character card data."""
    # PNG signature
    sig = b"\x89PNG\r\n\x1a\n"

    # Minimal IHDR chunk (1x1 pixel, 8-bit RGB)
    ihdr_data = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    ihdr = _make_chunk(b"IHDR", ihdr_data)

    # tEXt chunk with chara data
    json_str = json.dumps(chara_data)
    b64 = base64.b64encode(json_str.encode()).decode("latin-1")
    text_data = b"chara\x00" + b64.encode("latin-1")
    text_chunk = _make_chunk(b"tEXt", text_data)

    # Minimal IDAT (empty compressed data)
    import zlib
    raw_row = b"\x00\x00\x00\x00"  # filter byte + 1 pixel RGB
    idat_data = zlib.compress(raw_row)
    idat = _make_chunk(b"IDAT", idat_data)

    # IEND
    iend = _make_chunk(b"IEND", b"")

    return sig + ihdr + text_chunk + idat + iend


def _make_chunk(chunk_type: bytes, data: bytes) -> bytes:
    """Build a PNG chunk: length + type + data + CRC."""
    import zlib
    length = struct.pack(">I", len(data))
    crc = struct.pack(">I", zlib.crc32(chunk_type + data) & 0xFFFFFFFF)
    return length + chunk_type + data + crc


def test_read_png_text_chunks():
    from src.character_cards import _read_png_text_chunks

    card_data = {
        "spec": "chara_card_v2",
        "spec_version": "2.0",
        "data": {
            "name": "Test Character",
            "description": "A test",
            "personality": "Nice",
            "scenario": "Testing",
            "first_mes": "Hello!",
            "mes_example": "",
        },
    }

    png_bytes = _make_png_with_chara(card_data)
    chunks = _read_png_text_chunks(png_bytes)

    assert "chara" in chunks


def test_import_tavern_card(tmp_path):
    from src.character_cards import import_tavern_card

    cards_dir = tmp_path / "cards"
    portraits_dir = tmp_path / "portraits"

    card_data = {
        "spec": "chara_card_v2",
        "spec_version": "2.0",
        "data": {
            "name": "Seraphina",
            "description": "A healing mage with golden hair",
            "personality": "Caring and protective",
            "scenario": "A magical academy",
            "first_mes": "Welcome, I've been expecting you.",
            "mes_example": "",
            "creator_notes": "",
            "system_prompt": "",
            "post_history_instructions": "",
            "creator": "test",
            "character_version": "1.0",
            "tags": [],
            "alternate_greetings": [],
            "extensions": {},
        },
    }

    png_path = tmp_path / "seraphina.png"
    png_path.write_bytes(_make_png_with_chara(card_data))

    result = import_tavern_card(png_path, cards_dir, portraits_dir)

    assert result["name"] == "Seraphina"
    assert result["personality"] == "Caring and protective"
    assert result["greeting"] == "Welcome, I've been expecting you."
    assert result["description"] == "A healing mage with golden hair"

    # Check files were created
    assert (portraits_dir / result["portrait"]).exists()
    yaml_files = list(cards_dir.glob("*.yaml"))
    assert len(yaml_files) == 1

    # Verify the YAML content
    loaded = yaml.safe_load(yaml_files[0].read_text())
    assert loaded["name"] == "Seraphina"


def test_import_v1_card(tmp_path):
    """V1 cards have fields at root level, no data wrapper."""
    from src.character_cards import import_tavern_card

    cards_dir = tmp_path / "cards"
    portraits_dir = tmp_path / "portraits"

    card_data = {
        "name": "Old Format",
        "description": "A v1 character",
        "personality": "Grumpy",
        "scenario": "A tavern",
        "first_mes": "What do you want?",
        "mes_example": "",
    }

    png_path = tmp_path / "old.png"
    png_path.write_bytes(_make_png_with_chara(card_data))

    result = import_tavern_card(png_path, cards_dir, portraits_dir)
    assert result["name"] == "Old Format"
    assert result["greeting"] == "What do you want?"
