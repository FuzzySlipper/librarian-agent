# Agent Development Guide

This document encodes architectural decisions and constraints for AI coding assistants working on the Narrative Orchestration System. Read this before writing any code.

## Project Overview

A purpose-built creative writing system replacing SillyTavern. Instead of a chat interface with injected lore, this is a small network of specialized agents:

- **Orchestrator**: Conversational interface + routing (the personality)
- **Librarian**: Lore queries → structured bundles from markdown files
- **Prose Writer**: Scene generation, auto-calls Librarian via tool use

## Stack & Constraints

### Language & Runtime
- **Python 3.12+** (no async/await unless specifically requested)
- **Synchronous I/O** throughout—simpler debugging for non-technical users
- **Type hints required** on all public functions and class methods
- **Pydantic** optional for data validation and configuration

### LLM Integration
- **Anthropic SDK** ( Claude ) as primary provider
- **Prompt caching** is a core architectural feature—design for it
- Model selection via `config.yaml` (different models per agent allowed)

### Dependencies (Minimal)
```
anthropic>=0.40.0
pydantic>=2.0.0
pyyaml>=6.0
fastapi>=0.115.0
uvicorn[standard]>=0.32.0
python-dotenv>=1.0.0
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
```

- **Content directories** mounted via Docker volumes
- **Story files**: Append-only markdown
- **Lore files**: Read-only at runtime, loaded into memory at startup

## Development Stages

Work happens in 5 stages. Each stage produces something testable before moving on.

| Stage | Deliverable | Test |
|-------|-------------|------|
| 1 | Lore folder structure | Can answer factual questions from files |
| 2 | Librarian CLI | 10-15 queries, verify accuracy |
| 3 | Prose Writer CLI | Write 2-3 scenes, verify lore queries fire |
| 4 | Orchestrator CLI | Full routing test, persona evaluation |
| 5 | Web + Docker | Accessible from iPad on same WiFi |

## Agent Design Patterns

### Librarian Pattern
```python
class Librarian:
    """Loads lore files once, answers queries from cached content."""
    
    def __init__(self, lore_dir: Path, model: str):
        self.lore_content = self._load_all_lore(lore_dir)
        self.client = anthropic.Anthropic()
        self.model = model
        # System prompt includes ALL lore text (cached after first call)
        self.system_prompt = self._build_system_prompt()
    
    def query(self, query: str) -> LoreBundle:
        """Return relevant passages. No prose generation."""
        response = self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            system=self.system_prompt,  # Cached
            messages=[{"role": "user", "content": query}],
        )
        return self._parse_response(response.content[0].text)
```

**Key constraints:**
- Load files at startup, not per-query
- Never write prose—return structured lore only
- Return source file names for provenance

### Prose Writer Pattern
```python
class ProseWriter:
    """Generates scenes. Calls Librarian automatically via tool use."""
    
    def __init__(self, librarian: Librarian, model: str):
        self.librarian = librarian
        self.client = anthropic.Anthropic()
        self.model = model
    
    def write_scene(self, description: str, story_context: str) -> str:
        """Generate prose, appending to story file."""
        tools = [{
            "name": "query_lore",
            "description": "Query the Librarian for relevant lore",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"}
                },
                "required": ["query"]
            }
        }]
        
        response = self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=self._build_system_prompt(story_context),
            messages=[{"role": "user", "content": description}],
            tools=tools,
        )
        
        # Handle tool calls automatically
        if response.stop_reason == "tool_use":
            tool_result = self._handle_tool_use(response.content)
            # Continue conversation with tool result...
        
        return response.content[0].text
```

**Key constraints:**
- Must use tool calling for lore queries (user never manually queries)
- Appends output to story file, never overwrites
- Maintains consistent voice/style from story context

### Orchestrator Pattern
```python
class Orchestrator:
    """Routes user intent. The only agent the user talks to directly."""
    
    def __init__(self, librarian: Librarian, writer: ProseWriter, model: str):
        self.librarian = librarian
        self.writer = writer
        self.client = anthropic.Anthropic()
        self.model = model
        self.persona = self._load_persona()
        self.session_state = SessionState()
    
    def handle(self, user_input: str) -> Response:
        """Route based on intent classification."""
        intent = self._classify_intent(user_input)
        
        if intent == Intent.SCENE_WRITING:
            return self._delegate_to_writer(user_input)
        elif intent == Intent.LORE_QUESTION:
            return self._query_librarian_directly(user_input)
        elif intent == Intent.STORY_PLANNING:
            return self._discuss_planning(user_input)
        elif intent == Intent.REVISION:
            return self._handle_revision(user_input)
        else:
            return self._freeform_discussion(user_input)
    
    def _classify_intent(self, text: str) -> Intent:
        """Simple classification—can be rule-based or LLM-based."""
        # Start with keyword matching for speed
        # Fall back to LLM for ambiguous cases
        pass
```

