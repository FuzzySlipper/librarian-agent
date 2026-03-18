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
    active: str | None = None  # Subdirectory name, None = use root persona/


class LoreConfig(BaseModel):
    active: str | None = None  # Subdirectory name, None = use root lore/


class WritingStyleConfig(BaseModel):
    active: str = "default"  # Filename (without .md) in paths.writing_styles


class PathsConfig(BaseModel):
    lore: Path = Path("./lore")
    story: Path = Path("./story")
    writing: Path = Path("./writing")
    chats: Path = Path("./chats")
    code_requests: Path = Path("./code-requests")
    persona: Path = Path("./persona")
    writing_styles: Path = Path("./writing-styles")
    portraits: Path = Path("./portraits")
    council: Path = Path("./council")
    layouts: Path = Path("./layouts")
    layout_images: Path = Path("./layout-images")


class AppConfig(BaseModel):
    provider: Literal["anthropic"] = "anthropic"
    models: ModelsConfig = Field(default_factory=ModelsConfig)
    librarian: LibrarianConfig = Field(default_factory=LibrarianConfig)
    prose_writer: ProseWriterConfig = Field(default_factory=ProseWriterConfig)
    persona: PersonaConfig = Field(default_factory=PersonaConfig)
    lore: LoreConfig = Field(default_factory=LoreConfig)
    writing_style: WritingStyleConfig = Field(default_factory=WritingStyleConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)

    @property
    def active_lore_path(self) -> Path:
        """Resolved lore directory based on active lore set."""
        if self.lore.active:
            return self.paths.lore / self.lore.active
        return self.paths.lore

    @property
    def active_persona_path(self) -> Path:
        """Resolved persona directory based on active persona."""
        if self.persona.active:
            return self.paths.persona / self.persona.active
        return self.paths.persona

    @property
    def active_writing_style_path(self) -> Path:
        """Resolved path to the active writing style file."""
        return self.paths.writing_styles / f"{self.writing_style.active}.md"


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
        # Strip None values so Pydantic uses defaults
        raw = {k: v for k, v in raw.items() if v is not None}
        return AppConfig(**raw)

    return AppConfig()


def list_profiles(config: AppConfig) -> dict[str, list[str]]:
    """Discover available persona, lore, and writing style profiles."""
    profiles: dict[str, list[str]] = {"personas": [], "lore_sets": [], "writing_styles": []}

    # Scan persona directory for subdirectories containing .md files
    persona_dir = config.paths.persona
    if persona_dir.exists():
        for sub in sorted(persona_dir.iterdir()):
            if sub.is_dir() and any(sub.glob("*.md")):
                profiles["personas"].append(sub.name)
        if not profiles["personas"] and any(persona_dir.glob("*.md")):
            profiles["personas"].append("(default)")

    # Scan lore directory for subdirectories containing .md files
    lore_dir = config.paths.lore
    if lore_dir.exists():
        for sub in sorted(lore_dir.iterdir()):
            if sub.is_dir() and (any(sub.glob("*.md")) or any(sub.rglob("*.md"))):
                profiles["lore_sets"].append(sub.name)
        if any(lore_dir.glob("*.md")):
            profiles["lore_sets"].insert(0, "(default)")

    # Scan writing styles directory for .md files
    styles_dir = config.paths.writing_styles
    if styles_dir.exists():
        for f in sorted(styles_dir.glob("*.md")):
            profiles["writing_styles"].append(f.stem)

    return profiles
