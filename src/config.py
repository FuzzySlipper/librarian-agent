"""Configuration loading from config.yaml and environment."""

import os
from pathlib import Path
from typing import Literal

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field


class ModelsConfig(BaseModel):
    librarian: str = "claude-haiku-4-5-20251001"
    prose_writer: str = "claude-sonnet-4-6"
    orchestrator: str = "claude-sonnet-4-6"


class LibrarianConfig(BaseModel):
    max_tokens_per_query: int = 1024


class ProseWriterConfig(BaseModel):
    max_tokens_per_scene: int = 4096
    auto_append_to_story: bool = True


class PersonaConfig(BaseModel):
    max_tokens: int = 2000


class PathsConfig(BaseModel):
    lore: Path = Path("./lore")
    story: Path = Path("./story")
    code_requests: Path = Path("./code-requests")


class AppConfig(BaseModel):
    provider: Literal["anthropic"] = "anthropic"
    models: ModelsConfig = Field(default_factory=ModelsConfig)
    librarian: LibrarianConfig = Field(default_factory=LibrarianConfig)
    prose_writer: ProseWriterConfig = Field(default_factory=ProseWriterConfig)
    persona: PersonaConfig = Field(default_factory=PersonaConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)


def load_config(
    config_path: Path | None = None,
    env_path: Path | None = None,
) -> AppConfig:
    """Load config from YAML file and environment variables."""
    # Load .env if provided or look in standard locations
    if env_path and env_path.exists():
        load_dotenv(env_path)
    else:
        load_dotenv()  # Searches current dir and parents

    # Load YAML config — CONFIG_PATH env var takes precedence (used in Docker)
    if config_path is None:
        config_path = Path(os.environ.get("CONFIG_PATH", "config.yaml"))

    if config_path.exists():
        with open(config_path) as f:
            raw = yaml.safe_load(f) or {}
        return AppConfig(**raw)

    return AppConfig()
