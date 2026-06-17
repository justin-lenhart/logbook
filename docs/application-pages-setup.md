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

## ⚠️ One decision to make: SIC vs. dual-received for training time

This is the only place the generator does **not** match the old SWA worksheet,
and it's a definitional choice, not a bug:

- The old SWA sheet counted **all non-PIC military time as SIC**, including
  student time in the TH-57 and T-6.
- Your Airtable import (`scripts/import_legacy.py`) recorded that student time as
  **Dual Received** (PIC = SIC = 0), which is the strict FAA-logbook treatment.
- It also recorded civilian C172/PA-44 training time as **PIC**, where the old
  sheet split some of it to **SIC**.

The generator applies the airline convention for military legs
(`SIC = block − PIC − instructor`), which reproduces the workbook for every
military type. The remaining **~41.6 hr residual** in the SWA converted total
(generator 1623.7 vs. old sheet 1665.3 on the legacy subset) is entirely the
civilian C172/PA-44 dual time the old sheet counted as SIC.

**Your call:** leave it as-is (the generator's numbers are arguably the more
defensible ones), or, if you want to match the old sheet exactly, re-tag those
civilian light-piston hours as SIC in Airtable. Either way the military
conversion — which is the bulk of the value — is exact.

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
