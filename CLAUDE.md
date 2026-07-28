# logbook — agent guide

Pilot logbook system. Imports SkedPlus schedule exports into the datastore, keeps a
public Leaflet flight map, and (legacy) generates airline/FAA application pages. This
file is the entry point for making changes; deeper domain detail lives in
[`AGENTRULES.md`](AGENTRULES.md) and [`docs/`](docs/) — read the specific section named
below before touching that area.

## Repo ecosystem (three repos, one system)
Full living status: `homelab/TODO.md` (private repo).
- **logbook** (this repo, public) — canonical code on `main`. The importer + systemd
  watcher (auto-imports to the live Grist doc), the flight map, and reference docs.
- **logbook-visualize** (public) — Metabase frontend over a **read-only** SQLite sync of
  the Grist doc. 3 dashboards / 58 verified cards.
- **homelab** (private) — infra + docs hub for the mintbox server.
- `logbook-grist` was a *branch* here (Grist migration), merged to `main` 2026-07-26 — not
  a separate repo. The empty GitHub repo of that name is defunct.

## Golden rules (read before any change)
1. **This repo WRITES to Grist** — Grist is canonical (since the 2026-07-23 cutover).
   Do not confuse with `logbook-visualize`, which is *strictly read-only* toward Grist.
   Opposite rules, different repos.
2. **Never re-import pre-Jul-2026 source files.** Import keys were normalized once; a
   re-import would create duplicate Trips/Flights. See `AGENTRULES.md` → *Stable Keys* and
   `src/logbook_import/keys.py` (SkyWest pairing revision-suffix heuristic).
3. **Commands are dry-run by default.** Only `--commit` writes to the backend. Preserve
   this — never make a command write without an explicit `--commit`.
4. **Never add/rename Grist columns unprompted.** Schema changes are USER decisions (they
   also break `logbook-visualize` cards keyed on column names). Rebuild derived values as
   Grist formulas, not new stored columns, unless asked.
5. **Tests must pass and stay green.** Add/adjust tests with every behavior change.

## Architecture & data flow
```
SkedPlus .txt (+optional .csv)           systemd path unit fires
  dropped in inbox/{planned,actual}  ──►  scripts/process-inbox.sh  ──►  logbook-import
                                                                          writes Grist
  files moved to recorded/{planned,actual}   ◄── on success   ├─ actual  → import-actual
  failures quarantined to inbox/failed/                        └─ planned → import-planned
                                             actual imports also --update-map ─►
                                             docs/map_data.geojson ─► GitHub Pages (Leaflet)
```
- **Times** are stored in **UTC**. SkedPlus reports local time; `time_utils.py` uses
  `timezonefinder` (airport lat/lon → tz) to convert every out/in/report/release time to
  UTC on import. The Airports table must contain every airport flown, with lat/lon.
- **Night time & landings** are computed inline per pairing (not by calendar day) via
  `astral` in `night_enrichment.py` (FAA civil-twilight rule).
- **Deadheads** are excluded from flight-time sums and from the map (`not deadhead AND
  (PIC>0 OR SIC>0)`).
- **Stable keys** (`keys.py`): Trip / Duty Period / Import Flight keys make imports
  idempotent (upsert, not append). See `AGENTRULES.md` → *Stable Keys*.

## Code map — `logbook-tools/src/logbook_import/`
- **Backend switch:** `backend.py` — `active_backend()` reads `LOGBOOK_BACKEND` from
  `logbook-tools/.env` (`grist` in the deployed env; code default is still `airtable`).
- **Grist backend (ACTIVE):** `grist_client`, `grist_settings`, `grist_fields`,
  `grist_mapper`, `grist_sync`, `grist_airports`, `grist_map`.
- **Airtable backend (LEGACY, frozen):** `airtable_*` mirror modules — do not extend;
  kept for the frozen pre-cutover backup only.
