# Agent Development Guide

This document encodes architectural decisions and constraints for AI coding assistants working on the Narrative Orchestration System. Read this before writing any code.

**Before starting work:**
- Read `DECISIONS.md` for architectural rationale (numbered ADRs)
- Read `TASKS.md` for current work items and implementation notes
- Update both files as decisions are made or tasks progress

## Project Overview

A purpose-built creative writing system replacing SillyTavern. Instead of a chat interface with injected lore, this is a small network of specialized agents:

- **Orchestrator**: Conversational interface + routing (the personality)
- **Librarian**: Lore queries → structured bundles from markdown files
- **Prose Writer**: Scene generation, auto-calls Librarian via tool use

## Stack & Constraints

### Language & Runtime
- **Python 3.12+** (no async/await unless specifically requested — see ADR-008)
- **Synchronous I/O** throughout — simpler debugging for non-technical users
- **Type hints required** on all public functions and class methods
- **Pydantic** for data validation and configuration

### LLM Integration
- **Anthropic SDK** as primary provider (provider swapping deferred — see ADR-007)
- **Prompt caching** is a core architectural feature — design for it
- Model selection via `config.yaml` (different models per agent allowed)

### Dependencies (Minimal)
```
anthropic
pydantic>=2.0.0
pyyaml>=6.0
fastapi
uvicorn[standard]
python-dotenv
```

No ORMs, no vector databases, no message queues. Filesystem is the database.

### Storage Architecture

**Two-layer separation:**

```
GitHub (public)              Local (never committed)
─────────────────            ──────────────────────────────
/src                         ~/Documents/narrative-content/
  agents/                      .env  (API keys)
  web/                         lore/
  config.yaml                    characters/
  docker-compose.yaml            locations/
  Dockerfile                     factions/
  requirements.txt             story/
  .gitignore                     current-draft.md
                               code-requests/
```

- **Content directories** mounted via Docker volumes
- **Story files**: Append-only markdown
- **Lore files**: Read-only at runtime, loaded into memory at startup
- **Code requests**: Orchestrator writes structured change requests here (see ADR-004)

## Agent Design Patterns

### Librarian Pattern
```python
class Librarian:
    """Loads lore files once, answers queries from cached content."""

    def __init__(self, lore_dir: Path, model: str):
        self.lore_content = self._load_all_lore(lore_dir)
        self.client = anthropic.Anthropic()
        self.model = model
        self.system_prompt = self._build_system_prompt()

    def query(self, query: str) -> LoreBundle:
        """Return relevant passages. No prose generation."""
        response = self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            system=self.system_prompt,  # Cached by Anthropic after first call
            messages=[{"role": "user", "content": query}],
        )
        return self._parse_response(response.content[0].text)
```

**Key constraints:**
- Load files at startup, not per-query
- Never write prose — return structured lore only
- Return source file names for provenance
- When lore outgrows a single system prompt, switch to two-phase index lookup (ADR-002)

### Prose Writer Pattern

Uses a **tool-use loop** to query the Librarian automatically. The model may call the lore tool multiple times before producing final prose.

```python
def write_scene(self, description: str, story_context: str) -> str:
    tools = [{"name": "query_lore", ...}]
    messages = [{"role": "user", "content": description}]

    while True:
        response = self.client.messages.create(
            model=self.model,
            system=self._build_system_prompt(story_context),
            messages=messages,
            tools=tools,
        )

        if response.stop_reason == "end_turn":
            return extract_text(response)

        # Handle tool calls and continue the loop
        messages.append({"role": "assistant", "content": response.content})
        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                lore = self.librarian.query(block.input["query"])
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": lore.model_dump_json(),
                })
        messages.append({"role": "user", "content": tool_results})
```

**Key constraints:**
- Must use tool calling for lore queries (user never manually queries)
- Appends output to story file, never overwrites
- Maintains consistent voice/style from story context

### Orchestrator Pattern

The Orchestrator is a **tool-use loop with broad filesystem access** (ADR-003). It classifies intent and routes to the appropriate agent or handles directly.

