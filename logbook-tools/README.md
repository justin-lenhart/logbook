# logbook-tools

CLI for importing SkedPlus pairing exports into Airtable and maintaining the Leaflet flight map.

## Setup

```sh
cd logbook-tools
python3 -m venv .venv        # first time only
source .venv/bin/activate
pip install -e ".[dev]"      # first time only
```

`logbook-import` is the entry point (defined in `pyproject.toml`).

## Commands

### `import-actual`

Imports flown legs from SkedPlus exports as Flight rows in Airtable.

```sh
logbook-import import-actual --role <pic|sic> [--operator skw] [--dry-run | --commit] [--update-map]
```

- Default (no flags): dry run.
- `--commit`: writes to Airtable and moves processed files to `recorded/actual/`.
- `--update-map`: after a successful `--commit`, regenerates `docs/map_data.geojson` and pushes to GitHub Pages. No-op in dry-run mode.
- Both dry-run and commit runs print a map data summary at the end (current airport/route counts).

### `import-planned`

Imports planned pairing data (Trip and Duty Period rows, no Flight rows).

```sh
logbook-import import-planned --role <pic|sic> [--operator skw] [--dry-run | --commit]
```

### `export-map`

Regenerates `docs/map_data.geojson` from current Airtable flight data.

```sh
logbook-import export-map [--output PATH] [--update]
```

- Default output: `docs/map_data.geojson` in the repo root.
- `--update`: also commits the file and pushes to GitHub Pages (triggers a redeploy in ~1 min).

### `enrich-night`

Computes Night Time, Day Landing, and Night Landing for existing Flight records that haven't been enriched yet.

```sh
logbook-import enrich-night [--commit]
```

- Default: dry run, prints what would be written.
- `--commit`: writes to Airtable.

## Inbox / recorded layout

```
logbook/
├── inbox/          # Drop SkedPlus exports here (e.g. 01_20260501_AB1234.txt)
└── recorded/
    ├── planned/    # Files processed by import-planned
    └── actual/     # Files processed by import-actual
```

File naming convention: `<seq>_<YYYYMMDD>_<PairingID>.<txt|csv>`

## Known limitations

**Night time on short overnight legs** — night calculation uses civil twilight end at the origin (UTC departure date) and civil twilight begin at the destination (UTC arrival date). For legs departing just before local midnight and arriving just after, the UTC dates may coincide and slightly underestimate the night window. Rare in SkyWest regional operations.
