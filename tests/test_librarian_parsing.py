"""Tests for Librarian JSON response parsing."""

import json
import pytest


def _parse(raw_text: str):
    """Helper to call the Librarian's parse method without a full Librarian instance."""
    from src.agents.librarian import Librarian

    # Create a minimal instance just for the parser
    class FakeLibrarian(Librarian):
        def __init__(self):
            # Skip real init
            pass

    lib = FakeLibrarian()
    return lib._parse_response(raw_text)


def test_parse_clean_json():
    raw = json.dumps({
        "relevant_passages": ["Elena is a detective"],
        "source_files": ["characters/elena.md"],
        "confidence": "high",
    })
    result = _parse(raw)
    assert result.confidence == "high"
    assert len(result.relevant_passages) == 1
    assert "Elena" in result.relevant_passages[0]


def test_parse_json_in_code_block():
    raw = '```json\n{"relevant_passages": ["test"], "source_files": [], "confidence": "medium"}\n```'
    result = _parse(raw)
    assert result.confidence == "medium"
    assert result.relevant_passages == ["test"]


def test_parse_json_in_bare_code_block():
    raw = '```\n{"relevant_passages": ["test"], "source_files": [], "confidence": "low"}\n```'
    result = _parse(raw)
    assert result.confidence == "low"


def test_parse_json_with_surrounding_prose():
    raw = (
        "Based on the lore files, here is what I found:\n\n"
        '{"relevant_passages": ["The Pale City is ancient"], "source_files": ["locations/pale-city.md"], "confidence": "high"}\n\n'
        "I hope that helps!"
    )
    result = _parse(raw)
    assert result.confidence == "high"
    assert "Pale City" in result.relevant_passages[0]


def test_parse_completely_invalid_falls_back():
    raw = "I don't know anything about that topic. The lore doesn't contain relevant information."
    result = _parse(raw)
    # Should fall back to wrapping as raw passage
    assert result.confidence == "medium"
    assert len(result.relevant_passages) == 1
    assert "lore doesn't contain" in result.relevant_passages[0]


def test_parse_json_with_nested_arrays():
    raw = json.dumps({
        "relevant_passages": [
            "Elena has dark hair and green eyes",
            "She carries a weathered notebook",
        ],
        "source_files": ["characters/elena.md", "items/notebook.md"],
        "confidence": "high",
    })
    result = _parse(raw)
    assert len(result.relevant_passages) == 2
    assert len(result.source_files) == 2


def test_parse_json_with_extra_whitespace():
    raw = "  \n\n  " + json.dumps({
        "relevant_passages": ["test"],
        "source_files": [],
        "confidence": "high",
    }) + "  \n\n  "
    result = _parse(raw)
    assert result.confidence == "high"
