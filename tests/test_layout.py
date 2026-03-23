"""Tests for layout-related config."""

import pytest


def test_layout_prefs_defaults():
    from src.config import LayoutPrefsConfig

    prefs = LayoutPrefsConfig()
    assert prefs.active == "default"


def test_layout_prefs_custom():
    from src.config import LayoutPrefsConfig

    prefs = LayoutPrefsConfig(active="cinematic")
    assert prefs.active == "cinematic"
