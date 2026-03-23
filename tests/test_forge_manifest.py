"""Tests for forge manifest normalization and validation."""

import yaml
import pytest
from pathlib import Path


def test_normalize_stage_values(sample_config):
    from src.services.forge import ForgeProject

    fp = ForgeProject("test", sample_config)

    # Test various invalid stage values
    for bad, expected in [
        ("active", "writing"),
        ("completed", "done"),
        ("complete", "done"),
        ("planned", "planning"),
        ("in-progress", "writing"),
        ("draft", "writing"),
        ("nonsense", "planning"),
    ]:
        raw = {"project_name": "test", "stage": bad}
        result = fp._normalize_manifest(raw)
        assert result["stage"] == expected, f"stage '{bad}' should normalize to '{expected}'"


def test_normalize_chapter_keys(sample_config):
    from src.services.forge import ForgeProject

    fp = ForgeProject("test", sample_config)

    for raw_key, expected in [
        ("1", "ch-01"),
        ("2", "ch-02"),
        ("10", "ch-10"),
        ("ch-1", "ch-01"),
        ("ch-01", "ch-01"),
        ("ch-15", "ch-15"),
    ]:
        assert fp._normalize_chapter_key(raw_key) == expected


def test_normalize_chapter_statuses(sample_config):
    from src.services.forge import ForgeProject

    fp = ForgeProject("test", sample_config)

    raw = {
        "project_name": "test",
        "stage": "writing",
        "chapters": {
            "1": {"status": "completed", "word_count": 3000},
            "2": {"status": "in_progress", "word_count": 0},
            "3": {"status": "planned", "word_count": 0},
        },
    }

    result = fp._normalize_manifest(raw)
    chapters = result["chapters"]

    assert "ch-01" in chapters
    assert chapters["ch-01"]["status"] == "done"
    assert chapters["ch-01"]["word_count"] == 3000
    assert chapters["ch-02"]["status"] == "writing"
    assert chapters["ch-03"]["status"] == "pending"


def test_normalize_strips_unknown_fields(sample_config):
    from src.services.forge import ForgeProject

    fp = ForgeProject("test", sample_config)

    raw = {
        "project_name": "test",
        "stage": "planning",
        "automation": {"mode": "full"},
        "description": "some story",
        "characters": {"primary": ["bob"]},
        "target_length": {"total": 100000},
    }

    result = fp._normalize_manifest(raw)
    assert "automation" not in result
    assert "description" not in result
    assert "characters" not in result
    assert "target_length" not in result
    assert result["project_name"] == "test"


def test_normalize_strips_unknown_chapter_fields(sample_config):
    from src.services.forge import ForgeProject

    fp = ForgeProject("test", sample_config)

    raw = {
        "project_name": "test",
        "stage": "writing",
        "chapters": {
            "1": {"status": "done", "word_count": 3000, "outline": "Harold arrives"},
        },
    }

    result = fp._normalize_manifest(raw)
    ch = result["chapters"]["ch-01"]
    assert "outline" not in ch
    assert ch["status"] == "done"
    assert ch["word_count"] == 3000


def test_load_invalid_manifest_rebuilds(sample_config, tmp_path):
    """If manifest is too broken for Pydantic, rebuild from files."""
    from src.services.forge import ForgeProject

    # Set up project structure
    project_dir = sample_config.paths.forge / "test"
    for d in ["plan", "chapters", "output"]:
        (project_dir / d).mkdir(parents=True, exist_ok=True)

    # Write required design files
    (project_dir / "plan" / "outline.md").write_text("# Outline")
    (project_dir / "plan" / "style.md").write_text("# Style")
    (project_dir / "chapters" / "ch-01-brief.md").write_text("# Brief 1")
    (project_dir / "chapters" / "ch-02-brief.md").write_text("# Brief 2")

    # Write a completely broken manifest
    manifest_path = project_dir / "manifest.yaml"
    manifest_path.write_text(yaml.dump({
        "project_name": "test",
        "stage": "banana",
        "chapters": "not_a_dict",
    }))

    fp = ForgeProject("test", sample_config)
    manifest = fp.load()

    # Should have rebuilt from files
    assert manifest.stage == "design"
    assert manifest.chapter_count == 2
    assert "ch-01" in manifest.chapters
    assert "ch-02" in manifest.chapters


def test_load_valid_manifest(sample_config):
    """A properly formatted manifest loads without normalization issues."""
    from src.services.forge import ForgeProject

    project_dir = sample_config.paths.forge / "test"
    for d in ["plan", "chapters", "output"]:
        (project_dir / d).mkdir(parents=True, exist_ok=True)

    manifest_path = project_dir / "manifest.yaml"
    manifest_path.write_text(yaml.dump({
        "project_name": "test",
        "stage": "design",
        "chapter_count": 3,
        "chapters": {
            "ch-01": {"status": "done", "word_count": 5000},
            "ch-02": {"status": "pending"},
            "ch-03": {"status": "pending"},
        },
        "paused": False,
        "pause_after_ch1": True,
        "arc_type": "complete",
        "stats": {
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "agent_calls": 0,
            "chapters_revised": 0,
            "stage_timing": {},
        },
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
    }))

    fp = ForgeProject("test", sample_config)
    manifest = fp.load()

    assert manifest.project_name == "test"
    assert manifest.stage == "design"
    assert manifest.chapter_count == 3
    assert manifest.chapters["ch-01"].status == "done"
    assert manifest.chapters["ch-01"].word_count == 5000
