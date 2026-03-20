"""OpenAI-compatible LLM client implementation.

Wraps any OpenAI-compatible API (OpenAI, DeepSeek, local LLMs, etc.) to present
the unified LLMClient interface. Translates tool definitions, messages, and
responses between the internal Anthropic-style format and OpenAI's format.

Handles provider quirks (DeepSeek reasoning_content, empty required arrays, etc.)
via ProviderOptions.
"""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING, Any

import openai

from src.llm import LLMClient, LLMResponse, TextBlock, ToolUseBlock, Usage

if TYPE_CHECKING:
    from src.providers import ProviderOptions

log = logging.getLogger(__name__)


# ── Translation helpers ──────────────────────────────────────────────

def _anthropic_tools_to_openai(tools: list[dict] | None,
                                strip_empty_required: bool = False) -> list[dict] | None:
    """Convert Anthropic tool format to OpenAI function-calling format."""
    if not tools:
        return None
    result = []
    for tool in tools:
        params = dict(tool.get("input_schema", {"type": "object", "properties": {}}))
        # DeepSeek quirk: rejects empty required arrays
        if strip_empty_required:
            req = params.get("required")
            if isinstance(req, list) and len(req) == 0:
                params = {k: v for k, v in params.items() if k != "required"}
        result.append({
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": params,
            },
        })
    return result


def _system_to_string(system) -> str:
    """Normalize Anthropic system prompt (string or list of blocks) to a string."""
    if isinstance(system, str):
        return system
    if isinstance(system, list):
        parts = []
        for block in system:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block["text"])
            elif isinstance(block, str):
                parts.append(block)
        return "\n\n".join(parts)
    return str(system) if system else ""


def _convert_messages(messages: list[dict], system_text: str,
                      add_reasoning_content: bool = False) -> list[dict]:
    """Convert Anthropic-style messages to OpenAI format.

    Key differences:
    - System prompt becomes a system message at position 0
    - Anthropic tool_result blocks in user messages -> separate tool role messages
    - Anthropic assistant content (list of blocks) -> OpenAI assistant message + tool_calls

    If add_reasoning_content is True, adds empty reasoning_content field to
    assistant messages with tool_calls (required by DeepSeek reasoner models).
    """
    result = []

    if system_text:
        result.append({"role": "system", "content": system_text})

    for msg in messages:
        role = msg["role"]
        content = msg["content"]

        if role == "user":
            if isinstance(content, str):
                result.append({"role": "user", "content": content})
            elif isinstance(content, list):
                if content and isinstance(content[0], dict) and content[0].get("type") == "tool_result":
                    for block in content:
                        result.append({
                            "role": "tool",
                            "tool_call_id": block["tool_use_id"],
                            "content": block.get("content", ""),
                        })
                else:
                    text_parts = []
                    for block in content:
                        if isinstance(block, dict):
                            if block.get("type") == "text":
                                text_parts.append(block.get("text", ""))
                            elif "text" in block:
                                text_parts.append(block["text"])
                        elif isinstance(block, str):
                            text_parts.append(block)
                    result.append({"role": "user", "content": "\n".join(text_parts)})

        elif role == "assistant":
            if isinstance(content, str):
                result.append({"role": "assistant", "content": content})
            elif isinstance(content, list):
                text_parts = []
                tool_calls = []
                for block in content:
                    if hasattr(block, "type"):
                        btype = block.type
                    elif isinstance(block, dict):
                        btype = block.get("type", "")
                    else:
                        continue

                    if btype == "text":
                        text_parts.append(block.text if hasattr(block, "text") else block.get("text", ""))
                    elif btype == "tool_use":
                        name = block.name if hasattr(block, "name") else block.get("name", "")
                        bid = block.id if hasattr(block, "id") else block.get("id", "")
                        binput = block.input if hasattr(block, "input") else block.get("input", {})
                        tool_calls.append({
                            "id": bid,
                            "type": "function",
                            "function": {
                                "name": name,
                                "arguments": json.dumps(binput),
                            },
                        })

                msg_dict: dict = {"role": "assistant"}
                if text_parts:
                    msg_dict["content"] = "\n".join(text_parts)
                else:
                    msg_dict["content"] = None
                if tool_calls:
                    msg_dict["tool_calls"] = tool_calls
                    stored_reasoning = msg.get("reasoning")
                    if stored_reasoning is not None:
                        msg_dict["reasoning_content"] = stored_reasoning
                    elif add_reasoning_content:
                        msg_dict["reasoning_content"] = ""
                result.append(msg_dict)
        else:
            result.append(msg)

    return result


