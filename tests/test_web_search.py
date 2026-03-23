"""Tests for web search abstraction."""

import json
import pytest


def test_disabled_search():
    from src.config import WebSearchConfig
    from src.web_search import WebSearch

    ws = WebSearch(WebSearchConfig())
    assert not ws.enabled
    result = ws.search("test query")
    assert result.error is not None
    assert "not configured" in result.error


def test_format_results_for_llm():
    from src.web_search import SearchResponse, SearchResult, format_results_for_llm

    response = SearchResponse(
        query="test",
        results=[
            SearchResult(title="Result 1", url="https://example.com", snippet="A test result"),
            SearchResult(title="Result 2", url="https://example.org", snippet="Another result"),
        ],
    )

    formatted = format_results_for_llm(response)
    data = json.loads(formatted)

    assert data["query"] == "test"
    assert len(data["results"]) == 2
    assert data["results"][0]["title"] == "Result 1"
    assert data["results"][1]["url"] == "https://example.org"


def test_format_error_for_llm():
    from src.web_search import SearchResponse, format_results_for_llm

    response = SearchResponse(query="test", error="Connection failed")
    formatted = format_results_for_llm(response)
    data = json.loads(formatted)

    assert "error" in data
    assert "Connection failed" in data["error"]


def test_format_empty_results():
    from src.web_search import SearchResponse, format_results_for_llm

    response = SearchResponse(query="obscure query", results=[])
    formatted = format_results_for_llm(response)
    data = json.loads(formatted)

    assert data["results"] == []
    assert "No results" in data.get("note", "")
