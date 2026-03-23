"""Configuration loading from config.yaml and environment."""

import os
from pathlib import Path
from typing import Literal

import yaml
from dotenv import load_dotenv
from pydantic import field_validator

import logging

_log = logging.getLogger(__name__)

# Max sane value for any token/count config — prevents int overflow or API rejection
_MAX_SAFE = 1_000_000


def _clamp_tokens(v: int, field_name: str, minimum: int = 1) -> int:
    """Clamp a config integer to a safe range, logging if corrected."""
    if v < minimum:
        _log.warning("Config %s=%d too low, clamping to %d", field_name, v, minimum)
        return minimum
    if v > _MAX_SAFE:
        _log.warning("Config %s=%d too high, clamping to %d", field_name, v, _MAX_SAFE)
        return _MAX_SAFE
    return v
from pydantic import BaseModel, Field


class ModelsConfig(BaseModel):
    librarian: str = "claude-haiku-4-5-20251001"
    prose_writer: str = "claude-sonnet-4-6"
    orchestrator: str = "claude-sonnet-4-6"


class LibrarianConfig(BaseModel):
    max_tokens_per_query: int = 1024
    max_retries: int = 2  # Retry on empty responses

    @field_validator("max_tokens_per_query", "max_retries")
    @classmethod
    def _clamp_librarian(cls, v: int, info) -> int:
        return _clamp_tokens(v, info.field_name)


class ProseWriterConfig(BaseModel):
    max_tokens_per_scene: int = 16384
    max_continuation_rounds: int = 3
    auto_append_to_story: bool = True

    @field_validator("max_tokens_per_scene", "max_continuation_rounds")
    @classmethod
    def _clamp_writer(cls, v: int, info) -> int:
        return _clamp_tokens(v, info.field_name)


class OrchestratorConfig(BaseModel):
    max_tokens: int = 8192
    delegate_max_tokens: int = 2048  # For delegate_technical tool

    @field_validator("max_tokens", "delegate_max_tokens")
    @classmethod
    def _clamp_orchestrator(cls, v: int, info) -> int:
        return _clamp_tokens(v, info.field_name)


class PersonaConfig(BaseModel):
    max_tokens: int = 2000
    active: str | None = None  # Subdirectory name, None = use root persona/


class LoreConfig(BaseModel):
    active: str | None = None  # Subdirectory name, None = use root lore/


class WritingStyleConfig(BaseModel):
    active: str = "default"  # Filename (without .md) in paths.writing_styles


class ForgeConfig(BaseModel):
    max_revisions: int = 3
    review_threshold: float = 7.0
    chapter_max_tokens: int = 8192
    planner_max_tokens: int = 16384
    reviewer_max_tokens: int = 4096
    pause_after_ch1: bool = True
    quality_pass: bool = True
    writer_model: str | None = None    # None = use models.prose_writer
    reviewer_model: str | None = None  # None = use models.librarian (cost-effective)
    planner_model: str | None = None   # None = use models.orchestrator

    @field_validator("max_revisions", "chapter_max_tokens", "planner_max_tokens", "reviewer_max_tokens")
    @classmethod
    def _clamp_forge(cls, v: int, info) -> int:
        return _clamp_tokens(v, info.field_name)

    @field_validator("review_threshold")
    @classmethod
    def _clamp_threshold(cls, v: float) -> float:
        return max(0.0, min(v, 10.0))


class RoleplayConfig(BaseModel):
    ai_character: str | None = None   # Filename (without .yaml) of the AI character card
    user_character: str | None = None  # Filename (without .yaml) of the user character card


class WebSearchConfig(BaseModel):
    provider: str | None = None  # "searxng", "tavily", "brave", "google" — None = disabled
    searxng_url: str = "http://localhost:8888"  # SearXNG instance URL
    tavily_api_key: str | None = None
    brave_api_key: str | None = None
    google_api_key: str | None = None
    google_cx: str | None = None  # Google Custom Search engine ID
    max_results: int = 5


class LayoutPrefsConfig(BaseModel):
    active: str = "default"  # Layout name to load on startup


class PathsConfig(BaseModel):
    lore: Path = Path("./build/lore")
    story: Path = Path("./build/story")
    writing: Path = Path("./build/writing")
    chats: Path = Path("./build/chats")
    code_requests: Path = Path("./docs/code-requests")
    persona: Path = Path("./build/persona")
    writing_styles: Path = Path("./build/writing-styles")
    portraits: Path = Path("./build/portraits")
    council: Path = Path("./build/council")
    layouts: Path = Path("./build/layouts")
    layout_images: Path = Path("./build/layout-images")
    backgrounds: Path = Path("./build/backgrounds")
    character_cards: Path = Path("./build/character-cards")
    forge: Path = Path("./build/forge")
    forge_prompts: Path = Path("./build/forge-prompts")
    data: Path = Path("./build/data")


class AppConfig(BaseModel):
    provider: Literal["anthropic"] = "anthropic"
    user_agent: str = "NarrativeOrchestrator/1.0"
    models: ModelsConfig = Field(default_factory=ModelsConfig)
    orchestrator: OrchestratorConfig = Field(default_factory=OrchestratorConfig)
    librarian: LibrarianConfig = Field(default_factory=LibrarianConfig)
    prose_writer: ProseWriterConfig = Field(default_factory=ProseWriterConfig)
    persona: PersonaConfig = Field(default_factory=PersonaConfig)
    lore: LoreConfig = Field(default_factory=LoreConfig)
    writing_style: WritingStyleConfig = Field(default_factory=WritingStyleConfig)
    layout: LayoutPrefsConfig = Field(default_factory=LayoutPrefsConfig)
    web_search: WebSearchConfig = Field(default_factory=WebSearchConfig)
    roleplay: RoleplayConfig = Field(default_factory=RoleplayConfig)
    forge: ForgeConfig = Field(default_factory=ForgeConfig)
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
    # Load .env — DOTENV_PATH env var > explicit arg > default search
    if env_path and env_path.exists():
        load_dotenv(env_path)
    elif os.environ.get("DOTENV_PATH"):
        load_dotenv(os.environ["DOTENV_PATH"])
    else:
        load_dotenv()  # Searches current dir and parents

    # Load YAML config — CONFIG_PATH env var takes precedence (used in Docker)
    if config_path is None:
        config_path = Path(os.environ.get("CONFIG_PATH", "build/config.yaml"))

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

    # Scan lore directory for project subdirectories.
    # A lore project is a subdirectory that contains its own subdirectories
    # (e.g. characters/, locations/) — not a bare category dir with only .md files.
    lore_dir = config.paths.lore
    if lore_dir.exists():
        for sub in sorted(lore_dir.iterdir()):
            if sub.is_dir():
                has_subdirs = any(s.is_dir() for s in sub.iterdir())
                has_overview = (sub / "world-overview.md").exists()
                if has_subdirs or has_overview:
                    profiles["lore_sets"].append(sub.name)
        if any(lore_dir.glob("*.md")):
            profiles["lore_sets"].insert(0, "(default)")

    # Scan writing styles directory for .md files
    styles_dir = config.paths.writing_styles
    if styles_dir.exists():
        for f in sorted(styles_dir.glob("*.md")):
            profiles["writing_styles"].append(f.stem)

    return profiles
