"""Tests for config loading and validation."""

from pathlib import Path

import pytest
import yaml


def test_appconfig_defaults():
    from src.config import AppConfig

    config = AppConfig()
    assert config.orchestrator.max_tokens == 8192
    assert config.prose_writer.max_tokens_per_scene == 16384
    assert config.prose_writer.max_continuation_rounds == 3
    assert config.web_search.provider is None
    assert config.web_search.searxng_url == "http://localhost:8888"
    assert config.web_search.max_results == 5


def test_appconfig_from_yaml(tmp_path):
    from src.config import load_config

    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml.dump({
        "models": {"orchestrator": "test-model", "prose_writer": "test-writer"},
        "lore": {"active": "my-project"},
        "web_search": {"provider": "searxng", "searxng_url": "http://10.0.0.1:8888"},
    }))

    config = load_config(config_path=config_file)
    assert config.models.orchestrator == "test-model"
    assert config.lore.active == "my-project"
    assert config.web_search.provider == "searxng"
    assert config.web_search.searxng_url == "http://10.0.0.1:8888"


def test_active_lore_path_with_project():
    from src.config import AppConfig

    config = AppConfig()
    config.lore.active = "my-world"
    assert config.active_lore_path == Path("./build/lore/my-world")


def test_active_lore_path_default():
    from src.config import AppConfig

    config = AppConfig()
    config.lore.active = None
    assert config.active_lore_path == Path("./build/lore")


def test_appconfig_with_null_sections(tmp_path):
    """Config with null sections (e.g. 'lore:' with no sub-keys) should not crash."""
    from src.config import load_config

    config_file = tmp_path / "config.yaml"
    config_file.write_text("models:\n  orchestrator: test\nlore:\nroleplay:\n")

    config = load_config(config_path=config_file)
    assert config.models.orchestrator == "test"
    assert config.lore.active is None
    assert config.roleplay.ai_character is None
