# logbook-tools

The `logbook-import` CLI: imports SkedPlus pairing exports into Airtable and maintains
the Leaflet flight map + application reference pages.

**For day-to-day operator usage, read the [repo README](../README.md).** This file is
the developer/CLI reference.

## Setup

```sh
cd logbook-tools
python3 -m venv .venv          # first time only
source .venv/bin/activate
pip install -e ".[dev]"        # first time only
```

`logbook-import` is the entry point (`pyproject.toml` → `logbook_import.cli:main`).
Requires Python ≥ 3.11 and a `.env` with `AIRTABLE_API_KEY` / `AIRTABLE_BASE_ID`
(see `.env.example`).

## Commands

All import commands default to a **dry run**; pass `--commit` to write to Airtable.
`--dry-run` and `--commit` are mutually exclusive.

| Command | Key flags | Notes |
|---|---|---|
| `import-actual` | `--role {pic\|sic}` (req), `--operator skw`, `--commit`, `--update-map`, `--update-apps`, `--update-all` | Flown legs → Flight rows. `--update-all` = map + apps. |
| `import-planned` | `--role {pic\|sic}` (req), `--operator skw`, `--commit` | Trip + Duty Period rows, no flights. |
| `export-map` | `--output PATH`, `--update` | Regenerate `docs/map_data.geojson`; `--update` commits + pushes. |
| `export-apps` | `--output DIR`, `--page {swa\|ual\|faa\|summary}`, `--update` | Regenerate `docs/apps/*.html`; `--page` repeatable. |
| `enrich-night` | `--commit` | Backfill Night Time, Day/Night Landing on existing flights. |
| `backfill-passengers` | `--source {actual\|planned}`, `--commit` | Re-derive Passengers from archived exports. |

Run any command with `--help` for full details.

## Inbox / recorded layout

Both live at the **repo root** (`config.py`: `INBOX_DIR`, `RECORDED_DIR`), not inside
`logbook-tools/`:

```
logbook/
├── inbox/              # drop SkedPlus exports here
└── recorded/
    ├── planned/        # files processed by import-planned
    └── actual/         # files processed by import-actual
```

File naming convention: `<seq>_<YYYYMMDD>_<PairingID>.<txt|csv>` (e.g.
`01_20260601_E3405.txt`). The `.csv` is optional; the `.txt` is required.

## Layout

```
logbook-tools/
├── src/logbook_import/     # the package (importable as logbook_import)
│   ├── cli.py              # all CLI commands
│   ├── parsers/            # SkedPlus txt/csv parsing + merge
│   └── ...                 # import_planner, airtable_sync, airport_map, etc.
├── scripts/                # one-off / maintenance scripts (not part of the CLI)
└── tests/                  # pytest suite
```

Run tests with `pytest` from `logbook-tools/`.

## Known limitations

**Night time on short overnight legs** — night calculation uses civil twilight end at
the origin (UTC departure date) and civil twilight begin at the destination (UTC
arrival date). For legs departing just before local midnight and arriving just after,
the UTC dates may coincide and slightly underestimate the night window. Rare in
SkyWest regional operations.

**Split-duty / reposition credit** — SDuty and RDY/NMD credit are not modeled, so
actual credit reads low on trips containing them. Treat planned credit as
authoritative for those. See `docs/metrics-plan-efficiency-variance.md`.
