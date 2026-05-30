#!/usr/bin/env bash
# start.sh — Launch the Logbook web interface.
# Run this once from the project folder: ./start.sh
set -e

# Install uv if it's not already available.
if ! command -v uv &>/dev/null; then
    echo "Setting up package manager (one-time, ~30 seconds)..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    # Add uv to PATH for this session.
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
    if ! command -v uv &>/dev/null; then
        echo ""
        echo "ERROR: Could not find uv after install."
        echo "Please close this Terminal window, open a new one, and run ./start.sh again."
        exit 1
    fi
    echo "Done."
fi

# Move into logbook-tools (where pyproject.toml lives).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/logbook-tools"

echo ""
echo "Starting Logbook..."
echo "Your browser will open automatically. If it doesn't, go to: http://localhost:5000"
echo "Press Ctrl+C in this window to stop."
echo ""

uv run logbook-import serve "$@"
