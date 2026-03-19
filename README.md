# Narrative Orchestration System

A purpose-built creative writing environment with specialized AI agents for long-form narrative work.

## Quick Start

```bash
git clone <repo-url>
cd librarian-agent

# Linux / macOS
./start.sh

# Windows
start.bat
```

On first run the start script will:
1. Create `build/` with default configs, lore, and persona files
2. Set up a Python virtual environment and install dependencies
3. Start the server on http://localhost:8005

**Edit `build/.env`** to add your API key (or configure providers in the UI).

Access from any device on your local network using your machine's IP address.

## Project Structure

```
.
├── start.sh / start.bat    # Launch scripts (run these)
├── AGENTS.md               # Architecture guide for AI coding assistants
├── src/                    # Application code
├── static/                 # Pre-built frontend (served by server)
│
├── build/                  # YOUR personal data (gitignored — back this up!)
│   ├── config.yaml         # Model & path configuration
│   ├── .env                # API keys
│   ├── lore/               # Your world-building files
│   ├── persona/            # AI personality definitions
│   ├── writing-styles/     # Prose style guides
│   ├── council/            # Council advisor prompts
│   ├── layouts/            # UI layout definitions
│   ├── forge-prompts/      # Story forge prompts
│   ├── story/              # Append-only story drafts
│   ├── writing/            # Writing workspace
│   ├── chats/              # Chat history
│   ├── forge/              # Story forge output
│   ├── data/               # Runtime data (keys, model cache)
│   └── generated-images/   # AI-generated images
│
├── docs/                   # Documentation & shared files
│   ├── code-requests/      # Orchestrator code change requests (committable)
│   ├── architecture-guide.html
│   └── artifacts.md
│
└── dev/                    # Development & setup files
    ├── setup.sh / setup.bat    # Build directory setup scripts
    ├── defaults/               # Template data (copied to build/ on setup)
    ├── config.yaml.default     # Default config template
    ├── .env.example            # Example environment file
    ├── docker/                 # Docker configuration
    ├── frontend/               # Frontend source (for rebuilding UI)
    ├── tools/                  # Migration & utility scripts
    ├── tests/                  # Test suite
    ├── requirements.txt        # Python dependencies
    ├── requirements-dev.txt    # Dev dependencies (pytest, ruff, etc.)
    └── VERSION                 # Setup version stamp
```

### What goes where?

| Directory | Tracked in git? | Who manages it? | Back it up? |
|-----------|----------------|-----------------|-------------|
| `src/`, `static/` | Yes | Developers | No (use git) |
| `dev/` | Yes | Developers | No (use git) |
| `docs/` | Yes | Everyone | No (use git) |
| `build/` | **No** | You | **Yes!** |

**`build/` is your personal directory.** It contains your lore, stories, API keys, and configs. Back it up, put it in its own git repo, sync it however you like.

**`docs/code-requests/`** is the one shared runtime directory — it stays in git so the orchestrator's code requests can be committed and shared.

## How It Works

Three specialized agents work together:

- **Orchestrator** — Your conversational partner. Routes requests and maintains story context.
- **Librarian** — Grounds recall in your lore files. No hallucination drift.
- **Prose Writer** — Generates scenes using the Librarian automatically.

## Configuration

Edit `build/config.yaml` to change models, paths, or behavior. Models are configured per agent — use cheaper models for lore lookup, better models for prose.

## Start Script Options

```bash
./start.sh                    # Normal start
./start.sh --update           # Git pull + restart
./start.sh --build-frontend   # Rebuild frontend from source (needs Node.js)
./start.sh --setup            # Force re-run setup (won't overwrite your data)
./start.sh --port=9000        # Custom port
```

## Updating

```bash
./start.sh --update
```

If `dev/VERSION` has changed, setup will re-run automatically to apply new defaults. Your existing data in `build/` is never overwritten — only missing files are populated.

## Development

```bash
# Install dev dependencies
pip install -r dev/requirements.txt
pip install -r dev/requirements-dev.txt

# Run tests
pytest dev/tests/

# Rebuild frontend
./start.sh --build-frontend

# Architecture & decisions
cat AGENTS.md
cat docs/*.md
```

See `dev/tools/README.md` for the SillyTavern migration tool.

## Common Issues

**"Can't find config / lore is empty"** — Run `./start.sh --setup` to regenerate `build/`.

**"API errors"** — Check `build/.env` has a valid key matching your `build/config.yaml` provider.

**"Can't access from iPad"** — Same WiFi network, use machine's local IP (not localhost), check firewall.

## License

MIT
