"""Tests for safe access utilities."""

import pytest


def test_safe_get_list():
    from src.utils.safe import safe_get

    items = [10, 20, 30]
    assert safe_get(items, 0) == 10
    assert safe_get(items, 2) == 30
    assert safe_get(items, 5) is None
    assert safe_get(items, 5, default=-1) == -1
    assert safe_get(items, -1) == 30


def test_safe_get_dict():
    from src.utils.safe import safe_get

    d = {"a": 1, "b": 2}
    assert safe_get(d, "a") == 1
    assert safe_get(d, "missing") is None
    assert safe_get(d, "missing", default=99) == 99


def test_safe_get_none():
    from src.utils.safe import safe_get

    assert safe_get(None, 0) is None
    assert safe_get(None, "key", default="fallback") == "fallback"


def test_safe_attr():
    from src.utils.safe import safe_attr

    class Obj:
        x = 42

    assert safe_attr(Obj(), "x") == 42
    assert safe_attr(Obj(), "missing") is None
    assert safe_attr(Obj(), "missing", default="nope") == "nope"
    assert safe_attr(None, "x") is None


def test_safe_first_text():
    from src.utils.safe import safe_first_text

    class FakeBlock:
        def __init__(self, type, text=""):
            self.type = type
            self.text = text

    # Normal case
    blocks = [FakeBlock("text", "hello")]
    assert safe_first_text(blocks) == "hello"

    # Text block after tool_use
    blocks = [FakeBlock("tool_use"), FakeBlock("text", "found it")]
    assert safe_first_text(blocks) == "found it"

    # No text blocks
    blocks = [FakeBlock("tool_use")]
    assert safe_first_text(blocks) == ""
    assert safe_first_text(blocks, default="nothing") == "nothing"

    # Empty list
    assert safe_first_text([]) == ""

    # None
    assert safe_first_text(None, default="gone") == "gone"

    # Empty text block (should skip to default)
    blocks = [FakeBlock("text", ""), FakeBlock("text", "real")]
    assert safe_first_text(blocks) == "real"
