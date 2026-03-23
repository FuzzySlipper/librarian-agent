"""Shared test fixtures."""

import os
import sys
from pathlib import Path

import pytest


def pytest_addoption(parser):
    parser.addoption("--run-llm", action="store_true", default=False, help="Run LLM integration tests")


def pytest_configure(config):
    if config.getoption("--run-llm"):
        os.environ["RUN_LLM_TESTS"] = "1"

# Ensure the project root is on sys.path so `from src...` imports work
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Set a dummy config path so imports don't fail
os.environ.setdefault("CONFIG_PATH", str(PROJECT_ROOT / "build" / "config.yaml"))


@pytest.fixture
def tmp_project(tmp_path):
    """Create a temporary forge project directory structure."""
    plan = tmp_path / "plan"
    chapters = tmp_path / "chapters"
    output = tmp_path / "output"
    for d in (plan, chapters, output):
        d.mkdir()
    return tmp_path


@pytest.fixture
def sample_config(tmp_path):
    """Create a minimal AppConfig pointing at temp directories."""
    from src.config import AppConfig

    config = AppConfig()
    config.paths.lore = tmp_path / "lore"
    config.paths.story = tmp_path / "story"
    config.paths.writing = tmp_path / "writing"
    config.paths.chats = tmp_path / "chats"
    config.paths.forge = tmp_path / "forge"
    config.paths.forge_prompts = tmp_path / "forge-prompts"
    config.paths.portraits = tmp_path / "portraits"
    config.paths.character_cards = tmp_path / "character-cards"
    config.paths.data = tmp_path / "data"

    for p in [config.paths.lore, config.paths.story, config.paths.forge]:
        p.mkdir(parents=True, exist_ok=True)

    return config
