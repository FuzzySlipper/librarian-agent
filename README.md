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
| **Maintenance** | Manual copy-paste session management | Files in a folder, backed up by Time Machine |

## Quick Start

### Prerequisites

- [OrbStack](https://orbstack.dev/) (free for personal use) for Mac or Docker-cli for Linux
- Python 3.12+ (for local CLI usage before Docker)
- Anthropic API key (or OpenAI/Kimi if configured)

### Repository Setup

```bash
# Clone the code repository
git clone https://github.com/YOUR_USERNAME/narrative-system.git
cd narrative-system

# Create your content directory (outside the repo)
mkdir -p ~/Documents/narrative-content/{lore,story}

# Copy the example environment file
cp .env.example ~/Documents/narrative-content/.env

# Edit with your API key
open ~/Documents/narrative-content/.env
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

Each file is just prose descriptions. No special formatting required.

**Test:** Pick a scene from your existing story. Can you answer every factual question about characters and setting from these files alone?

### Running the Stages

#### Stage 2 — Librarian (CLI)

```bash
# Install dependencies
pip install -r requirements.txt

# Test the Librarian
python -m src.agents.librarian --query "What does Elena know about the Archivist?"
```

The Librarian loads all lore files at startup and answers queries from that cached knowledge.

#### Stage 3 — Prose Writer (CLI)

```bash
# Interactive prose generation
python -m src.agents.prose_writer

# Or single scene
python -m src.agents.prose_writer --scene "Elena confronts the Archivist in the library"
```

The Writer automatically calls the Librarian when it needs lore details. You don't manage this.

#### Stage 4 — Orchestrator (CLI)

```bash
# Full conversational interface
python -m src.main
```

Now you talk to the Orchestrator directly. It decides whether to:
- Write a scene (engages Prose Writer)
- Answer a lore question (queries Librarian directly)
- Discuss story planning (no generation)
- Handle revisions (re-engages Writer with constraints)

#### Stage 5 — Web Wrapper + Docker

```bash
# Start the container
docker-compose up

# Access from any device on your WiFi
open http://$(ipconfig getifaddr en0):8000
```

On your iPad: open Safari, navigate to `http://YOUR_MAC_IP:8000`, add to Home Screen for app-like experience.

## Configuration

Edit `config.yaml` (committed to repo, no secrets):

```yaml
provider: anthropic

models:
  librarian: claude-haiku-4-5-20251001    # Cheaper, faster for lore lookup
  prose_writer: claude-sonnet-4-6         # Best prose quality
  orchestrator: claude-sonnet-4-6         # Consistent personality

# Switching providers is a config edit, not a code change
# provider: openai
# models:
#   prose_writer: gpt-4o
```

## File Organization

### GitHub Repository (Code)
- `/src` — Python agents and web server
- `config.yaml` — Model selection, paths
- `docker-compose.yaml` — Container orchestration
- `requirements.txt` — Python dependencies
- `AGENTS.md` — Architecture guide for coding assistants

### Local Machine (Content)
- `~/Documents/narrative-content/.env` — API keys (never committed)
- `~/Documents/narrative-content/lore/` — Character, location, faction files (your world)
- `~/Documents/narrative-content/story/current-draft.md` — Append-only story

**Backup strategy:** Local backup covers your content directory. GitHub backs up code.

## Architecture

```
User (Tablet/Phone/Laptop)
    ↓
Orchestrator (FastAPI / CLI)
    ↓
    ├── Librarian ──→ Lore files (read-only, cached)
    └── Prose Writer ──→ Story file (append-only)
```

- **Stateless**: Each request is independent. State lives in the story file.
- **Append-only**: Story grows forever. Revision creates new passages, doesn't overwrite history.
- **Prompt caching**: Lore + story context cached by Anthropic, dramatic cost reduction.

## Development

### For Non-Technical Users (Vibe Coding)

This project is designed to be built incrementally with AI coding assistance (Claude Code, Cursor, etc.):

1. Read `AGENTS.md` first — it encodes the architecture
2. Work through stages 1-5 sequentially
3. Each stage has a test in `tests/test_stage_N.py`
4. Commit after each working session

### For Technical Contributors

```bash
# Setup
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt  # pytest, mypy, ruff

# Testing
pytest tests/
mypy src/
ruff check src/

# Running locally (no Docker)
python -m src.main --cli
```

## Common Issues

**"Librarian returns empty results"**
- Check that lore files exist in `~/Documents/narrative-content/lore/`
- Verify Docker volume mount in `docker-compose.yaml`
- Ensure files are valid UTF-8

**"Story file not updating"**
- Check permissions on `~/Documents/narrative-content/story/`
- Container needs write access to story volume
- Verify `current-draft.md` exists (create empty file if needed)

**"API errors"**
- Verify `~/Documents/narrative-content/.env` exists and has valid key
- Check `config.yaml` provider matches your API key type
- For Anthropic: ensure `ANTHROPIC_API_KEY` not `ANTHROPIC_API_KEY=` (no value)

**"Can't access from iPad"**
- Laptop and iPad must be on same WiFi network
- Use Mac's local IP, not `localhost`
- Check firewall settings

## Roadmap / Open Questions

- [ ] Provider decision: Anthropic vs Kimi vs both (start with one, swap via config)
- [ ] Orchestrator persona: Name, voice, relationship to story
- [ ] Story file format: Single append-only vs chapter-segmented files
- [ ] Revision workflow: Write to separate draft file or overwrite in place
- [ ] Content directory location: Documents folder vs dedicated location

See `narrative-system-plan.md` for full development plan.

## License

MIT — Feel free to fork and adapt for your own writing workflow.

## Acknowledgments

Built to escape SillyTavern's brittleness. Inspired by:
- FastAPI's developer experience philosophy
