#!/usr/bin/env bash
set -euo pipefail

# Narrative Orchestration System — Launch Script
# Usage: ./start.sh [--update] [--build] [--port PORT]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PORT="${PORT:-8005}"
HOST="${HOST:-0.0.0.0}"
VENV_DIR=".venv"
STATIC_DIR="static"
BUILD_DIR="build"
DEV_DIR="dev"

# Parse arguments
DO_UPDATE=false
BUILD_FRONTEND=false
FORCE_SETUP=false
for arg in "$@"; do
    case "$arg" in
        --update)         DO_UPDATE=true ;;
        --build|--build-frontend) BUILD_FRONTEND=true ;;
        --setup)          FORCE_SETUP=true ;;
        --port=*)         PORT="${arg#*=}" ;;
        --port)           shift; PORT="${1:-8005}" ;;
        --help|-h)
            echo "Usage: ./start.sh [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --update           Pull latest code and update dependencies"
            echo "  --build            Rebuild frontend (requires Node.js)"
            echo "  --setup            Force re-run setup (won't overwrite your data)"
            echo "  --port=PORT        Set server port (default: 8005)"
            echo "  -h, --help         Show this help"
            echo ""
            echo "Environment variables:"
            echo "  PORT               Server port (default: 8005)"
            echo "  HOST               Bind address (default: 0.0.0.0)"
            exit 0
            ;;
    esac
done

# ── Git update ───────────────────────────────────────────────────
if $DO_UPDATE; then
    echo "Pulling latest changes..."
    git pull --ff-only || {
        echo "Git pull failed — you may have local changes. Resolve and retry."
        exit 1
    }
fi

# ── Build directory setup ────────────────────────────────────────
NEEDS_SETUP=false

if [ ! -d "$BUILD_DIR" ]; then
    NEEDS_SETUP=true
elif [ ! -f "$BUILD_DIR/.setup-version" ]; then
    NEEDS_SETUP=true
elif ! diff -q "$DEV_DIR/VERSION" "$BUILD_DIR/.setup-version" &>/dev/null; then
    echo "New version detected — running setup to apply updates..."
    NEEDS_SETUP=true
fi

if $FORCE_SETUP; then
    NEEDS_SETUP=true
fi

if $NEEDS_SETUP; then
    bash "$DEV_DIR/setup.sh"
fi

# ── Python virtual environment ───────────────────────────────────
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating Python virtual environment..."
    if command -v uv &>/dev/null; then
        uv venv "$VENV_DIR"
    else
        python3 -m venv "$VENV_DIR"
    fi
fi

PYTHON="$VENV_DIR/bin/python"

echo "Installing Python dependencies..."
if command -v uv &>/dev/null; then
    uv pip install --python "$PYTHON" -r "$DEV_DIR/requirements.txt" --quiet
else
    "$VENV_DIR/bin/pip" install -r "$DEV_DIR/requirements.txt" --quiet
fi

# ── Frontend build (optional) ───────────────────────────────────
if $BUILD_FRONTEND; then
    if command -v npm &>/dev/null; then
        echo "Building frontend..."
        (cd "$DEV_DIR/frontend" && npm install && npm run build)
        rm -rf "$STATIC_DIR"
        cp -r "$DEV_DIR/frontend/dist" "$STATIC_DIR"
        echo "Frontend built to $STATIC_DIR/"
    else
        echo "Warning: npm not found. Cannot build frontend."
        echo "Install Node.js or use the pre-built static/ directory."
    fi
fi

if [ ! -d "$STATIC_DIR" ]; then
    echo ""
    echo "Warning: No $STATIC_DIR/ directory found."
    echo "Run with --build to build, or ensure pre-built files are present."
    echo "The API will still work, but there will be no web UI."
    echo ""
fi

# ── Launch server ────────────────────────────────────────────────
export CONFIG_PATH="$BUILD_DIR/config.yaml"
export DOTENV_PATH="$BUILD_DIR/.env"

echo ""
echo "Starting server on http://localhost:${PORT}"
echo "Press Ctrl+C to stop."
echo ""

exec "$PYTHON" -m uvicorn src.web.server:app --host "$HOST" --port "$PORT"
