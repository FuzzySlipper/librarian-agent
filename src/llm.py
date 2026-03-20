"""Unified LLM client interface.

All LLM communication goes through LLMClient, regardless of whether the
backend is Anthropic, OpenAI, or any OpenAI-compatible provider. Agents
receive an LLMClient and never need to know which provider they're using.

Response types (TextBlock, ToolUseBlock, etc.) are shared across providers.
Messages use Anthropic-style format as the internal wire format:
  {"role": "user", "content": "text"}
  {"role": "assistant", "content": [TextBlock(...), ToolUseBlock(...)]}
  {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "...", "content": "..."}]}
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Generator


@dataclass
class TextBlock:
    type: str = "text"
    text: str = ""


@dataclass
class ToolUseBlock:
    type: str = "tool_use"
    id: str = ""
    name: str = ""
    input: dict = field(default_factory=dict)


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class LLMResponse:
    """Unified response from any LLM provider."""
    content: list = field(default_factory=list)
    stop_reason: str = "end_turn"
    usage: Usage = field(default_factory=Usage)
    reasoning: str | None = None


# Stream event type
StreamEvent = dict[str, Any]
# {"type": "text_delta", "text": "..."}
# {"type": "reasoning_delta", "text": "..."}
# {"type": "done", "response": LLMResponse}


class LLMClient:
    """Base class for LLM provider clients.

    Subclasses implement create() and create_stream() for their provider.
    All agents program against this interface.
    """

    def create(self, *, model: str, max_tokens: int, system: Any = None,
               messages: list[dict], tools: list[dict] | None = None,
               **kwargs) -> LLMResponse:
        """Send a message and get a complete response."""
        raise NotImplementedError

    def create_stream(self, *, model: str, max_tokens: int, system: Any = None,
                      messages: list[dict], tools: list[dict] | None = None,
                      **kwargs) -> Generator[StreamEvent, None, None]:
        """Send a message and stream the response.

        Yields dicts:
          {"type": "text_delta", "text": "..."}      — partial text
          {"type": "reasoning_delta", "text": "..."}  — partial reasoning
          {"type": "done", "response": LLMResponse}   — final assembled response
        """
        raise NotImplementedError
