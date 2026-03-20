"""Anthropic LLM client implementation.

Wraps the anthropic SDK to present the unified LLMClient interface.
Handles prompt caching (cache_control) transparently.
"""

from __future__ import annotations

import logging
from typing import Any

import anthropic

from src.llm import LLMClient, LLMResponse, TextBlock, ToolUseBlock, Usage

log = logging.getLogger(__name__)


def _convert_response(response: anthropic.types.Message) -> LLMResponse:
    """Convert an Anthropic SDK Message to our unified LLMResponse."""
    content = []
    for block in response.content:
        if block.type == "text":
            content.append(TextBlock(text=block.text))
        elif block.type == "tool_use":
            content.append(ToolUseBlock(id=block.id, name=block.name, input=block.input))

    return LLMResponse(
        content=content,
        stop_reason=response.stop_reason or "end_turn",
        usage=Usage(
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        ),
    )


def _serialize_content_blocks(content) -> list[dict] | str:
    """Serialize content blocks (our dataclasses or dicts) for the Anthropic SDK.

    The SDK accepts dicts, so we convert our TextBlock/ToolUseBlock dataclasses.
    """
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return content

    result = []
    for block in content:
        if isinstance(block, TextBlock):
            result.append({"type": "text", "text": block.text})
        elif isinstance(block, ToolUseBlock):
            result.append({"type": "tool_use", "id": block.id, "name": block.name, "input": block.input})
        elif isinstance(block, dict):
            result.append(block)
        elif hasattr(block, "type"):
            # Anthropic SDK types — pass through, SDK handles them
            result.append(block)
        else:
            result.append(block)
    return result


def _prepare_messages(messages: list[dict]) -> list[dict]:
    """Ensure message content blocks are serializable for the SDK."""
    result = []
    for msg in messages:
        content = msg.get("content")
        if isinstance(content, list):
            result.append({**msg, "content": _serialize_content_blocks(content)})
        else:
            result.append(msg)
    return result


class AnthropicClient(LLMClient):
    """LLMClient backed by the Anthropic SDK."""

    def __init__(self, client: anthropic.Anthropic | None = None, **kwargs):
        self._client = client or anthropic.Anthropic(**kwargs)

    def create(self, *, model: str, max_tokens: int, system: Any = None,
               messages: list[dict], tools: list[dict] | None = None,
               **kwargs) -> LLMResponse:
        call_kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": _prepare_messages(messages),
        }

        if system is not None:
            call_kwargs["system"] = system
        if tools:
            call_kwargs["tools"] = tools

        response = self._client.messages.create(**call_kwargs)
        return _convert_response(response)

    def create_stream(self, *, model: str, max_tokens: int, system: Any = None,
                      messages: list[dict], tools: list[dict] | None = None,
                      **kwargs):
        call_kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": _prepare_messages(messages),
        }

        if system is not None:
            call_kwargs["system"] = system
        if tools:
            call_kwargs["tools"] = tools

        with self._client.messages.stream(**call_kwargs) as stream:
            for text in stream.text_stream:
                yield {"type": "text_delta", "text": text}
            response = stream.get_final_message()

        yield {"type": "done", "response": _convert_response(response)}
