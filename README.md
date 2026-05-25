# logbook

Personal aviation logbook backed by Airtable, with a Leaflet flight map published to GitHub Pages.

## Repo structure

```
logbook/
├── docs/                   # GitHub Pages site
│   ├── index.html          # Leaflet map
│   └── map_data.geojson    # Generated — do not edit by hand
└── logbook-tools/          # CLI for importing flights and updating the map
    ├── inbox/              # Drop SkedPlus export files here before importing
    ├── recorded/           # Processed files are moved here after import
    └── src/logbook_import/ # CLI source
```

## Map

The flight map lives at https://justin-lenhart.github.io/logbook/ and is embedded in the Airtable base as a custom block (see the `logbook-map` repo).

`docs/map_data.geojson` is a static file — the map only reflects data up to the last time it was regenerated and pushed. Use `export-map` or `import-actual --update-map` to refresh it (see below).

## CLI setup

```sh
cd logbook-tools
python3 -m venv .venv        # first time only
source .venv/bin/activate
pip install -e ".[dev]"      # first time only
```

After that, `logbook-import` is available while the venv is active.

## Commands

### Import flights

Drop SkedPlus `.txt` (and optionally `.csv`) export files into `inbox/`, then:

```sh
# Dry run — preview what will be imported, show current map state
logbook-import import-actual --role pic

# Commit to Airtable
logbook-import import-actual --role pic --commit

# Commit and update the map in one step
logbook-import import-actual --role pic --commit --update-map
```

Both dry-run and commit outputs include a map data summary (airport count, route count, any missing airports). In dry-run, the map is never written or pushed.

### Update the map without importing

```sh
# Regenerate map_data.geojson locally (inspect before pushing)
logbook-import export-map

# Regenerate, commit, and push to GitHub Pages
logbook-import export-map --update
```

GitHub Pages redeploys in ~1 minute after a push. The map fetches the GeoJSON with `cache: "no-cache"` so it picks up the new data on the next page load.

### Other commands

```sh
# Import planned pairing data (no Flight rows)
logbook-import import-planned --role pic --commit

# Compute and write Night Time, Day Landing, Night Landing
logbook-import enrich-night --commit
```

## Map pipeline detail

`export-map` reads every non-deadhead flight with PIC or SIC time from the Airtable Flights table, resolves the linked Departure/Arrival airport records to IATA codes, counts route frequencies, and writes a GeoJSON FeatureCollection with:

- **Point** features for each airport visited
- **LineString** features for each unique route, with a `count` property used to weight line thickness on the map