def _convert_response(response) -> LLMResponse:
    """Convert an OpenAI ChatCompletion response to our unified LLMResponse."""
    choice = response.choices[0]
    message = choice.message
    content = []

    if message.content:
        content.append(TextBlock(text=message.content))

    if message.tool_calls:
        for tc in message.tool_calls:
            try:
                args = json.loads(tc.function.arguments)
            except (json.JSONDecodeError, TypeError):
                args = {}
            content.append(ToolUseBlock(
                id=tc.id,
                name=tc.function.name,
                input=args,
            ))

    finish_reason = choice.finish_reason
    if finish_reason == "tool_calls":
        stop_reason = "tool_use"
    elif finish_reason == "stop":
        stop_reason = "end_turn"
    elif finish_reason == "length":
        stop_reason = "max_tokens"
    else:
        stop_reason = finish_reason or "end_turn"

    usage = Usage(
        input_tokens=getattr(response.usage, "prompt_tokens", 0) if response.usage else 0,
        output_tokens=getattr(response.usage, "completion_tokens", 0) if response.usage else 0,
    )

    reasoning = getattr(message, "reasoning_content", None)

    return LLMResponse(content=content, stop_reason=stop_reason, usage=usage, reasoning=reasoning)


def _stream_response(stream):
    """Consume an OpenAI streaming response as a generator.

    Yields dicts:
      {"type": "text_delta", "text": "..."} — partial text
      {"type": "reasoning_delta", "text": "..."} — partial reasoning
      {"type": "done", "response": LLMResponse} — final assembled response
    """
    text_parts = []
    reasoning_parts = []
    tool_calls_data: dict[int, dict] = {}
    finish_reason = None
    usage_prompt = 0
    usage_completion = 0

    for chunk in stream:
        if not chunk.choices:
            if chunk.usage:
                usage_prompt = getattr(chunk.usage, "prompt_tokens", 0)
                usage_completion = getattr(chunk.usage, "completion_tokens", 0)
            continue

        delta = chunk.choices[0].delta
        finish_reason = chunk.choices[0].finish_reason or finish_reason

        if delta.content:
            text_parts.append(delta.content)
            yield {"type": "text_delta", "text": delta.content}

        reasoning_content = getattr(delta, "reasoning_content", None)
        if reasoning_content:
            reasoning_parts.append(reasoning_content)
            yield {"type": "reasoning_delta", "text": reasoning_content}

        if delta.tool_calls:
            for tc_delta in delta.tool_calls:
                idx = tc_delta.index
                if idx not in tool_calls_data:
                    tool_calls_data[idx] = {"id": "", "name": "", "arguments": ""}
                if tc_delta.id:
                    tool_calls_data[idx]["id"] = tc_delta.id
                if tc_delta.function:
                    if tc_delta.function.name:
                        tool_calls_data[idx]["name"] = tc_delta.function.name
                    if tc_delta.function.arguments:
                        tool_calls_data[idx]["arguments"] += tc_delta.function.arguments

        if chunk.usage:
            usage_prompt = getattr(chunk.usage, "prompt_tokens", 0)
            usage_completion = getattr(chunk.usage, "completion_tokens", 0)

    # Assemble final response
    content = []
    full_text = "".join(text_parts)
    if full_text:
        content.append(TextBlock(text=full_text))

    for _idx in sorted(tool_calls_data.keys()):
        tc = tool_calls_data[_idx]
        try:
            args = json.loads(tc["arguments"])
        except (json.JSONDecodeError, TypeError):
            args = {}
        content.append(ToolUseBlock(id=tc["id"], name=tc["name"], input=args))

    if finish_reason == "tool_calls":
        stop_reason = "tool_use"
    elif finish_reason == "stop":
        stop_reason = "end_turn"
    elif finish_reason == "length":
        stop_reason = "max_tokens"
    else:
        stop_reason = finish_reason or "end_turn"

    reasoning = "".join(reasoning_parts) if reasoning_parts else None

    response = LLMResponse(
        content=content,
        stop_reason=stop_reason,
        usage=Usage(input_tokens=usage_prompt, output_tokens=usage_completion),
        reasoning=reasoning,
    )
    yield {"type": "done", "response": response}


