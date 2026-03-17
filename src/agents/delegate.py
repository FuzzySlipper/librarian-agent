"""Generic multi-agent delegation handler.

Fans out tasks to multiple lightweight agents in parallel, supporting both
Anthropic and OpenAI-compatible endpoints. Designed for simple prompt-in /
text-out tasks (NPC decisions, evaluations, translations) where you want
concurrency and cheap providers — not for complex tool-use loops.

Usage:
    from src.agents.delegate import DelegatePool, Task, Provider

    pool = DelegatePool()
    results = pool.run([
        Task(id="guard", system="You are a suspicious guard.", prompt="A stranger approaches."),
        Task(id="merchant", system="You are a greedy merchant.", prompt="A customer enters."),
    ])
    # results == {"guard": DelegateResult(...), "merchant": DelegateResult(...)}
"""

import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from enum import Enum

log = logging.getLogger(__name__)


class Provider(str, Enum):
    """Supported provider types."""
    ANTHROPIC = "anthropic"
    OPENAI = "openai"  # Also covers OpenAI-compatible (Groq, Together, Ollama, LM Studio, etc.)


# Sensible defaults per provider
_DEFAULTS = {
    Provider.ANTHROPIC: {
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 1024,
    },
    Provider.OPENAI: {
        "model": "gpt-4o-mini",
        "max_tokens": 1024,
    },
}


@dataclass
class Task:
    """A single unit of work to delegate to an agent."""
    id: str
    system: str
    prompt: str
    provider: Provider = Provider.ANTHROPIC
    model: str | None = None       # None = use provider default
    max_tokens: int | None = None   # None = use provider default
    base_url: str | None = None     # For OpenAI-compatible: override endpoint
    api_key: str | None = None      # For OpenAI-compatible: override key
    temperature: float = 0.7
    metadata: dict = field(default_factory=dict)  # Pass-through data (npc_id, etc.)


@dataclass
class DelegateResult:
    """Result from a single delegated task."""
    id: str
    content: str
    model: str
    provider: Provider
    metadata: dict
    error: str | None = None


def _run_anthropic(task: Task) -> DelegateResult:
    """Execute a task via the Anthropic API."""
    import anthropic

    model = task.model or _DEFAULTS[Provider.ANTHROPIC]["model"]
    max_tokens = task.max_tokens or _DEFAULTS[Provider.ANTHROPIC]["max_tokens"]

    try:
        client = anthropic.Anthropic(api_key=task.api_key) if task.api_key else anthropic.Anthropic()
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=task.temperature,
            system=task.system,
            messages=[{"role": "user", "content": task.prompt}],
        )
        text = "".join(b.text for b in response.content if b.type == "text")
        return DelegateResult(
            id=task.id, content=text, model=model,
            provider=Provider.ANTHROPIC, metadata=task.metadata,
        )
    except Exception as e:
        log.error("Delegate task %s failed (anthropic): %s", task.id, e)
        return DelegateResult(
            id=task.id, content="", model=model,
            provider=Provider.ANTHROPIC, metadata=task.metadata,
            error=str(e),
        )


def _run_openai(task: Task) -> DelegateResult:
    """Execute a task via an OpenAI-compatible API."""
    from openai import OpenAI

    model = task.model or _DEFAULTS[Provider.OPENAI]["model"]
    max_tokens = task.max_tokens or _DEFAULTS[Provider.OPENAI]["max_tokens"]

    try:
        client_kwargs: dict = {}
        if task.base_url:
            client_kwargs["base_url"] = task.base_url
        if task.api_key:
            client_kwargs["api_key"] = task.api_key
        elif task.base_url:
            # Local providers (Ollama, LM Studio) often don't need a key
            client_kwargs["api_key"] = os.environ.get("OPENAI_API_KEY", "not-needed")

        client = OpenAI(**client_kwargs)
        response = client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            temperature=task.temperature,
            messages=[
                {"role": "system", "content": task.system},
                {"role": "user", "content": task.prompt},
            ],
        )
        text = response.choices[0].message.content or ""
        return DelegateResult(
            id=task.id, content=text, model=model,
            provider=Provider.OPENAI, metadata=task.metadata,
        )
    except Exception as e:
        log.error("Delegate task %s failed (openai): %s", task.id, e)
        return DelegateResult(
            id=task.id, content="", model=model,
            provider=Provider.OPENAI, metadata=task.metadata,
            error=str(e),
        )


_RUNNERS = {
    Provider.ANTHROPIC: _run_anthropic,
    Provider.OPENAI: _run_openai,
}


class DelegatePool:
    """Runs multiple agent tasks in parallel and collects results.

    Args:
        max_workers: Max concurrent API calls. Keep this reasonable to avoid
                     rate limits — 5-10 is usually fine.
    """

    def __init__(self, max_workers: int = 8):
        self.max_workers = max_workers

    def run(self, tasks: list[Task]) -> dict[str, DelegateResult]:
        """Execute all tasks in parallel, return results keyed by task ID."""
        if not tasks:
            return {}

        results: dict[str, DelegateResult] = {}

        # Single task — skip the thread pool overhead
        if len(tasks) == 1:
            task = tasks[0]
            runner = _RUNNERS[task.provider]
            result = runner(task)
            return {result.id: result}

        with ThreadPoolExecutor(max_workers=min(self.max_workers, len(tasks))) as pool:
            futures = {
                pool.submit(_RUNNERS[task.provider], task): task.id
                for task in tasks
            }
            for future in as_completed(futures):
                task_id = futures[future]
                try:
                    result = future.result()
                    results[result.id] = result
                except Exception as e:
                    log.error("Delegate task %s raised: %s", task_id, e)
                    results[task_id] = DelegateResult(
                        id=task_id, content="", model="unknown",
                        provider=Provider.ANTHROPIC, metadata={},
                        error=str(e),
                    )

        return results

    def run_single(self, task: Task) -> DelegateResult:
        """Convenience: run one task synchronously."""
        runner = _RUNNERS[task.provider]
        return runner(task)
