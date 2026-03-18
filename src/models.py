"""Shared data models for inter-agent communication."""

from typing import Literal

from pydantic import BaseModel, Field


class LoreBundle(BaseModel):
    """Output from Librarian — structured lore with provenance."""
    relevant_passages: list[str]
    source_files: list[str]
    confidence: Literal["high", "medium", "low"] = "high"


class ProseRequest(BaseModel):
    """Input to Prose Writer."""
    scene_description: str
    story_context: str
    tone_notes: str | None = None


class ProseResult(BaseModel):
    """Output from Prose Writer."""
    generated_text: str
    lore_queries_made: list[str]
    word_count: int


class Response(BaseModel):
    """Output from Orchestrator to user."""
    content: str
    response_type: Literal["prose", "lore_answer", "discussion", "confirmation"]
    suggested_next: list[str] | None = None


# ── StoryForge models ────────────────────────────────────────────────


class ReviewResult(BaseModel):
    """Structured review scores from a forge reviewer agent."""
    continuity: float
    brief_adherence: float
    voice_consistency: float
    quality: float
    overall: float
    feedback: str
    passed: bool


class ChapterStatus(BaseModel):
    """Tracks the state of a single chapter in the forge pipeline."""
    status: Literal["pending", "writing", "review", "revision", "done", "flagged"] = "pending"
    revision_count: int = 0
    word_count: int = 0
    scores: dict[str, float] | None = None
    feedback: list[str] = Field(default_factory=list)


class ForgeStats(BaseModel):
    """Diagnostics collected during a forge pipeline run."""
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    agent_calls: int = 0
    chapters_revised: int = 0
    stage_timing: dict[str, dict[str, str]] = Field(default_factory=dict)  # stage -> {start, end}


class ForgeManifest(BaseModel):
    """Source of truth for a forge project's pipeline state."""
    project_name: str
    stage: Literal["planning", "design", "writing", "quality", "assembly", "done"] = "planning"
    chapter_count: int = 0
    chapters: dict[str, ChapterStatus] = Field(default_factory=dict)
    paused: bool = False
    pause_after_ch1: bool = True
    arc_type: str = "complete"  # complete | episodic
    stats: ForgeStats = Field(default_factory=ForgeStats)
    created_at: str = ""
    updated_at: str = ""
