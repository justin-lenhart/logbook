# Airline / FAA Application Reference Pages

Generated pages that present your logbook in the structure airline and FAA
applications ask for, so you can copy-paste your pilot-hours sections.

Targets: **Southwest (SWA)**, **United (UAL)**, **FAA / IACRA**, and a
**Summary / Milestones** page (the equivalents of the worksheets in the old
AnytimeLogbook workbook). Delta is intentionally omitted — the workbook had no
DAL sheet and Delta's form doesn't follow the same structure.

## How it works

`export-apps` reads the live Airtable Flights + Aircraft tables, groups flights
by **application family** (TH-57B/C → `H57`, CR5/CR7/CR9/CRJ → `CRJ`, etc.),
applies the military **0.3-hour-per-sortie** conversion where the application
expects it, and writes one self-contained HTML page per target to `docs/apps/`.

It is the same pattern as the Flight Map: code generates a static artifact in
`docs/`, published via GitHub Pages, embedded back into Airtable as a custom
block. Nothing is written to Airtable — the generator is read-only.

```bash
cd logbook-tools
.venv/bin/python -m logbook_import.cli export-apps          # all four pages
.venv/bin/python -m logbook_import.cli export-apps --page swa --page faa
```

Output: `docs/apps/{swa,ual,faa,summary}.html`. Open them directly in a browser,
or embed (see below).

## Source of truth for family attributes

`logbook-tools/src/logbook_import/app_families.py` holds, per family: the
application family code, SWA category, FAA category bucket, UAL make/model/class/
powerplant/type-rated, and the fixed historical **military sortie counts**
(seeded verbatim from the SWA worksheet). Add a new aircraft by extending
`AIRCRAFT_TO_FAMILY` and, if it's a new family, `FAMILIES`. No Airtable schema
changes are required.

## Validation

`scripts/validate_apps.py` checks the aggregation against the trusted workbook
on the **legacy subset** of the logbook (the pre-2025-12-01 snapshot, which must
reproduce the workbook exactly):

```bash
cd logbook-tools && .venv/bin/python scripts/validate_apps.py
```

These reconcile **exactly**: total time 1506.3, converted PIC 377.8, total
military sorties 516, rotorcraft 824.6, and the per-family military SIC
reconstruction (AH-1Z 449.8, UC-12W 469.6, TH-57 123.3, T-6 68.2). Unit tests
live in `tests/test_app_report.py`.

## The SWA converted-total residual — RESOLVED (keep generator numbers)

The generator's SWA converted total is **~41.6 hr lower** than the old SWA
worksheet (1623.7 vs 1665.3 on the legacy subset). Investigated 2026-06-18; the
old sheet was wrong and the generator is correct. Do **not** re-tag anything.

Background: the old sheet counted the civilian C172 and PA-44 **dual-received**
training hours as **SIC**. By 14 CFR 61.51, single-pilot trainer dual time is
never SIC — it is dual received, and (where the pilot was sole manipulator and
rated) may *also* be PIC. So that ~41.6 hr should never have been SIC.

- **PA-44 (22.3 hr dual):** this was the pilot *earning* the AMEL rating; the
  checkride was the final flight (9 Jun 2024, already logged as 3.1 hr PIC).
  Pre-checkride dual correctly stays Dual Received — it cannot be sole-manipulator
  PIC in a class not yet rated. **No change.**
- **C172:** post-Private flights are already logged PIC (some concurrent with
  dual, which is correct); the ~11.9 hr of 2015 primary training correctly stays
  dual. **No change.**

The military legs use the airline convention `SIC = block − PIC − instructor`,
which reproduces the workbook exactly for every military type. Net: the military
conversion (the bulk of the value) is exact, and the civilian residual is the
old sheet's error, not the generator's.

### Known source-data typo (noted, not fixed)

The Master-sheet C172 PIC cell for **2024-09-24 contains `"1,6"`** (comma instead
of period), so `import_legacy.py`'s numeric parser silently drops it. True C172
PIC is ~**31.9**, not 30.3 — about **1.6 PIC hr currently lost**. To fix: correct
the cell to `1.6` in the source `.xlsx` and re-run `scripts/import_legacy.py
--commit`, then regenerate the pages. Left as-is per the pilot's request.

## Remaining manual steps (Airtable UI — can't be scripted)

1. **Publish:** commit `docs/apps/*.html` and `git push` (GitHub Pages redeploys
   in ~1 min). I left these committed on a branch but did **not** push — that's
   yours to do when you're ready, same as the map.
   **Privacy note:** GitHub Pages is world-readable. Publishing these makes your
   PIC/SIC/hours totals public to anyone with the URL (same as the existing map).
   If you'd rather keep hours private, don't push — instead embed the local HTML
   or host it somewhere access-controlled.
2. **Embed as custom blocks:** in each Airtable interface page, add a custom
   block / embed pointing at the published URL
   (`https://justin-lenhart.github.io/logbook/apps/swa.html`, etc.).
3. **Native Summary dashboard (optional):** the `summary.html` page already
   covers milestones and headline numbers. If you also want a live, in-Airtable
   dashboard, build a new interface page with Big-Number elements (Total Time,
   PIC, FW Turbine, milestone progress). This must be built in the Airtable UI;
   the API can't create interface pages.

## How to revert everything

All changes this session are **additive and in the repo** — nothing was written
to Airtable. To undo:

- Code/pages: `git checkout` the branch away / delete `docs/apps/` and the new
  `app_families.py`, `app_report.py`, and `scripts/{backup_airtable,validate_apps}.py`.
- A full read-only Airtable backup was taken first at
  `backups/airtable-<timestamp>/` (restore point, not needed since nothing was
  written).
