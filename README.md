# Logbook

A personal Part 121 logbook. It imports your **SkedPlus** trip exports into Airtable
(your real logbook), and keeps a public **flight map** and a set of **application
reference pages** up to date.

The whole thing is built around one habit: **drop your SkedPlus files in a folder,
run one command.** That's it. Everything below the Quick Start is reference material
you can ignore on a normal day.

---

## BLUF — Quick Start

You do this twice a month: once when the schedule drops (planned), and again after
you fly (actual).

**1. Drop your SkedPlus export files into the `inbox/` folder** (repo root).
   Files must be named `<seq>_<YYYYMMDD>_<PairingID>.txt` — e.g. `01_20260601_E3405.txt`.
   A matching `.csv` is optional.

**2. Open a terminal, activate the tool:**

```sh
cd logbook/logbook-tools
source .venv/bin/activate
```

**3. Run the one command you need:**

```sh
# After you've FLOWN the trips — writes flights + refreshes the map & app pages
logbook-import import-actual --role sic --operator skw --commit --update-all
```

```sh
# When the schedule DROPS — writes planned trips (no flights yet)
logbook-import import-planned --role sic --operator skw --commit
```

That's the whole job. Files are moved out of `inbox/` into `recorded/` automatically
once they import. Done.

> **Tip:** Drop `--commit` from any command to do a **dry run** first — it prints
> exactly what *would* be imported without touching Airtable. Worth a glance if a
> trip looks unusual.

---

## What it does

1. **Import planned trips** — when your monthly schedule drops, load the pairings as
   planned trips (planned block/credit, no flight rows yet).
2. **Import actual trips** — after you fly, load the flown legs as real flight rows.
3. **Publish** — refresh the [flight map](https://justin-lenhart.github.io/logbook/)
   and the airline/FAA [application reference pages](https://justin-lenhart.github.io/logbook/apps/summary.html).

Airtable is where you *view and analyze* everything. This tool only does the import
and publish steps — it never asks you questions and has no reporting mode.

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

Create `logbook-tools/.env` with your Airtable credentials (needed for `--commit`):

```sh
AIRTABLE_API_KEY=pat...your token...
AIRTABLE_BASE_ID=app...your base id...
```

See `.env.example` for the template. **After setup, you only ever need
`source .venv/bin/activate` once per terminal session.**

### The normal workflow

| When | Command |
|------|---------|
| Schedule drops | `logbook-import import-planned --role sic --operator skw --commit` |
| After you fly | `logbook-import import-actual --role sic --operator skw --commit --update-all` |

- `--role` is **required** (`sic` or `pic`).
- `--operator` defaults to `skw`, so it's optional — shown above for clarity.
- `--commit` writes to Airtable. **Without it, every command is a safe dry run.**
- `--update-all` (actual only) refreshes the map *and* the app pages and pushes them
  to GitHub Pages. See [Publishing](#publishing-map--app-pages) for the finer-grained flags.

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
├── inbox/                 # ← you drop SkedPlus exports here
└── recorded/
    ├── planned/           # import-planned moves files here
    └── actual/            # import-actual moves files here
```

File naming convention: `<seq>_<YYYYMMDD>_<PairingID>.<txt|csv>`
(e.g. `01_20260601_E3405.txt`). Anything not matching that pattern is ignored with a
warning, so it's safe to have other junk in `inbox/`.

### Publishing (map & app pages)

`--update-all` on an actual import is the shorthand most days. The pieces, if you
ever need them individually:

| Flag (on `import-actual`) | What it does |
|---|---|
| `--update-map` | Regenerate the flight map and push to GitHub Pages |
| `--update-apps` | Regenerate the airline/FAA app reference pages and push |
| `--update-all`  | Both of the above |

You can also publish **without** importing anything:

```sh
logbook-import export-map --update      # refresh just the map
logbook-import export-apps --update     # refresh just the app pages
```

GitHub Pages redeploys ~1 minute after the push. The map fetches its data with
`no-cache`, so a page reload picks up the new flights.

### Command reference

Everything else the CLI can do. You will rarely touch these.

| Command | Purpose |
|---|---|
| `import-actual` | Import flown legs as Flight rows *(your main command)* |
| `import-planned` | Import the schedule as planned Trips/Duty Periods |
| `export-map` | Regenerate `docs/map_data.geojson` (add `--update` to push) |
| `export-apps` | Regenerate `docs/apps/*.html` (`--page` to limit; `--update` to push) |
| `enrich-night` | Fill Night Time / Day & Night Landing on existing flights (`--commit`) |
| `backfill-passengers` | Re-derive the Passengers field from archived exports (`--commit`) |

Run any command with `--help` for its flags.

---

## The flight map

- Live map: **https://justin-lenhart.github.io/logbook/**
- It's a static Leaflet page served from `docs/`. `docs/map_data.geojson` is
  **generated — never hand-edit it.** Refresh it with `--update-map` (during an
  import) or `export-map --update`.
- The map is embedded inside the Airtable base as a custom block. That block lives in
  the separate **[`logbook-map`](https://github.com/justin-lenhart/logbook)** repo —
  it's just a thin iframe wrapper around the page above. You only touch that repo if
  you're changing the embed itself; day-to-day map updates happen here via the CLI.

---

## Reference & background

Day-to-day you don't need any of this. It's here so the context isn't lost.

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
  sunrise) and are assigned by **pairing**, not by calendar day. Run `enrich-night`
  to backfill any flights missing this data.

### Efficiency metrics (viewed in Airtable, not here)

There are no efficiency *commands* — the metrics live as formula fields and views in
Airtable. The ones worth watching to judge a trip:

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
├── recorded/               # processed exports land here (git-ignored)
│   ├── planned/
│   └── actual/
├── docs/                   # GitHub Pages site (the map + app pages)
│   ├── index.html          # Leaflet map
│   ├── map_data.geojson    # generated — do not edit
│   ├── apps/               # generated airline/FAA reference pages
│   └── *.md                # planning docs (Part 117, efficiency metrics)
└── logbook-tools/          # the CLI
    ├── src/logbook_import/ # source
    ├── scripts/            # one-off / maintenance scripts
    └── .env                # your Airtable credentials (git-ignored)
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