**Key capabilities:**
- Routes to Librarian, Prose Writer, or handles directly based on intent
- Persona system with tiered loading and token budgeting (ADR-005)
- Delegates technical queries to a clean agent call without persona overhead (ADR-006)
- Can read/write/search files within mounted volumes
- Can write structured code change requests (ADR-004)
- Dice rolling for randomized outcomes — pure RNG, no LLM overhead (ADR-011)
- Story state tracking via companion .state.yaml files — structured metadata separate from prose (ADR-011)
- Logs responses for portability (ADR-009)

**Key constraints:**
- Defines the "personality" of the system
- Maintains session state (what was just written, current mode)
- Never exposes internal agent boundaries to user

## Data Models

Use Pydantic for all inter-agent communication:

```python
class LoreBundle(BaseModel):
    """Output from Librarian."""
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
```

## File Organization

```
src/
├── __init__.py
├── main.py                    # CLI entry point (Stages 2-4)
├── config.py                  # Pydantic models for config.yaml
├── models.py                  # Shared Pydantic models (above)
├── agents/
│   ├── __init__.py
│   ├── librarian.py
│   ├── prose_writer.py
│   └── orchestrator.py
├── web/
│   ├── __init__.py
│   └── server.py              # FastAPI wrapper (Stage 5)
└── utils/
    ├── __init__.py
    └── file_utils.py          # Safe file append, lore loading
```

## Configuration

`config.yaml` (committed, no secrets):

```yaml
provider: anthropic

models:
  librarian: <cheap-fast-model>      # Cheaper, faster for lore lookup
  prose_writer: <best-prose-model>   # Best prose quality
  orchestrator: <best-prose-model>   # Consistent personality

librarian:
  max_tokens_per_query: 1024

prose_writer:
  max_tokens_per_scene: 4096
  auto_append_to_story: true

persona:
  max_tokens: 2000               # Token budget for personality content

paths:
  lore: /app/lore                # In-container paths
  story: /app/story
  code_requests: /app/code-requests
```

`.env` (never committed, mounted at runtime):

```bash
ANTHROPIC_API_KEY=sk-ant-...
```

## Docker Constraints

```yaml
services:
  narrator:
    build: .
    ports:
      - "8005:8005"
    env_file:
      - ~/Documents/narrative-content/.env
    volumes:
      - ~/Documents/narrative-content/lore:/app/lore:ro
      - ~/Documents/narrative-content/story:/app/story
      - ~/Documents/narrative-content/code-requests:/app/code-requests
    environment:
      - CONFIG_PATH=/app/config.yaml
```

- Container has no secrets at build time
- Lore is read-only (`:ro`)
- Story and code-requests are read-write

## Common Pitfalls

1. **Don't use async/await** — Adds complexity without benefit for this use case (exception: web layer, ADR-008)
2. **Don't add a database** — Filesystem is sufficient and debuggable
3. **Don't over-engineer the intent classifier** — Start with keywords, add LLM if needed
4. **Don't cache lore in vector DB** — Load files into system prompt for prompt caching
5. **Don't build a chat history system** — The story file IS the history
6. **Don't make the web UI complex** — Text in, text out, mobile-friendly
7. **Don't build provider abstraction prematurely** — Build against Anthropic SDK, abstract when needed

## Code Review Checklist

- [ ] Type hints on all public methods
- [ ] Docstrings explain "why" not just "what"
- [ ] No hardcoded paths (use config)
- [ ] No secrets in code
- [ ] Safe file append (atomic if possible)
- [ ] Error messages are user-friendly
- [ ] Logging for debugging, not print statements

## Troubleshooting & Remote Support

The users of this system are non-technical. If a user reports a problem:

1. Run `python tools/site_report.py --issue "what the user described"`
2. Read the generated report — it captures system state, project state, content state, and recent logs
3. If you can diagnose and fix the issue, do so
4. If you can't, tell the user to send the report file to Patch (the remote developer)
5. You can also write a code change request to `code-requests/` if the fix requires code changes you're unsure about

Reports land in `code-requests/` by default so they're visible to the developer on next review.

## When to Escalate

If the coding agent is unsure about:
- Provider abstraction strategy
- Session persistence approach
- Story file format (single vs multiple files)
- Orchestrator persona definition
- Content policy implications of provider choices

These are **creative/product decisions**, not technical. Check `DECISIONS.md` first — the answer may already be recorded.
