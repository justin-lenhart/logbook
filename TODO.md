# Logbook Project — TODO

High-level milestones live in Things 3 → 🪵 Logbook Workflow 📋.
This file is the source of truth for implementation-level tasks.
Keep completed items — this is a historical record, not a scratchpad.

---

## ✅ Completed

- [x] Python package structure (`src/logbook_import/`, `pyproject.toml`, `.venv`)
- [x] SkedPlus `.txt` parser
- [x] SkedPlus `.csv` parser
- [x] Parser merge logic (txt is primary source; csv enriches aircraft/type info)
- [x] Stable key generation (Trip Key, Duty Period Key, Import Flight Key)
- [x] Leg classifier (deadhead detection, RDY/NMD recognized as non-flight duty events)
- [x] Import planner (planned vs actual mode, PIC/SIC role handling)
- [x] Dry-run output formatter
- [x] CLI — `import-planned` and `import-actual` subcommands
- [x] Airtable upsert write path — `--commit` validated in production
- [x] File archival on commit (`inbox/` → `recorded/`)
- [x] Airport data seeded in Airtable (OurAirports CSV, filtered to large + medium airports)
- [x] `airport_map.py` — `resolve_airports()`, `build_geojson()` written by Cursor
- [x] `airtable_airports.py` — `fetch_airport_index()` written by Cursor
- [x] `export-map` CLI subcommand written by Cursor
- [x] `tests/test_airport_map.py` written by Cursor

### Airport Schema Fix
- [x] Renamed `"Imported table"` → `"Airports"` in Airtable
- [x] Verified live Airtable schema via Airtable MCP; updated airport constants in `airtable_fields.py` to match
  (`IATA`, `Airport Name`, `Municipality`, `Country`, `Latitude`, `Longitude`)

### Night Time + Landing Enrichment
- [x] Added `astral>=3.2` dependency
- [x] Created `night_enrichment.py` with `civil_twilight_times()` and `compute_night_data()`
- [x] Implemented `enrich-night` CLI subcommand
  - Dry-run by default; `--commit` writes to Airtable
  - Idempotent — skips records where Night Time is already populated
  - Establishes pairing-level leg numbering from Import Flight Key
- [x] Updated `import-actual` to write Night Time / Day Landing / Night Landing at commit time
- [x] 5 unit tests in `tests/test_night_enrichment.py` — all passing
- [x] Known limitations note added to `README.md`
- [x] **TODO in code:** Confirm SkyWest takeoff credit rule. Currently assumes takeoffs alternate
      on the same odd/even leg pattern as landings (PIC=odd, SIC=even). Add an explicit
      check against the FOM and update `night_enrichment.compute_night_data()` if different.

### Timezone Correctness (critical fix discovered during enrich-night validation)
*Discovered: SkedPlus exports each leg in its own airport's local time. Previously the importer
stored these as naive datetimes, which Airtable then interpreted as UTC — every flight's times
were off by the airport's UTC offset. Caused incorrect night/landing classification.*

- [x] Added `timezonefinder>=6.5` dependency
- [x] `fetch_airport_index()` now populates IANA timezone (`tz`) per airport from lat/lon
- [x] `_to_utc()` helper in `import_planner.py` — converts local times to UTC using origin/dest
      IANA timezones via `zoneinfo`
- [x] `build_import_plan()` / `build_plans_for_exports()` accept `airport_index` and convert
      leg times to UTC at parse time
- [x] Handles cross-midnight legs (if `in_utc < out_utc` → bump arrival by one day)
- [x] CLI loads airport index up front before planning; graceful fallback for dry-run when
      Airtable unreachable
- [x] `AirtableImporter` accepts pre-loaded `airport_index` (avoids double-fetch)
- [x] Wiped Flights table and re-imported all three pairings (E3058E, E3109E, E7748);
      verified UTC times match local-time + offset for all 10 legs of E3058E

---

### Airport Map / Leaflet — completed
- [x] Re-validated `export-map` against live Airtable data (post-schema-fix, post-timezone-fix)
- [x] Hosting strategy chosen: static GeoJSON committed to repo under `docs/`,
      published via GitHub Pages from `justin-lenhart/logbook` (free, public)
- [x] Built `docs/index.html` — vanilla Leaflet 1.9.4 via CDN, OSM tiles,
      auto-fit bounds, click popups, route weight scaled by visit count
- [x] Wrote `scripts/update-map.sh` — runs `export-map`, diffs the geojson,
      commits + pushes only on change. Status line warns users of the
      ~30s Airtable query. Validated both branches (changed / no-change)
- [x] First commit pushed to GH; Pages enabled from `main` / `/docs`
- [x] Validated map renders at https://justin-lenhart.github.io/logbook/
- [x] Cross-cutting: added `.gitignore` excluding operational data
      (`inbox/`, `recorded/`, `sampleDataStorage/`, `misc/`, `.env`, editor state)
- [x] **Equipment Family cleanup** — removed dead defensive `_base_has_field`
      check from `cli.py` (field exists; saves one API call per commit)
- [x] **Cross Country Time** — now auto-written to every non-deadhead flight
      at import time (`block_hours` mirrored to `Cross Country Time` field)

---

## 🟡 Up Next

### Embed the map on Justin's WordPress.com blog
*Will be handled by a separate Claude agent — handoff prompt below in conversation history*

- [ ] Connect the WordPress.com MCP to Claude (Justin)
- [ ] Identify the target WordPress.com site + plan tier
- [ ] Pick embed strategy (iframe / plugin / fallback) based on plan capabilities
- [ ] Publish the page with the embedded map
- [ ] Validate from a fresh browser (incognito) that the map renders inside WordPress

