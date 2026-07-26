# Logbook

A personal Part 121 logbook. It imports your **SkedPlus** trip exports into a
self-hosted **Grist** doc (your real logbook, on the home server), and keeps a
public **flight map** up to date. (It began life on Airtable; cutover to Grist
happened 2026-07-23 — Airtable survives only as a frozen pre-cutover backup.)

The whole thing is built around one habit: **drag your SkedPlus files into a
folder. That's it.** The synced folder auto-imports on the server — no terminal.
Everything below the Quick Start is reference material you can ignore on a
normal day.

---

## BLUF — Quick Start

You do this twice a month: once when the schedule drops (planned), and again after
you fly (actual).

**Drag the SkedPlus export pair (txt + csv) into the synced inbox folder on your
Mac** (Syncthing shares it with the server):

- schedule just dropped → the **`planned/`** subfolder
- trips flown → the **`actual/`** subfolder

Files must be named `<seq>_<YYYYMMDD>_<PairingID>.txt` — e.g. `01_20260601_E3405.txt`
(SkedPlus names them this way already). Within ~30 seconds the files vanish
(= imported into Grist) and land in `recorded/` on the server. If an import fails,
the files reappear in the **`failed/`** subfolder with an `import-log.txt`
explaining why. See [Automatic imports](#automatic-imports-server) for how it works.

**Manual fallback** (server terminal — same engine the watcher uses):

```sh
cd logbook/logbook-tools && source .venv/bin/activate

# After you've FLOWN the trips (files at inbox/ top level)
logbook-import import-actual --role sic --operator skw --commit

# When the schedule DROPS — writes planned trips (no flights yet)
logbook-import import-planned --role sic --operator skw --commit
```

> **Tip:** Drop `--commit` from any manual command to do a **dry run** first — it
> prints exactly what *would* be imported without writing to the logbook. Worth a
> glance if a trip looks unusual.

---

## What it does

1. **Import planned trips** — when your monthly schedule drops, load the pairings as
   planned trips (planned block/credit, no flight rows yet).
2. **Import actual trips** — after you fly, load the flown legs as real flight rows.
3. **Publish** — refresh the [flight map](https://justin-lenhart.github.io/logbook/).

You *view and analyze* everything in the Grist doc (`http://100.78.241.102:8484`,
Tailscale-only) and its embedded Metabase dashboards (see the `logbook-visualize`
repo). This tool only does the import and publish steps — it never asks you
questions and has no reporting mode.

---

## Detailed usage

### One-time setup

The tool is a Python CLI. You only set it up once.

```sh
cd logbook/logbook-tools
python3 -m venv .venv          # first time only
source .venv/bin/activate
pip install -e ".[dev]"        # first time only
```

Create `logbook-tools/.env` with the backend credentials (needed for `--commit`):

```sh
LOGBOOK_BACKEND=grist
GRIST_URL=http://100.78.241.102:8484
GRIST_API_KEY=...your key...
GRIST_DOC=...the live doc id...
```

See `.env.example` for the template. (`LOGBOOK_BACKEND=airtable` +
`AIRTABLE_API_KEY`/`AIRTABLE_BASE_ID` still selects the legacy backend — only
useful against the frozen pre-cutover base.) **After setup, you only ever need
`source .venv/bin/activate` once per terminal session.**

### The normal workflow (manual runs)

Day to day you don't run these — the [auto-importer](#automatic-imports-server)
does. For manual runs on the server:

| When | Command |
|------|---------|
| Schedule drops | `logbook-import import-planned --role sic --operator skw --commit` |
| After you fly | `logbook-import import-actual --role sic --operator skw --commit --update-map` |

- `--role` defaults to `sic` (`pic` when that day comes).
- `--operator` defaults to `skw`, so it's optional — shown above for clarity.
- `--commit` writes to the logbook. **Without it, every command is a safe dry run.**
- `--update-map` (actual only) refreshes the public flight map and pushes it to
  GitHub Pages. See [Publishing](#publishing-map--app-pages) for the finer-grained flags.

### Dry run first (optional)

Before committing, run the same command **without `--commit`** to preview:

```sh
logbook-import import-actual --role sic --operator skw
```

It prints every trip, duty period, and leg it would create, plus the current map
state. Nothing is written. Eyeball it against your trip report, then re-run with
`--commit`.

### Where files go

```
logbook/
├── inbox/                 # ← you drop SkedPlus exports here (manual runs scan the top level)
│   ├── planned/           #   auto-import watch folder — schedule-drop exports
│   ├── actual/            #   auto-import watch folder — flown-trip exports
│   └── failed/            #   auto-import quarantine (bad files + the import log)
└── recorded/
    ├── planned/           # import-planned moves files here
    └── actual/            # import-actual moves files here
```

File naming convention: `<seq>_<YYYYMMDD>_<PairingID>.<txt|csv>`
(e.g. `01_20260601_E3405.txt`). Anything not matching that pattern is ignored with a
warning, so it's safe to have other junk in `inbox/`.

### Automatic imports (server)

On the home server (mintbox) the two subfolders are watched by systemd path
units: drop a txt/csv export pair into **`inbox/planned/`** or **`inbox/actual/`**
and the matching import runs by itself with `--commit` — no terminal needed.
Syncthing shares `inbox/` with the Mac (folder id `logbook-inbox`), so the daily
habit is *drag the files into the right folder, walk away*. Processed files disappear
into `recorded/<mode>/` as usual; anything that fails lands in
`inbox/failed/<timestamp>-<mode>/` together with `import-log.txt`, which syncs
back to the Mac so you'll see it.

The pieces, all in this repo:

| Piece | Where |
|---|---|
| Watcher wrapper (settle delay, pair-wait, quarantine) | `scripts/process-inbox.sh` |
| systemd path + service units (×2 modes) | `deploy/systemd/` |
| Backend/credentials the auto-import uses | `logbook-tools/.env` (`LOGBOOK_BACKEND`, `GRIST_*`) |

Install (once, needs sudo):

```sh
sudo cp deploy/systemd/logbook-import-*.{path,service} /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now logbook-import-planned.path logbook-import-actual.path
```

Watch a run / debug: `journalctl -u logbook-import-actual.service -f`.
Auto-imports run with the default flags (`--role sic --operator skw`) and do
**not** push the map to GitHub Pages — run `logbook-import export-map --update`
(or an import with `--update-map`) when you want the public map refreshed.

> **Backend:** the importer writes to the live Grist doc (`GRIST_DOC` in
> `logbook-tools/.env`) — cutover from Airtable happened 2026-07-23. Airtable
> remains only as a frozen last-resort backup of pre-cutover data.

### Publishing (map & app pages)

| Flag (on `import-actual`) | What it does |
|---|---|
| `--update-map` | Regenerate the flight map and push to GitHub Pages |
| `--update-apps` | *(legacy, Airtable-only — skipped under Grist)* regenerate the app reference pages |
| `--update-all`  | Both of the above |

You can also publish **without** importing anything:

```sh
logbook-import export-map --update      # refresh just the map
```

(`export-apps` still reads Airtable and has not been ported — the Metabase
**Application Reference** dashboard in `logbook-visualize` replaced it.)

GitHub Pages redeploys ~1 minute after the push. The map fetches its data with
`no-cache`, so a page reload picks up the new flights.

### Command reference

Everything else the CLI can do. You will rarely touch these.

| Command | Purpose |
|---|---|
| `import-actual` | Import flown legs as Flight rows *(what the auto-importer runs)* |
| `import-planned` | Import the schedule as planned Trips/Duty Periods |
| `export-map` | Regenerate `docs/map_data.geojson` (add `--update` to push) |
| `export-apps` | *(legacy, Airtable-only)* regenerate `docs/apps/*.html` |
| `enrich-night` | *(legacy, Airtable-only)* backfill night data — Grist imports enrich inline |
| `backfill-passengers` | *(legacy, Airtable-only)* re-derive Passengers from archived exports |

Run any command with `--help` for its flags.

---

## The flight map

- Live map: **https://justin-lenhart.github.io/logbook/**
- It's a static Leaflet page served from `docs/`. `docs/map_data.geojson` is
  **generated — never hand-edit it.** Refresh it with `--update-map` (during an
  import) or `export-map --update`.
- The map is embedded in the Grist doc as its **Flight Map** page (a Custom-URL
  widget pointing at the page above). Day-to-day map updates happen here via the
  CLI — the embed just re-renders whatever is published.

---

## Reference & background

Day-to-day you don't need any of this. It's here so the context isn't lost.

### Grist doc pages (the live logbook UI)

The Grist `Logbook` doc (`http://100.78.241.102:8484`, Tailscale-only) carries these
pages (2026-07-23):

| Page | What it shows |
|------|---------------|
| Airports … Bugs_Features | Raw table views (one per table) |
| **Hours Dashboard** | Native Grist pivots: Category/Class × Position/Engine + career totals (kept for side-by-side comparison with Metabase; user may retire) |
| **Analytics** | Native Grist charts: block/credit by month, planned-v-actual, TAFB, trip pie, TCI (same retire-candidate status) |
| **Flights Logbook / Trips Log** | Curated grids, newest first |
| **Flight Map** | Custom-URL widget embedding the public Leaflet map |
| **Analytics (Metabase)** | Embedded Metabase **Daily Ops** dashboard (career + monthly tiles, trends, pivots) via its public link |
| **Application Reference** | Embedded Metabase **Application Reference** dashboard (per-aircraft totals, FAA 8710 matrix, class hours, currency recency) |
| **Trip Details** | Master-detail: pick a trip (newest-first grid) → trip card + its flights + its duty periods, linked by cursor |

The two Metabase embeds render the live dashboards from the `logbook-visualize`
stack (read-only 15-min sync of this doc); appearance edits made in Metabase
auto-reflect here. Embed URLs: `logbook-visualize/embed-urls.md`.

### How credit & times are handled

- **Times are converted to UTC on import.** SkedPlus reports local time at each
  airport; the importer looks up each airport's location and converts every
  out/in/report/release time to UTC before writing. This is why the Airports table
  must contain every airport you fly (with lat/lon).
- **Credit** is parsed straight from the SkedPlus export as the sum of leg credits.
  Note the **known gap**: split-duty (SDuty) and reposition (RDY/NMD) credit are *not*
  modeled, so for any trip containing those, **actual credit reads low** — treat
  planned credit as the source of truth there. (See efficiency metrics doc below.)
- **Night time & landings** follow FAA currency rules (1 hr after sunset → 1 hr before
  sunrise) and are assigned by **pairing**, not by calendar day. Grist imports
  compute this inline on every flight; the standalone `enrich-night` backfill is
  Airtable-legacy.

### Efficiency metrics (viewed in Grist/Metabase, not here)

There are no efficiency *commands* — the metrics live as formula columns and
dashboards in the Grist doc and Metabase. The ones worth watching to judge a trip:

- **Credit : Block ratio** — how favorable the rig is (anything > 1.0 is paid more
  than flown).
- **Credit per TAFB day** — the big one: pay earned per day away from home.
- **Block per TAFB day** — how hard the trip works you.

The full design (formulas, which need the new `Trips.TAFB` field) is in
[`docs/metrics-plan-efficiency-variance.md`](docs/metrics-plan-efficiency-variance.md).
TAFB import is implemented — `import-planned` writes `Trips.TAFB` from the SkedPlus header.

### Part 117 compliance (planned, not yet in the tool)

There is **no compliance command yet.** The research and implementation plan —
rolling 100h/28-day block, 60h/7-day FDP, rest checks, etc. — is written up in
[`docs/part117-compliance-plan.md`](docs/part117-compliance-plan.md). Nothing there is
user-facing today; it's the roadmap for a future `compliance-check` command.

---

## Repo layout

```
logbook/
├── inbox/                  # drop SkedPlus exports here (git-ignored)
│   ├── planned/            #   watched — auto-imports planned trips
│   ├── actual/             #   watched — auto-imports flown trips
│   └── failed/             #   quarantine for failed auto-imports
├── recorded/               # processed exports land here (git-ignored)
│   ├── planned/
│   └── actual/
├── deploy/systemd/         # path/service units for the auto-importer
├── scripts/                # process-inbox.sh (watcher), update-map.sh
├── docs/                   # GitHub Pages site (the map + app pages)
│   ├── index.html          # Leaflet map
│   ├── map_data.geojson    # generated — do not edit
│   ├── apps/               # generated airline/FAA reference pages
│   └── *.md                # planning docs (Part 117, efficiency metrics)
└── logbook-tools/          # the CLI
    ├── src/logbook_import/ # source
    ├── scripts/            # one-off / maintenance scripts
    └── .env                # backend credentials (git-ignored):
                            #   LOGBOOK_BACKEND=grist|airtable + GRIST_*/AIRTABLE_*
```

Operational data (`inbox/`, `recorded/`, `backups/`, `misc/`, `.env`) is git-ignored —
it contains crew names, tail numbers, and credentials and never leaves your machine.

---

## Roadmap

- **Config file / `--std` flag** — collapse `--role sic --operator skw` into a stored
  default so the daily command becomes just `logbook-import import-actual --std`.
- **`compliance-check` command** — Part 117 rolling limits (see plan doc).
- **Flask web app** — eventually wrap this whole flow in a GUI so a non-coding pilot
  never touches a terminal. The import/publish logic here is the backend for that.
