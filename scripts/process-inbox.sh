#!/usr/bin/env bash
# Auto-import SkedPlus exports dropped into inbox/planned or inbox/actual.
#
# Invoked by the logbook-import-<mode>.path systemd units whenever the watched
# directory becomes non-empty (see deploy/systemd/). Can also be run by hand:
#
#   scripts/process-inbox.sh planned
#   scripts/process-inbox.sh actual
#
# Behaviour:
#   - waits briefly so a txt/csv pair syncing in from the Mac arrives complete
#   - runs the importer with --commit against every pairing set in the folder
#   - on success the CLI moves the source files to recorded/<mode>/
#   - on failure (or for files the importer doesn't recognise) everything left
#     in the folder is quarantined to inbox/failed/<timestamp>-<mode>/ together
#     with the full import log — the watched folder is ALWAYS left empty so the
#     path unit cannot re-trigger in a loop
#
# The backend (grist/airtable) and Grist doc come from logbook-tools/.env.

set -uo pipefail

MODE="${1:?usage: process-inbox.sh <planned|actual>}"
case "$MODE" in planned|actual) ;; *) echo "unknown mode: $MODE" >&2; exit 2 ;; esac

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WATCH_DIR="$REPO_ROOT/inbox/$MODE"
FAILED_ROOT="$REPO_ROOT/inbox/failed"
PYTHON="$REPO_ROOT/logbook-tools/.venv/bin/python"
LOCK_FILE="$REPO_ROOT/inbox/.import.lock"

PAIR_WAIT_SECS=120   # max time to wait for a txt/csv pair to finish syncing
SETTLE_SECS=10       # initial pause after the trigger fires

# Serialise planned/actual runs — both units may fire at once.
exec 9>"$LOCK_FILE"
flock 9

shopt -s nullglob

matched_files() {
    # Regular files that look like SkedPlus exports: <prefix>_<date>_<pairing>.<txt|csv>
    find "$WATCH_DIR" -maxdepth 1 -type f -regextype posix-extended \
        -iregex '.*/[0-9]+_[0-9]{8}_[A-Z0-9]+\.(txt|csv)' 2>/dev/null
}

visible_files() {
    # Everything except Syncthing temp/metadata files (still syncing / internal).
    find "$WATCH_DIR" -maxdepth 1 -type f \
        ! -name '.syncthing*' ! -name '~syncthing~*' ! -name '.stfolder*' 2>/dev/null
}

if [ -z "$(visible_files)" ]; then
    echo "Nothing in $WATCH_DIR — exiting."
    exit 0
fi

sleep "$SETTLE_SECS"

# Wait for every txt to have its csv (and vice versa) — Syncthing delivers the
# two files independently. Give up after PAIR_WAIT_SECS and import what's there;
# the importer copes with a missing csv (warns) or missing txt (skips).
waited=0
while [ "$waited" -lt "$PAIR_WAIT_SECS" ]; do
    incomplete=0
    while IFS= read -r f; do
        base="${f%.*}"; ext="${f##*.}"
        case "${ext,,}" in
            txt) [ -f "$base.csv" ] || [ -f "$base.CSV" ] || incomplete=1 ;;
            csv) [ -f "$base.txt" ] || [ -f "$base.TXT" ] || incomplete=1 ;;
        esac
    done < <(matched_files)
    [ "$incomplete" -eq 0 ] && break
    sleep 10; waited=$((waited + 10))
done
[ "${incomplete:-0}" -ne 0 ] && echo "WARN: proceeding with incomplete txt/csv pair(s) after ${PAIR_WAIT_SECS}s"

STAMP="$(date +%Y%m%d-%H%M%S)"
LOG="$(mktemp)"
trap 'rm -f "$LOG"' EXIT

# Actual imports also regenerate + publish the public flight map (GitHub Pages).
# Planned imports write no flown legs, so the map can't change — skip the push.
EXTRA_ARGS=()
[ "$MODE" = actual ] && EXTRA_ARGS+=(--update-map)

echo "=== logbook auto-import: mode=$MODE $(date -Is) ==="
"$PYTHON" -m logbook_import.cli "import-$MODE" --commit --inbox "$WATCH_DIR" "${EXTRA_ARGS[@]}" 2>&1 | tee "$LOG"
status=${PIPESTATUS[0]}

# macOS AppleDouble sidecars (._foo) ride along with files copied from a Mac —
# pure metadata junk, delete rather than quarantine.
find "$WATCH_DIR" -maxdepth 1 -type f -name '._*' -delete

# Quarantine anything still sitting in the watched folder (failed import,
# unrecognised files, or a lone csv the importer skipped). The folder must end
# up empty or the path unit re-triggers forever.
leftovers=( "$(visible_files)" )
if [ -n "${leftovers[0]}" ]; then
    DEST="$FAILED_ROOT/$STAMP-$MODE"
    mkdir -p "$DEST"
    visible_files | while IFS= read -r f; do mv -- "$f" "$DEST/"; done
    cp "$LOG" "$DEST/import-log.txt"
    echo "Quarantined leftover file(s) to inbox/failed/$STAMP-$MODE/ (see import-log.txt)"
fi

if [ "$status" -ne 0 ]; then
    if [ -d "$FAILED_ROOT/$STAMP-$MODE" ]; then
        echo "Import FAILED (exit $status) — files moved to inbox/failed/$STAMP-$MODE/" >&2
    else
        # Watch dir emptied = every pairing committed; a post-import step
        # (map regen/publish) failed. Data is in Grist — rerun the map with:
        #   logbook-import export-map --update
        echo "Import COMMITTED but a post-import step failed (exit $status) — likely the map publish. Run 'export-map --update' manually." >&2
    fi
    exit "$status"
fi

echo "=== import complete ==="
