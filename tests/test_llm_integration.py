"""Integration tests that require a local LLM (e.g. Ollama).

These tests are skipped by default. Run with:
    pytest tests/test_llm_integration.py --run-llm

Requires a local Ollama instance with a model pulled:
    ollama pull qwen2.5:3b

Configure via environment:
    LLM_TEST_BASE_URL=http://localhost:11434/v1
    LLM_TEST_MODEL=qwen2.5:3b
"""

import json
import os

import pytest

# Skip all tests in this module unless --run-llm is passed
pytestmark = pytest.mark.skipif(
    not os.environ.get("RUN_LLM_TESTS"),
    reason="LLM integration tests require --run-llm flag and a local model",
)

BASE_URL = os.environ.get("LLM_TEST_BASE_URL", "http://localhost:11434/v1")
MODEL = os.environ.get("LLM_TEST_MODEL", "qwen2.5:3b")


def _get_client():
    from src.llm_openai import OpenAIClient
    import openai

    return OpenAIClient(openai.OpenAI(base_url=BASE_URL, api_key="ollama"))


def test_basic_completion():
    """Model can produce a basic text response."""
    client = _get_client()
    response = client.create(
        model=MODEL,
        max_tokens=100,
        system="You are a helpful assistant.",
        messages=[{"role": "user", "content": "Say hello in exactly 5 words."}],
    )

    assert response.content
    assert response.content[0].type == "text"
    assert len(response.content[0].text) > 0
    assert response.stop_reason == "end_turn"


def test_tool_calling():
    """Model can make a tool call."""
    client = _get_client()

    tools = [{
        "name": "get_weather",
        "description": "Get the current weather for a location.",
        "input_schema": {
            "type": "object",
            "properties": {
                "location": {"type": "string", "description": "City name"},
            },
            "required": ["location"],
        },
    }]

    response = client.create(
        model=MODEL,
        max_tokens=200,
        system="You are a helpful assistant. Use the get_weather tool to answer weather questions.",
        messages=[{"role": "user", "content": "What's the weather in Tokyo?"}],
        tools=tools,
    )

    # Model should either make a tool call or respond with text
    assert response.content
    has_tool = any(b.type == "tool_use" for b in response.content)
    has_text = any(b.type == "text" for b in response.content)
    assert has_tool or has_text, "Response should contain tool_use or text"


def test_streaming():
    """Streaming produces text deltas and a final response."""
    client = _get_client()
    chunks = []

    for chunk in client.create_stream(
        model=MODEL,
        max_tokens=100,
        system="You are a helpful assistant.",
        messages=[{"role": "user", "content": "Count from 1 to 5."}],
    ):
        chunks.append(chunk)

    # Should have text_delta chunks and a final done
    text_deltas = [c for c in chunks if c["type"] == "text_delta"]
    done_chunks = [c for c in chunks if c["type"] == "done"]

    assert len(text_deltas) > 0, "Should have text deltas"
    assert len(done_chunks) == 1, "Should have exactly one done event"
    assert done_chunks[0]["response"].content


def test_multi_turn_conversation():
    """Multi-turn conversation maintains context."""
    client = _get_client()

    r1 = client.create(
        model=MODEL,
        max_tokens=100,
        system="You are a helpful assistant.",
        messages=[{"role": "user", "content": "My name is Alice."}],
    )

    r2 = client.create(
        model=MODEL,
        max_tokens=100,
        system="You are a helpful assistant.",
        messages=[
            {"role": "user", "content": "My name is Alice."},
            {"role": "assistant", "content": r1.content[0].text},
            {"role": "user", "content": "What is my name?"},
        ],
    )

    assert "Alice" in r2.content[0].text