# ── Quirk detection ──────────────────────────────────────────────────

_DEEPSEEK_REASONER_RE = re.compile(r"-reasoner\b", re.IGNORECASE)


def _should_add_reasoning_content(option_value: bool | str, model: str) -> bool:
    if option_value is True:
        return True
    if option_value is False:
        return False
    return bool(_DEEPSEEK_REASONER_RE.search(model))


def _should_strip_empty_required(option_value: bool | str, model: str) -> bool:
    if option_value is True:
        return True
    if option_value is False:
        return False
    return "deepseek" in model.lower()


# ── Client class ─────────────────────────────────────────────────────

class OpenAIClient(LLMClient):
    """LLMClient backed by any OpenAI-compatible API."""

    def __init__(self, client: openai.OpenAI | None = None,
                 options: ProviderOptions | None = None, **kwargs):
        self._client = client or openai.OpenAI(**kwargs)
        self._options = options

    def _build_call_kwargs(self, *, model: str, max_tokens: int, system,
                           messages: list[dict], tools: list[dict] | None,
                           stream: bool = False) -> dict[str, Any]:
        """Build the kwargs dict for chat.completions.create."""
        opts = self._options

        add_reasoning = _should_add_reasoning_content(
            opts.reasoning_content if opts else "auto", model)
        strip_required = _should_strip_empty_required(
            opts.strip_empty_required if opts else "auto", model)

        system_text = _system_to_string(system)
        oai_messages = _convert_messages(messages, system_text,
                                         add_reasoning_content=add_reasoning)
        oai_tools = _anthropic_tools_to_openai(tools, strip_empty_required=strip_required)

        call_kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": oai_messages,
        }
        if stream:
            call_kwargs["stream"] = True
        if oai_tools:
            call_kwargs["tools"] = oai_tools

        if opts:
            if opts.temperature is not None:
                call_kwargs["temperature"] = opts.temperature
            if opts.top_p is not None:
                call_kwargs["top_p"] = opts.top_p
            if opts.frequency_penalty is not None:
                call_kwargs["frequency_penalty"] = opts.frequency_penalty
            if opts.presence_penalty is not None:
                call_kwargs["presence_penalty"] = opts.presence_penalty
            if opts.seed is not None:
                call_kwargs["seed"] = opts.seed
            if opts.extra_body:
                call_kwargs["extra_body"] = opts.extra_body

        return call_kwargs

    def create(self, *, model: str, max_tokens: int, system: Any = None,
               messages: list[dict], tools: list[dict] | None = None,
               **kwargs) -> LLMResponse:
        call_kwargs = self._build_call_kwargs(
            model=model, max_tokens=max_tokens, system=system,
            messages=messages, tools=tools)
        response = self._client.chat.completions.create(**call_kwargs)
        return _convert_response(response)

    def create_stream(self, *, model: str, max_tokens: int, system: Any = None,
                      messages: list[dict], tools: list[dict] | None = None,
                      **kwargs):
        call_kwargs = self._build_call_kwargs(
            model=model, max_tokens=max_tokens, system=system,
            messages=messages, tools=tools, stream=True)
        stream = self._client.chat.completions.create(**call_kwargs)
        yield from _stream_response(stream)
