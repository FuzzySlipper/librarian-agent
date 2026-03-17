"""Council service — fans out a query to multiple AI perspectives and collates results.

Council members are defined by MD files in the council/ directory. Each file has
a header block with model/provider config, followed by the system prompt.

File format:
    model: claude-haiku-4-5-20251001
    provider: anthropic
    base_url: http://localhost:11434/v1  (optional, for openai-compatible)

    You are a critical analyst. Examine the query thoroughly...
"""

import logging
from pathlib import Path

from src.agents.delegate import DelegatePool, Task, Provider, DelegateResult

log = logging.getLogger(__name__)


def _parse_council_file(path: Path) -> dict:
    """Parse a council member MD file into config + system prompt."""
    text = path.read_text(encoding="utf-8").strip()
    lines = text.split("\n")

    config: dict = {"name": path.stem}
    prompt_start = 0

    # Parse key: value header lines until we hit a blank line or non-header
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            prompt_start = i + 1
            break
        if ":" in stripped and not stripped.startswith("You") and not stripped.startswith("#"):
            key, _, value = stripped.partition(":")
            config[key.strip().lower()] = value.strip()
        else:
            prompt_start = i
            break

    config["system"] = "\n".join(lines[prompt_start:]).strip()
    return config


def load_council_members(council_dir: Path) -> list[dict]:
    """Load all council member configs from the council directory."""
    if not council_dir.is_dir():
        return []

    members = []
    for path in sorted(council_dir.glob("*.md")):
        try:
            members.append(_parse_council_file(path))
        except Exception as e:
            log.warning("Failed to parse council member %s: %s", path.name, e)

    return members


def run_council(query: str, council_dir: Path, max_workers: int = 8) -> dict:
    """Run a query through all council members in parallel.

    Returns a dict with:
        - members: list of {name, model, provider, content, error}
        - query: the original query
    """
    members = load_council_members(council_dir)
    if not members:
        return {"query": query, "members": [], "error": "No council members found."}

    tasks = []
    for member in members:
        provider_str = member.get("provider", "anthropic").lower()
        provider = Provider.OPENAI if provider_str == "openai" else Provider.ANTHROPIC

        task_kwargs: dict = {
            "id": member["name"],
            "system": member["system"],
            "prompt": query,
            "provider": provider,
            "metadata": {"name": member["name"]},
        }

        if member.get("model"):
            task_kwargs["model"] = member["model"]
        if member.get("base_url"):
            task_kwargs["base_url"] = member["base_url"]
        if member.get("api_key"):
            task_kwargs["api_key"] = member["api_key"]

        tasks.append(Task(**task_kwargs))

    log.info("Running council with %d members: %s", len(tasks), [t.id for t in tasks])
    pool = DelegatePool(max_workers=max_workers)
    results = pool.run(tasks)

    return {
        "query": query,
        "members": [
            {
                "name": r.id,
                "model": r.model,
                "provider": r.provider.value,
                "content": r.content,
                "error": r.error,
            }
            for r in results.values()
        ],
    }


def format_council_for_orchestrator(council_result: dict) -> str:
    """Format council results into a prompt the orchestrator can synthesize."""
    parts = [
        f'The user asked for a council review of the following query:\n\n"{council_result["query"]}"\n',
        f"{len(council_result['members'])} council members responded. "
        "Please analyze their responses and write a synthesis report that identifies:\n"
        "1. Points of agreement across members\n"
        "2. Points of disagreement or tension\n"
        "3. Unique insights from individual members\n"
        "4. Your overall assessment incorporating their perspectives\n\n"
        "End with a section containing each member's full response for reference.\n",
    ]

    for member in council_result["members"]:
        parts.append(f"--- {member['name'].upper()} ({member['model']}) ---")
        if member["error"]:
            parts.append(f"[ERROR: {member['error']}]")
        else:
            parts.append(member["content"])
        parts.append("")

    return "\n".join(parts)
