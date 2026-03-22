"""Web search abstraction — provider-agnostic search interface.

Supports: SearXNG (self-hosted), Tavily, Brave Search, Google Custom Search.
Configure via web_search section in config.yaml.
"""

import json
import logging
from dataclasses import dataclass, field

import requests

from src.config import WebSearchConfig

log = logging.getLogger(__name__)


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str


@dataclass
class SearchResponse:
    query: str
    results: list[SearchResult] = field(default_factory=list)
    error: str | None = None


class WebSearch:
    """Unified web search interface."""

    def __init__(self, config: WebSearchConfig):
        self.config = config
        self.provider = config.provider
        if self.provider:
            log.info("Web search initialized: provider=%s", self.provider)
        else:
            log.info("Web search disabled (no provider configured)")

    @property
    def enabled(self) -> bool:
        return self.provider is not None

    def search(self, query: str, max_results: int | None = None) -> SearchResponse:
        """Run a web search query. Returns SearchResponse with results or error."""
        if not self.enabled:
            return SearchResponse(query=query, error="Web search not configured")

        n = max_results or self.config.max_results

        try:
            if self.provider == "searxng":
                return self._search_searxng(query, n)
            elif self.provider == "tavily":
                return self._search_tavily(query, n)
            elif self.provider == "brave":
                return self._search_brave(query, n)
            elif self.provider == "google":
                return self._search_google(query, n)
            else:
                return SearchResponse(query=query, error=f"Unknown search provider: {self.provider}")
        except Exception as e:
            log.error("Web search failed (%s): %s", self.provider, e)
            return SearchResponse(query=query, error=str(e))

    def _search_searxng(self, query: str, n: int) -> SearchResponse:
        """Search via a SearXNG instance."""
        url = self.config.searxng_url.rstrip("/") + "/search"
        resp = requests.get(url, params={
            "q": query,
            "format": "json",
            "categories": "general",
        }, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        results = []
        for item in data.get("results", [])[:n]:
            results.append(SearchResult(
                title=item.get("title", ""),
                url=item.get("url", ""),
                snippet=item.get("content", ""),
            ))

        return SearchResponse(query=query, results=results)

    def _search_tavily(self, query: str, n: int) -> SearchResponse:
        """Search via Tavily API."""
        api_key = self.config.tavily_api_key
        if not api_key:
            return SearchResponse(query=query, error="Tavily API key not configured")

        resp = requests.post(
            "https://api.tavily.com/search",
            json={
                "api_key": api_key,
                "query": query,
                "max_results": n,
                "include_answer": True,
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        results = []
        for item in data.get("results", [])[:n]:
            results.append(SearchResult(
                title=item.get("title", ""),
                url=item.get("url", ""),
                snippet=item.get("content", ""),
            ))

        return SearchResponse(query=query, results=results)

    def _search_brave(self, query: str, n: int) -> SearchResponse:
        """Search via Brave Search API."""
        api_key = self.config.brave_api_key
        if not api_key:
            return SearchResponse(query=query, error="Brave API key not configured")

        resp = requests.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query, "count": n},
            headers={"X-Subscription-Token": api_key, "Accept": "application/json"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        results = []
        for item in data.get("web", {}).get("results", [])[:n]:
            results.append(SearchResult(
                title=item.get("title", ""),
                url=item.get("url", ""),
                snippet=item.get("description", ""),
            ))

        return SearchResponse(query=query, results=results)

    def _search_google(self, query: str, n: int) -> SearchResponse:
        """Search via Google Custom Search API."""
        api_key = self.config.google_api_key
        cx = self.config.google_cx
        if not api_key or not cx:
            return SearchResponse(query=query, error="Google API key or CX not configured")

        resp = requests.get(
            "https://www.googleapis.com/customsearch/v1",
            params={"key": api_key, "cx": cx, "q": query, "num": min(n, 10)},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        results = []
        for item in data.get("items", [])[:n]:
            results.append(SearchResult(
                title=item.get("title", ""),
                url=item.get("link", ""),
                snippet=item.get("snippet", ""),
            ))

        return SearchResponse(query=query, results=results)


def format_results_for_llm(response: SearchResponse) -> str:
    """Format search results as a string for LLM consumption."""
    if response.error:
        return json.dumps({"error": response.error})

    if not response.results:
        return json.dumps({"query": response.query, "results": [], "note": "No results found"})

    formatted = []
    for r in response.results:
        formatted.append({
            "title": r.title,
            "url": r.url,
            "snippet": r.snippet,
        })

    return json.dumps({"query": response.query, "results": formatted})
