"""Shared data models for inter-agent communication."""

from typing import Literal

from pydantic import BaseModel


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
