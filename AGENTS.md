# Agent Development Guide

This document encodes architectural decisions and constraints for AI coding assistants working on the Narrative Orchestration System. Read this before writing any code.

**Before starting work:**
- Read `docs/DECISIONS.md` for architectural rationale (numbered ADRs)
- Read `docs/TASKS.md` for current work items and implementation notes
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
- **LLMClient abstraction** (`src/llm.py`) with Anthropic and OpenAI backends
- All agents use `client.create()` / `client.create_stream()` — never raw SDK calls
- **Provider registry** (`src/providers.py`) manages configured providers via the web UI
- Agents receive their client from the server — never construct their own
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
GitHub (tracked)             Local (gitignored build/)
─────────────────            ──────────────────────────────
src/                         build/
  agents/                      config.yaml
  web/                         .env  (API keys)
dev/                           lore/
  defaults/                    persona/
  docker/                      story/
  requirements.txt             data/
  setup.sh                     ...
docs/
  code-requests/             docs/code-requests/ is tracked
start.sh / start.bat         (shared via git)
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

`build/config.yaml` (gitignored, user-editable):

```yaml
provider: anthropic

models:
  librarian: <cheap-fast-model>      # Cheaper, faster for lore lookup
  prose_writer: <best-prose-model>   # Best prose quality
  orchestrator: <best-prose-model>   # Consistent personality

paths:
  lore: ./build/lore
  story: ./build/story
  code_requests: ./docs/code-requests
```

`build/.env` (gitignored):

```bash
ANTHROPIC_API_KEY=sk-ant-...
```

The `build/` directory is created by `dev/setup.sh` on first run. It copies defaults from `dev/defaults/` and is the user's personal data directory to back up.

## Common Pitfalls

1. **Don't use async/await** — Adds complexity without benefit for this use case (exception: web layer, ADR-008)
2. **Don't add a database** — Filesystem is sufficient and debuggable
3. **Don't over-engineer the intent classifier** — Start with keywords, add LLM if needed
4. **Don't cache lore in vector DB** — Load files into system prompt for prompt caching
5. **Don't build a chat history system** — The story file IS the history
6. **Don't make the web UI complex** — Text in, text out, mobile-friendly
7. **Don't bypass the LLM abstraction** — All LLM calls go through `LLMClient`. Never create `anthropic.Anthropic()` or `openai.OpenAI()` directly in agent code. Agents that need a fallback should raise `RuntimeError` pointing users to the Model settings UI.

## Testing

### Running Tests

```bash
# Unit tests (no external dependencies)
.venv/bin/python -m pytest tests/ -v

# Include LLM integration tests (requires local Ollama)
.venv/bin/python -m pytest tests/ --run-llm -v
```

### Test Architecture

Tests live in `tests/` and use pytest. There are two categories:

**Unit tests** — Pure logic, no LLM or network calls. These should always pass.
- `test_config.py` — Config loading, defaults, YAML edge cases, path resolution
- `test_forge_manifest.py` — Manifest normalization, chapter key/status mapping, rebuild from files
- `test_character_cards.py` — Card CRUD, PNG parsing, SillyTavern import
- `test_librarian_parsing.py` — JSON extraction from various LLM response formats
- `test_web_search.py` — Search result formatting, disabled provider handling
- `test_layout.py` — Layout config defaults

**Integration tests** (`test_llm_integration.py`) — Require a local model via Ollama.
- Skipped by default, enabled with `--run-llm` flag
- Configure with env vars: `LLM_TEST_BASE_URL`, `LLM_TEST_MODEL`
- Default: `http://localhost:11434/v1` with `qwen2.5:3b`
- Tests: basic completion, tool calling, streaming, multi-turn context

### Testing Guidelines

1. **Test the logic, not the LLM.** Most bugs are in parsing, normalization, path resolution, and state management — not in the model's output. Mock or skip LLM calls in unit tests.

2. **Use `tmp_path` for file operations.** Never write to `build/` in tests. The `sample_config` fixture in `conftest.py` provides an `AppConfig` pointing at temp directories.

3. **Test edge cases from real usage.** When a user reports a bug (e.g., LLM writes manifest with wrong field names), add a test that reproduces the exact input and verifies the fix. The forge manifest tests came directly from real malformed manifests.

4. **New features need tests for:**
   - Config validation (new fields have correct defaults, load from YAML)
   - Input normalization (anything that cleans up LLM output or user input)
   - Error paths (what happens when files are missing, API returns errors)
   - Round-trip consistency (save → load produces the same data)

5. **Don't test internal implementation details.** Test behavior: "given this manifest, loading produces these chapter statuses" — not "the third line of `_normalize_manifest` sets the right variable."

6. **Integration tests should be resilient.** Local models are unpredictable — assert structure (response has content, tool call has name) not exact text. Use `assert "Alice" in response` not `assert response == "Your name is Alice."`.

7. **Keep tests fast.** Unit tests should complete in under 1 second total. Integration tests can take longer but should each complete within 30 seconds.

### Adding Tests for Bug Fixes

When fixing a bug:
1. Write a test that reproduces the bug (it should fail before the fix)
2. Apply the fix
3. Verify the test passes

Example from manifest normalization:
```python
def test_normalize_stage_active_becomes_writing(sample_config):
    """Bug: LLM wrote 'stage: active' which isn't a valid Pydantic literal."""
    fp = ForgeProject("test", sample_config)
    raw = {"project_name": "test", "stage": "active"}
    result = fp._normalize_manifest(raw)
    assert result["stage"] == "writing"
```

### Local LLM Setup for Integration Tests

```bash
# Install Ollama
curl -fsSL https://ollama.com/install.sh | sh

# Pull a small model that fits in 16GB VRAM
ollama pull qwen2.5:3b    # ~2GB, good tool calling support
# or
ollama pull mistral:7b     # ~4GB, stronger but larger

# Run tests
LLM_TEST_MODEL=qwen2.5:3b pytest tests/ --run-llm -v
```

The integration tests use the OpenAI-compatible endpoint that Ollama exposes at `http://localhost:11434/v1`, which routes through the same `OpenAIClient` adapter the production code uses.

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

1. Run `python dev/tools/site_report.py --issue "what the user described"`
2. Read the generated report — it captures system state, project state, content state, and recent logs
3. If you can diagnose and fix the issue, do so
4. If you can't, tell the user to send the report file to Patch (the remote developer)
5. You can also write a code change request to `docs/code-requests/` if the fix requires code changes you're unsure about

Reports land in `docs/code-requests/` by default so they're visible to the developer on next review.

## When to Escalate

If the coding agent is unsure about:
- Provider abstraction strategy
- Session persistence approach
- Story file format (single vs multiple files)
- Orchestrator persona definition
- Content policy implications of provider choices

These are **creative/product decisions**, not technical. Check `docs/DECISIONS.md` first — the answer may already be recorded.
