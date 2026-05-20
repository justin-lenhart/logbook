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

## 🟡 Up Next

### Airport Map / Leaflet

- [ ] Re-validate `export-map` end-to-end now that airport schema + IANA tz are in place
- [ ] Research Leaflet vs alternatives — evaluate WordPress plugin compatibility and embed options
- [ ] Decide GeoJSON hosting strategy (static file committed to repo? S3? WordPress media?)
- [ ] Build Leaflet (or equivalent) embed on WordPress blog
- [ ] Validate map renders correctly with real flight data
- [ ] Publish on blog

---

## 🔵 Later

### Legacy Logbook Import
*Important — deprioritized until map is complete*

- [ ] Analyze `misc/LEN2J-AnytimeLogbook2025.12.01.xlsx` — understand column structure
- [ ] Define field mapping from legacy format → Flights table (summary-style rows, not individual legs)
- [ ] Confirm aircraft/category mapping for pre-SkyWest types (H1, B300, etc.)
- [ ] **Cursor:** Implement legacy import mode

### Airtable Interfaces
*UI work, no code — build these in Airtable directly*

- [ ] Import review page — grouped by Import Batch, shows linked Flights/Trips/Duty Periods
- [ ] Flights view — browse all Flight records with key fields visible
- [ ] Trips view — browse all Trip records

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