**Key constraints:**
- Defines the "personality" of the system
- Maintains session state (what was just written, current mode)
- Never exposes internal agent boundaries to user

## Data Models

Use Pydantic for all inter-agent communication:

```python
from pydantic import BaseModel, Field
from typing import List, Literal
from pathlib import Path

class LoreBundle(BaseModel):
    """Output from Librarian."""
    relevant_passages: List[str] = Field(description="Direct quotes from lore files")
    source_files: List[str] = Field(description="Which files provided this info")
    confidence: Literal["high", "medium", "low"] = Field(default="high")

class ProseRequest(BaseModel):
    """Input to Prose Writer."""
    scene_description: str
    story_context: str  # Last N paragraphs of current draft
    tone_notes: str | None = None

class ProseResult(BaseModel):
    """Output from Prose Writer."""
    generated_text: str
    lore_queries_made: List[str]
    word_count: int

class Response(BaseModel):
    """Output from Orchestrator to user."""
    content: str
    response_type: Literal["prose", "lore_answer", "discussion", "confirmation"]
    suggested_next: List[str] | None = None  # Helpful prompts

class SessionState(BaseModel):
    """Maintained by Orchestrator."""
    current_mode: Literal["writing", "planning", "reviewing"] = "writing"
    last_scene_summary: str | None = None
    pending_revision: bool = False
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
  librarian: claude-haiku-4-5-20251001
  prose_writer: claude-sonnet-4-6
  orchestrator: claude-sonnet-4-6

librarian:
  max_tokens_per_query: 1024
  
prose_writer:
  max_tokens_per_scene: 4096
  auto_append_to_story: true

paths:
  lore: /app/lore           # In-container paths
  story: /app/story
```

`.env` (never committed, mounted at runtime):

```bash
ANTHROPIC_API_KEY=sk-ant-...
```

## Testing Strategy

Each stage includes a standalone test script:

```python
# tests/test_stage_2.py
import sys
sys.path.insert(0, 'src')

from agents.librarian import Librarian
from pathlib import Path

def test_librarian():
    lib = Librarian(lore_dir=Path("../content/lore"), model="claude-haiku-4-5")
    
    # Test queries based on friend's actual lore
    result = lib.query("What does Elena know about the Archivist?")
    assert len(result.relevant_passages) > 0
    assert "elena-vasquez.md" in result.source_files
    
    # Verify no hallucination
    result2 = lib.query("What is Elena's favorite color?")
    # Should return low confidence or empty if not in lore
    
    print("✓ Stage 2 tests pass")

if __name__ == "__main__":
    test_librarian()
```

Tests should be **runnable** with a single command.

## Docker Constraints

`docker-compose.yaml`:

```yaml
services:
  narrator:
    build: .
    ports:
      - "8000:8000"
    env_file:
      - ~/Documents/narrative-content/.env
    volumes:
      - ~/Documents/narrative-content/lore:/app/lore:ro
      - ~/Documents/narrative-content/story:/app/story
    environment:
      - CONFIG_PATH=/app/config.yaml
```

**Important:**
- Container has no secrets at build time
- Lore is read-only (`:ro`)
- Story is read-write (append-only by convention)

## Common Pitfalls

1. **Don't use async/await** - Adds complexity without benefit for this use case
2. **Don't add a database** - Filesystem is sufficient and debuggable
3. **Don't over-engineer the intent classifier** - Start with keywords, add LLM if needed
4. **Don't cache lore in vector DB** - Load files into system prompt for prompt caching
5. **Don't build a chat history system** - The story file IS the history
6. **Don't make the web UI complex** - Text in, text out, mobile-friendly

## Code Review Checklist

Before submitting code:

- [ ] Type hints on all public methods
- [ ] Docstrings explain "why" not just "what"
- [ ] No hardcoded paths (use config)
- [ ] No secrets in code
- [ ] Safe file append (atomic if possible)
- [ ] Error messages are user-friendly
- [ ] Logging for debugging, not print statements

## When to Escalate

If the coding agent is unsure about:
- Provider abstraction (OpenAI vs Anthropic switching)
- Session persistence approach
- Story file format (single vs multiple files)
- Orchestrator persona definition

These are **creative/product decisions**, not technical.
