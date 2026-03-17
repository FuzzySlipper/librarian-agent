# Narrative Orchestration System

A purpose-built creative writing environment replacing SillyTavern for long-form narrative work.

## What This Is

Instead of a chat interface with injected lore, this is a small network of specialized AI agents:

- **Orchestrator** — Your conversational partner. Routes requests, maintains story context, and presents a consistent personality.
- **Librarian** — Grounds all factual recall in your lore files. No hallucination drift, no forgotten details.
- **Prose Writer** — Generates scenes using the Librarian automatically. You say "write the confrontation," it finds the relevant lore and writes.

The system runs locally in Docker, accessible from any device on your WiFi (iPad, laptop, phone).

## Why Not SillyTavern?

| | SillyTavern | This System |
|---|---|---|
| **Lore injection** | Keyword grep, dynamic per turn | Static file load, cached permanently |
| **Prompt caching** | Effectively broken at 100k+ tokens | Full cache on lore + prior story |
| **Cost at scale** | High (full context repriced each turn) | Low (only new tokens priced marginally) |
| **iPad access** | Workable but awkward | First-class via web wrapper |
| **Personalization drift** | Accumulates in model state | Grounded in versioned files |
| **Maintenance** | Manual copy-paste session management | Files in a folder, backed up normally |

## Quick Start

### Prerequisites

- Docker (OrbStack on Mac, docker-cli on Linux)
- Python 3.12+ (for local CLI usage before Docker)
- API key for your configured provider

### Repository Setup

```bash
git clone <repo-url>
cd narrative-system

# Create your content directory (outside the repo)
mkdir -p ~/Documents/narrative-content/{lore,story,code-requests}

# Copy the example environment file
cp .env.example ~/Documents/narrative-content/.env

# Edit with your API key
nano ~/Documents/narrative-content/.env
```

### Lore Migration (Stage 1)

Before running code, migrate your SillyTavern lorebooks:

```
~/Documents/narrative-content/lore/
├── characters/
│   ├── elena-vasquez.md
│   ├── the-archivist.md
│   └── ...
├── locations/
│   ├── the-pale-city.md
│   └── ...
├── factions/
├── events/
└── world-overview.md
```

Each file is just prose descriptions. No special formatting required. See `tools/README.md` for the SillyTavern migration tool.

**Test:** Pick a scene from your existing story. Can you answer every factual question about characters and setting from these files alone?

### Running the Stages

#### Stage 2 — Librarian (CLI)

```bash
pip install -r requirements.txt
python -m src.agents.librarian --query "What does Elena know about the Archivist?"
```

The Librarian loads all lore files at startup and answers queries from that cached knowledge.

#### Stage 3 — Prose Writer (CLI)

```bash
python -m src.agents.prose_writer --scene "Elena confronts the Archivist in the library"
```

The Writer automatically calls the Librarian when it needs lore details. You don't manage this.

#### Stage 4 — Orchestrator (CLI)

```bash
python -m src.main
```

Now you talk to the Orchestrator directly. It decides whether to write a scene, answer a lore question, discuss story planning, or handle revisions.

#### Stage 5 — Web Wrapper + Docker

```bash
docker-compose up
```

Access from any device on your local network. On iPad: open Safari, navigate to your machine's IP on port 8005, add to Home Screen.

## Configuration

Edit `config.yaml` (committed to repo, no secrets). Models are configured per agent — use cheaper/faster models for lore lookup, better models for prose generation. Provider is swappable via config.

## File Organization

### Repository (Code)
- `/src` — Python agents and web server
- `config.yaml` — Model selection, paths
- `AGENTS.md` — Architecture guide for coding assistants
- `DECISIONS.md` — Architectural decisions with rationale
- `TASKS.md` — Current work items and implementation notes

### Local Machine (Content)
- `~/Documents/narrative-content/.env` — API keys (never committed)
- `~/Documents/narrative-content/lore/` — Character, location, faction files (your world)
- `~/Documents/narrative-content/story/` — Append-only story drafts
- `~/Documents/narrative-content/code-requests/` — Orchestrator's code change requests

## Architecture

```
User (Tablet/Phone/Laptop)
    ↓
Orchestrator (FastAPI / CLI)
    ↓
    ├── Librarian ──→ Lore files (read-only, cached)
    ├── Prose Writer ──→ Story file (append-only)
    └── Filesystem tools ──→ Lore, story, code-requests (scoped to mounted volumes)
```

- **Append-only**: Story grows forever. Revision creates new passages, doesn't overwrite history.
- **Prompt caching**: Lore + story context cached, dramatic cost reduction.
- **Persona budgeting**: Personality files are tiered and token-capped to prevent hallucination drift.

## Development

This project is designed to be built incrementally with AI coding assistance:

1. Read `AGENTS.md` — architecture and code patterns
2. Read `DECISIONS.md` — rationale behind design choices
3. Check `TASKS.md` — current work items
4. Work through stages sequentially
5. Update `TASKS.md` and `DECISIONS.md` as you go

```bash
# Local dev setup
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt  # pytest, mypy, ruff

pytest tests/
python -m src.main --cli
```

## Common Issues

**"Librarian returns empty results"**
- Check that lore files exist in the lore directory
- Verify Docker volume mount in `docker-compose.yaml`
- Ensure files are valid UTF-8

**"Story file not updating"**
- Check permissions on the story directory
- Container needs write access to story volume

**"API errors"**
- Verify `.env` exists and has a valid key
- Check `config.yaml` provider matches your API key type

**"Can't access from iPad"**
- Devices must be on same WiFi network
- Use machine's local IP, not `localhost`
- Check firewall settings

## License

MIT