- **Parsers:** `parsers/skedplus_txt.py`, `skedplus_csv.py`, `merge.py` (txt is required,
  csv optional; merge reconciles them).
- **Domain:** `models.py`, `config.py` (paths: `TOOLS_ROOT`, `INBOX_DIR`, `RECORDED_DIR`),
  `keys.py`, `leg_classifier.py`, `night_enrichment.py`, `time_utils.py`, `import_planner.py`.
- **App pages (LEGACY):** `app_families.py`, `app_report.py` — superseded by the Metabase
  Application Reference dashboard (see `docs/application-pages-setup.md`).
- **Map:** `airport_map.py`, `grist_map.py`.
- **CLI:** `cli.py` (Click). Entry point `logbook-import` (`pyproject.toml [project.scripts]`).

## Commands
All import commands default to dry-run; add `--commit` to write.
- `import-actual --role {pic|sic} [--operator skw] [--commit] [--update-map] [--update-apps]`
  — flown legs → Flight rows (+ actuals roll up to Trips/Duty Periods).
- `import-planned --role {pic|sic} [--commit]` — Trip + Duty Period rows, no flights;
  writes `Trips.TAFB` from the SkedPlus header.
- `export-map [--output PATH] [--update]` — regenerate `docs/map_data.geojson`; `--update`
  commits + pushes (GitHub Pages).
- `export-apps` / `enrich-night` / `backfill-passengers` — **legacy, Airtable-only.**

## Dev / test
- Package is `uv`-managed (`logbook-tools/uv.lock`, `.venv` present). Python ≥ 3.11.
- Run tests from `logbook-tools/`: **`uv run pytest`** (or activate `.venv` and run `pytest`).
  `pythonpath=src`, `testpaths=tests`. Coverage spans parsers, mappers, keys, night, time,
  cli, config (17 test modules).
- Deps: `click`, `python-dotenv`, `pyairtable` (legacy), `astral`, `timezonefinder`,
  `openpyxl`; dev: `pytest`.

## Config & deployment
- **Creds:** `logbook-tools/.env` (gitignored) — `LOGBOOK_BACKEND=grist`, `GRIST_URL`,
  `GRIST_API_KEY`, `GRIST_DOC` (legacy `AIRTABLE_*`). Template: `logbook-tools/.env.example`.
- **Grist canonical URL:** `http://100.78.241.102:8484` (Tailscale-only; other hostnames
  rejected).
- **Deployed on mintbox:** `deploy/systemd/logbook-import-{planned,actual}.{path,service}`
  watch `inbox/{planned,actual}` and run `scripts/process-inbox.sh` (settle delay,
  txt/csv pair-wait, `flock`, always empties the watch dir). Transport: Syncthing
  (Mac↔mintbox). `sudo` install steps are the user's.

## Making changes — checklist
1. Read the relevant `AGENTRULES.md` section (Stable Keys, Parsing Rules, Safety Rules,
   Core Data Philosophy) before editing that area.
2. Grist backend only — don't extend `airtable_*`. Keep dry-run default.
3. Update/add tests; `uv run pytest` green before committing.
4. Keep docs honest: if behavior changes, update `README.md` and the relevant `docs/*.md`;
   cross-repo status lives in `homelab/TODO.md`.
5. Branch from `main`; commit/push only when asked. `distribute` / `enhanced-map` branches
   are deprecated — never build on them.

## Deeper references
- `AGENTRULES.md` — architecture, data philosophy, stable keys, parsing rules, aircraft
  philosophy, CLI philosophy, git/worktree + safety rules.
- `README.md` — BLUF quickstart, detailed usage, the flight map, repo layout.
- `docs/part117-compliance-plan.md` — Part 117 regulatory reference (analytics ship in the
  Metabase Trip Efficiency & Duty Legality dashboard; exact Table A/B limits are blocked on
  local report time — `Airports.UTC_Offset` is all zeros).
- `docs/metrics-plan-efficiency-variance.md`, `docs/historical-logbook-import.md`.
