#!/usr/bin/env bash
set -euo pipefail

# Populate the build/ directory with defaults for a new user.
# Re-run when dev/VERSION changes to pick up new defaults.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
BUILD_DIR="$PROJECT_DIR/build"
DEV_DIR="$SCRIPT_DIR"

echo "Setting up build/ directory..."

# ── Create directory structure ────────────────────────────────────
mkdir -p "$BUILD_DIR"/{data,story,writing,chats,forge,generated-images,portraits}

# ── Copy content defaults (only if target dir is missing/empty) ──
copy_defaults() {
    local src="$1" dst="$2"
    if [ ! -d "$dst" ] || [ -z "$(ls -A "$dst" 2>/dev/null)" ]; then
        echo "  Populating $dst"
        mkdir -p "$dst"
        cp -r "$src"/. "$dst"/
    else
        echo "  Skipping $dst (already has content)"
    fi
}

copy_defaults "$DEV_DIR/defaults/lore"            "$BUILD_DIR/lore"
copy_defaults "$DEV_DIR/defaults/persona"         "$BUILD_DIR/persona"
copy_defaults "$DEV_DIR/defaults/writing-styles"  "$BUILD_DIR/writing-styles"
copy_defaults "$DEV_DIR/defaults/council"         "$BUILD_DIR/council"
copy_defaults "$DEV_DIR/defaults/layouts"         "$BUILD_DIR/layouts"
copy_defaults "$DEV_DIR/defaults/layout-images"   "$BUILD_DIR/layout-images"
copy_defaults "$DEV_DIR/defaults/forge-prompts"   "$BUILD_DIR/forge-prompts"

# ── Config file ───────────────────────────────────────────────────
if [ ! -f "$BUILD_DIR/config.yaml" ]; then
    echo "  Creating config.yaml"
    cp "$DEV_DIR/config.yaml.default" "$BUILD_DIR/config.yaml"
fi

# ── .env file ─────────────────────────────────────────────────────
if [ ! -f "$BUILD_DIR/.env" ]; then
    echo "  Creating .env from example"
    cp "$DEV_DIR/.env.example" "$BUILD_DIR/.env"
    echo ""
    echo "  *** Edit build/.env to add your API key, or configure providers in the UI. ***"
    echo ""
fi

# ── Write version stamp ──────────────────────────────────────────
cp "$DEV_DIR/VERSION" "$BUILD_DIR/.setup-version"

echo "Setup complete. Your personal data lives in build/"
echo "Back up this directory — it contains your configs, lore, and stories."