### Make manually / form-entered Flight records show up on the map
*Today: `export-map` pulls Flights from Airtable using `Departure Airport` and
`Arrival Airport` string fields.  Records added through Airtable UI or a form
may or may not satisfy that contract — depends on how the form is set up.
Worth confirming what currently happens and closing any gaps.*

Open questions before coding:
- Does the user enter airports as IATA strings, or pick from a linked-record
  field?  (`export-map` currently expects strings.)
- Do form-entered records have Out/In Time?  If yes, in what timezone format —
  are they local or UTC?  (Different fix path depending on the answer.)
- Should night/landing enrichment be triggered for manual entries too, or only
  for SkedPlus-imported ones?

Candidate approaches (pick after answering the questions):
- **Airtable-side:** automation/formula that auto-populates derived fields
  (linked airport record, UTC times, night/landing) on record create/update —
  consistent with the AGENTRULES "Airtable handles visualization + manual entry"
  philosophy
- **Python-side:** small `enrich-manual` CLI subcommand that scans for records
  missing derived fields and fills them in (sibling to `enrich-night`)
- **Hybrid:** Airtable form normalizes inputs, Python handles UTC + night math

---

## 🔵 Later

### Legacy Logbook Import
*~1500 hours pre-SkyWest across multiple aircraft types. Goal: one summary row per aircraft
type in the Flights table (not individual legs). `Legacy Summary` checkbox already exists
on the Flights schema.*

Source data: `misc/LEN2J-AnytimeLogbook2025.12.01.xlsx`

Three implementation options (decided in conversation 2026-05-23 — pick one before starting):

**Option A — Manual Airtable entry**
Manually create one Flights record per aircraft type directly in Airtable.
- Pro: zero code, immediate, full field control
- Con: tedious; no auditability or re-run path; error-prone for totals

**Option B — Python script (recommended for this repo)**
Script reads the Excel, aggregates by aircraft type, writes one Airtable record per type.
Could be extended to accept ForeFlight or LogTen Pro CSV exports — making it useful
for other pilots using this logbook system.
- Pro: reproducible, auditable, expandable to other formats
- Con: one-time dev effort; requires column mapping from legacy format

**Option C — Claude/AI agent**
Feed the Excel to a Claude agent with Airtable MCP access; agent reviews and writes records.
- Pro: handles messy/unstructured data; no code needed
- Con: less transparent; harder to reproduce or audit; potential for silent errors

Tasks (pending option choice):
- [ ] Analyze `misc/LEN2J-AnytimeLogbook2025.12.01.xlsx` — column structure, aircraft types, date range
- [ ] Define field mapping from legacy columns → Flights table fields
- [ ] Confirm Aircraft table entries exist for pre-SkyWest types (H1, B300, etc.)
- [ ] Implement chosen import path

### Airtable Interfaces
*UI work, no code — build these in Airtable directly*

- [ ] Import review page — grouped by Import Batch, shows linked Flights/Trips/Duty Periods
- [ ] Flights view — browse all Flight records with key fields visible
- [ ] Trips view — browse all Trip records

### CLI polish
*Quality-of-life improvements for day-to-day use*

- [ ] **Config file support** — add a `.logbook.json` (or similar) in the project root that
      stores per-pilot defaults so the common invocation shrinks to just
      `logbook-import import-actual --commit`. Proposed keys:
      ```json
      { "role": "sic", "operator": "skw", "type": "cl65" }
      ```
      CLI reads the file on startup and uses values as flag defaults, overridable at runtime.
      `type` would gate a new `--type` flag (aircraft family override, not yet implemented).
- [ ] **`--help` text completeness** — audit every subcommand; ensure flag descriptions,
      value choices, and default behavior are clearly documented in Click decorators so
      `logbook-import import-actual --help` is self-contained without needing the README.

### Special Category expansions
- [ ] **Ferry autodetect** — add `"Ferry"` to `Flight.Special Category` options in Airtable,
      then detect it in the parser: a leg is a Ferry if `leg.crew.flight_attendant is None`
      (no FA listed in the SkedPlus crew section). Combine with SDuty/Reposition in the
      `special_categories` list — not mutually exclusive.

### Loose ends / cleanup
*Not blocking — pick up when convenient*

- [ ] Decide fate of unused `UTC Offset` column on Airports (now superseded by IANA tz
      computed from lat/lon at index-load time). Keep, delete, or repurpose.
- [ ] Decide fate of unused `F_AIRPORT_TYPE`, `F_AIRPORT_ICAO`, `F_AIRPORT_ELEVATION`,
      `F_AIRPORT_UTC_OFFSET` constants in `airtable_fields.py` — referenced nowhere
- [ ] Fix pre-existing `test_build_geojson_structure` assertion (`== 4` should be `== 3`
      for "2 points + 1 line"). Failure predates this work.
- [ ] Add inbox fixture files (or refactor tests) so `test_build_import_batch_from_pairing`,
      `test_discover_inbox_pairings`, `test_skedplus_*`, `test_import_planner_*`, and
      `test_merge_attaches_aircraft_type` pass in clean checkouts. All currently require
      pairing files in `/Users/justinlenhart/Developer/logbook/inbox/` that don't exist
      in dev environment.
- [ ] Confirm/correct takeoff credit rule (see Night Enrichment completed section above)

---

## 🚫 Shelved / Deferred

- **`airport-import` CLI command** — Airtable CSV import is sufficient; airport data rarely changes; may never be needed
- **`currency-report` CLI** — Airtable handles visualization; import CLI is for import only
- **Instrument time / approach CLI prompts** — Airtable UI workflow is the right tool; no CLI needed
- **`scripts/seed_airports.py`** — redundant now that Airtable import was done manually; can be deleted
