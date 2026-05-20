#!/usr/bin/env bash
# Regenerate the published map GeoJSON from current Airtable data and push it.
# No prompts — intended to be run after every batch of new imports.
#
# Requires:
#   - this directory is the root of the logbook git repo
#   - logbook-tools/.venv exists with the project installed
#   - Airtable credentials available in env (or .env loaded by the CLI)
#   - a configured `origin` remote with push access
#
# Exits 0 cleanly even if no data has changed.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

OUTPUT="docs/map_data.geojson"
mkdir -p "$(dirname "$OUTPUT")"

echo "→ Querying Airtable for flight + airport data (takes ~30s)…"
./logbook-tools/.venv/bin/python -m logbook_import.cli export-map --output "$OUTPUT"

if ! git diff --quiet -- "$OUTPUT"; then
    echo "→ Map data changed; committing and pushing."
    git add "$OUTPUT"
    git commit -m "Update map data ($(date +%Y-%m-%d))"
    git push
    echo "→ Done."
else
    echo "→ No changes to $OUTPUT — nothing to commit."
fi
