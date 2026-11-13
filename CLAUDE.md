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
- **homelab** (private) — infra + docs hub for the crushbox server.
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

Grist ──► export-profile ──► exports/ ──► ~/Logbook-Outbox ─ Syncthing ─► Mac
            ▲
            └─ one click: logbook-export.service (Tailscale-only, read-only),
               as a Grist custom widget or a homepage link
```
- **Times** are stored in **UTC**. SkedPlus reports local time; `time_utils.py` uses
  `timezonefinder` (airport lat/lon → tz) to convert every out/in/report/release time to
  UTC on import. The Airports table must contain every airport flown, with lat/lon.
- **Night time & landings** are computed inline per pairing (not by calendar day) via
  `astral` in `night_enrichment.py` (FAA civil-twilight rule).
- **Deadheads** are excluded from flight-time sums and from the map (`not deadhead AND
  (PIC>0 OR SIC>0)`). A deadhead row carries no Aircraft link, no Flight_Position, and
  zero in every time and landing column (night included) — the importer enforces this.
- **Cross-country** (`cross_country.py`) follows 14 CFR 61.1: a leg logs its block time as
  cross-country only when the destination is more than 50 nm straight-line from the
  departure airport; air returns and deadheads log 0. Pre-2026 rows keep their legacy values.
- **Row timestamps** are Grist trigger formulas, not importer fields: `Flights.Created`
  fills with `NOW()` when a row is added, `Flights.Edited` on any later edit (manual or
  import). `Record_Status` is a legacy Airtable field and is not written.
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
- **Export profiles (read-only):** `profile_data.py` (`Leg`, `load_legs`, predicates,
  aggregators), `profiles.py` (per-target `Profile`/`Section` specs, `pilot.toml`),
  `profile_render.py` (print HTML + certified log pages), `profile_export.py`
  (`build_export` — one export run, shared by the CLI and the button, plus
  `deliver` into the Syncthing outbox), `export_service.py` (the one-click
  endpoint; see *Commands*). Per-flight pages never print
  night/instrument/XC/landings — synthetic on the pre-2026 rows. Targets: `generic`,
  `faa`, `ual`, `swa`, `allegiant`, `jetblue`, `aal`; `profiles.PENDING_TARGETS` names
  the ones still waiting on a real field list (Delta) — never guess a carrier's fields.
  - `generic` is the pilot's own logbook: a `Profile` with **no sections**, so
    `render_profile` prints no target sheet at all (a target sheet is one
    organisation's form). It is the summary + the three reference tables + the log
    pages. Do not give it carrier-shaped sections.
  - `REFERENCE_SECTIONS` (Totals by FAA Type / Hours by Category / Class Hours) is the
    standing application-reference block appended to **every** target. Group by
    `Aircraft.FAA_Type`, never a display name, so a spelling fix cannot move a grouping.
    `reference_sections(profile)` is what the renderer actually calls: a target with
    `Profile.reports_supervised_sic=False` (JetBlue) loses the two SIC-to-PIC rows and
    their note there too. Nothing else differs between targets — a figure quoted on one
    application must stay traceable from any other.
  - Read `Cross_Country_Time`, `Night_Time` and `Instrument_Time` **as stored** — never
    recompute them here, so a change to the importer's definition flows through on its own.
  - Allegiant forbids conversions of any kind and must never see `SORTIE_FACTOR`, which
    Southwest uses from the same module. `test_profiles.py` guards this; keep it.
  - JetBlue reports flight time as dropdown **bands**, not figures. Only band labels seen
    on the submitted application are in the ladders (`JETBLUE_TOTAL_BANDS`,
    `JETBLUE_TYPE_BANDS`, `JETBLUE_TIMEFRAMES`); a value off the ladder prints
    `OFF_LADDER` and the hours rather than inventing a label. Add the next label when the
    hours grow past it. `JETBLUE_TYPE_NAMES` / `JETBLUE_MULTI_ENGINE_TYPES` reproduce the
    aircraft rows as submitted — Grist records no engine count, so a twin-engine
    helicopter is named, not inferred.
  - JetBlue's application has **no** PIC-performing-SIC field, so no JetBlue metric
    may read `sic_to_pic` or anything derived from it (POSITION is the highest seat
    held, not an hours majority). `test_profiles.py` guards this by rendering the
    whole export with and without the column populated; keep it. Allegiant fields 7-9
    are *PIC or supervised SIC*, so Allegiant (and every other target) keeps the
    reference rows that evidence them.
  - American (`aal`) is **one** block of its application — the repeating per-aircraft
    entry — and nothing else of that form has been transcribed. A row is one
    `FAA_Type` under **one operating rule** (the form demands a separate entry per
    rule; no type in the logbook has two today, but the split is built in). Every
    hours figure on that sheet is a whole number via `_half_up` — round half **up**,
    never truncate, and never `round()`, which turns 42.5 into 42. The exact tenths
    stay off the sheet and live on the Application Reference block.
  - The American entry is the **only** place on that application that takes flight
    time, so `PIC + SIC` must account for the whole logbook. Dual received is
    reported as **SIC** (`_entry_sic`) — it has no field of its own and the pilot
    was not in command — which works because every row splits
    `pic + sic + dual_received = block`. **Dual given is NOT added to PIC**: it is
    flown in command and already inside that column, so adding it double-counts
    and breaks the total. Its own column reports it, in addition to nothing.
  - The American totals row sums the cells **as printed** (`per_entry`), not a
    separately rounded grand total — 348.4 h of PIC rounds to 348 while the eight
    entries as typed come to 349, and the figure that matters is the one the
    application reaches by adding the boxes. `_aal_total_note` states the gap.
    The three H-1 variants are one entry filed as the AH-1Z, and `_aal_variant_note`
    writes the hours in the other two **and checks the role claim against the data**
    — never hardcode "all SIC".
  - American lists the CRJ-200/550/700/900 separately, so `AAL_SPLIT_TYPES` (`CL65`
    only) makes those entries key on the **Aircraft code** as well as the FAA type —
    the one place the grouping drops below `FAA_Type`, gated on that allowlist for
    exactly the reason the rule exists. `AAL_VARIANT_NAMES` holds the designations
    as American's own list spells them; an unrecognised code still gets its own row
    under its model name, so a rename is a differently-named row, never lost hours.
    Splitting changes no totals. Do not add a type to that set without seeing it
    listed separately on the application.
  - `Section.notes` entries may be `str` **or** `fn(legs, ctx) -> str`, so a note can
    quote a real figure; one that returns "" is left out. `profile_render._notes`
    resolves them. Do not go back to static-only notes.
  - Every note on a target sheet is read by the airline's recruiting department, not
    by us: no file names, no "dropdown", no "re-run it", no build talk. There is a
    test asserting that for the JetBlue and American notes.
- **One-off backfills (Grist writes, dry-run by default):** `sic_to_pic.py` fills
  `Flights.SIC_to_PIC` from the legacy workbook's PF column (14 CFR 61.51) behind a hard
  reconciliation gate; `training_codes.py` rewrites the historical `Flights.Notes` remarks
  to their 4-digit event codes. Both are history-only and already applied (2026-11-10) —
  do not re-run against new data without re-deriving the gates.
  - `Flights.SIC_to_PIC` is labelled **SIC-to-PIC (§61.51)** in Grist with
    `untieColIdFromLabel` set, so the display name can be changed without renaming the
    `colId` the SQL depends on. Renaming a tied column silently breaks every query that
    names it — that is how it broke once already.
  - The codes live in `Notes` and nowhere else; a stored column for them would only
    duplicate it.
- **CLI:** `cli.py` (Click). Entry point `logbook-import` (`pyproject.toml [project.scripts]`).

## Commands
All import commands default to dry-run; add `--commit` to write.
- `import-actual --role {pic|sic} [--operator skw] [--commit] [--update-map] [--update-apps]`
  — flown legs → Flight rows; writes `Duty_Periods.Actual_Credit` (Day Total) and
  `Trips.Actual_Credit` (sum of Day Totals), sets no-flight days `Cancelled`.
- `import-planned --role {pic|sic} [--commit]` — Trip + Duty Period rows, no flights.
- Both write `Trips.TAFB` from the SkedPlus header (last import wins). `Trips.Base` =
  first schedule line origin, on trip create only. The txt header is never used for
  base or aircraft (see `AGENTRULES.md` → *Aircraft Philosophy*).
- `import-rsr [PDF...] [--inbox DIR] [--commit]` — SkyWest RSR system-wide reports →
  `RSR_Metrics` (one row per Scope|Fleet|Data_Month; newest report wins, a report's
  oldest column only fills gaps). Domicile reports have no efficiency pages.
- `export-map [--output PATH] [--update]` — regenerate `docs/map_data.geojson`; `--update`
  commits + pushes (GitHub Pages).
- `export-profile --target {generic|faa|ual|swa|allegiant|jetblue|aal} [--output DIR] [--as-of DATE]
  [--pilot FILE] [--no-log]` — printable summary + target sections + the three
  application-reference tables + certified log pages. Read-only toward Grist (no
  `--commit`). Writes `exports/` (gitignored — never `docs/`, which is public). Pilot
  identity comes from gitignored `pilot.toml` (see `pilot.toml.example`).
- `serve-exports [--host H] [--port 8486] [--outbox DIR] [--allow-host H] [--allow-origin O]`
  — the one-click export page (`export_service.py`), deployed as
  `deploy/systemd/logbook-export.service`. A click runs **one `export-profile`** in
  process and copies the file to `~/Logbook-Outbox`, which Syncthing carries to the
  Mac. Keep its guard rails: Tailscale-only bind (never `0.0.0.0`), `Host` header
  pinned to that address, `Origin` limited to the page itself / Grist (:8484) /
  homepage (:3001), target validated against `profiles.TARGETS`, no shell, and
  nothing that can write to Grist or start an importer. Added to Grist as a
  **custom widget** (Custom URL) — Grist webhooks are a dead end here: this
  instance sets no `ALLOWED_WEBHOOK_DOMAINS`, and with it unset Grist rejects every
  webhook target.
- `backfill-sic-to-pic --workbook FILE [--commit]` — fills `Flights.SIC_to_PIC` (SIC time
  flown as pilot flying under a supervising PIC) from the legacy AnytimeLogbook PF column.
  The workbook is read for the PF column **only**; every other figure in it is superseded
  by Grist. Refuses to write unless the per-aircraft gate matches to the tenth
  (UC-12W 244.7 / AH-1Z 210.7 / AH-1W 1.3 / UH-1Y 0.6 / MV-22 0.3, total 457.6) and no row
  would log SIC-to-PIC alongside PIC. Never keep that workbook in this repo.
- `backfill-training-codes [--commit]` — rewrites `Flights.Notes` on the historical rows to
  the flight's 4-digit military event codes, dropping the `Historical line-item import …`
  preamble. Remarks up to 16 digits are exact; longer ones went through a float, so the
  value is rounded (never truncated) to 15 significant digits and only the first four codes
  are kept. Flight-school text remarks keep the pilot's own words. No code-to-description
  lookup — that mapping is the user's to maintain. `profile_data.parse_remark` reads both
  the old prefixed shape and the cleaned one.
- `export-apps` / `enrich-night` / `backfill-passengers` — **legacy, Airtable-only.**

## Dev / test
- Package is `uv`-managed (`logbook-tools/uv.lock`, `.venv` present). Python ≥ 3.11.
- Run tests from `logbook-tools/`: **`uv run pytest`** (or activate `.venv` and run `pytest`).
  `pythonpath=src`, `testpaths=tests`. Coverage spans parsers, mappers, keys, night, time,
  cli, config, export profiles, the export service and the one-off backfills
  (27 test modules).
- **On crushbox** `uv` is not installed and `logbook-tools/.venv` is runtime-only (no
  `pytest`) — it is what the systemd importer runs, so do not add dev packages to it.
  Make a throwaway venv instead: `python3 -m venv /tmp/t && /tmp/t/bin/pip install -e
  logbook-tools pytest && cd logbook-tools && /tmp/t/bin/python -m pytest`.
- Deps: `click`, `python-dotenv`, `pyairtable` (legacy), `astral`, `timezonefinder`,
  `openpyxl`; dev: `pytest`.

## Config & deployment
- **The server is `crushbox`** — the only host in this system. It runs Grist, the
  systemd importers and the export button, and `100.78.232.7` is its own Tailscale
  address. There is no second machine and nothing here is reached over SSH: a
  "deploy" is `git pull` in `/home/crushbox/Developer/logbook` plus a
  `systemctl restart`, run on this box. An earlier host name survived in prose
  long after the move and sent readers looking for a machine that does not exist;
  `tests/test_host_references.py` now fails if it reappears, if a doc quotes a
  tailnet address other than the one `DEFAULT_GRIST_URL` dials, or if a unit file
  names another user. If the server is ever genuinely renamed, change
  `DEFAULT_GRIST_URL`, the unit files and the docs in one commit — do not delete
  those tests to make a rename pass.
- **Creds:** `logbook-tools/.env` (gitignored) — `LOGBOOK_BACKEND=grist`, `GRIST_URL`,
  `GRIST_API_KEY`, `GRIST_DOC` (legacy `AIRTABLE_*`). Template: `logbook-tools/.env.example`.
- **Grist canonical URL:** `http://100.78.232.7:8484` (Tailscale-only; other hostnames
  rejected).
- **Deployed on crushbox:** `deploy/systemd/logbook-import-{planned,actual,rsr}.{path,service}`
  watch `inbox/{planned,actual,rsr}` and run `scripts/process-inbox.sh` (settle delay,
  txt/csv pair-wait, `flock`, always empties the watch dir). Transport: Syncthing
  (Mac↔crushbox). `sudo` install steps are the user's.
- **Export button:** `deploy/systemd/logbook-export.service` runs `serve-exports` on
  `http://100.78.232.7:8486/`; the outbox is `~/Logbook-Outbox` (outside the repo —
  exports are flight data and must never be committed). Syncthing folder id
  `logbook-outbox`, Send Only, paired with the Mac's
  `/Users/crush/Documents/Logbook-Outbox` (Receive Only). README →
  *One-click exports (the button)* has the install and pairing steps.

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
- `docs/historical-logbook-import.md`.
