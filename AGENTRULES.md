# Logbook Project — Agent Rules / Passdown

## Project Purpose

This project is building a pilot logbook + reporting system centered around:

- SkyWest / SkedPlus import automation
- Airtable as the operational datastore
- Python-based import + reporting tooling
- FAA / airline-app compatible totals and reporting
- Planned vs actual trip tracking
- Legacy flight-time integration

This is NOT intended to become a full aviation operations ERP system.

Primary goal:

```text
Pilot logbook + reporting engine
```

NOT:

```text
Dispatch replay / airline ops simulation system
```

Keep architecture lean and practical.

---

# Agent Role Separation

## Native ~Codex~ *Claude* Agent (planning / architecture)

Use external ~Codex~ *Claude* agent for:

- feature planning
- architecture discussion
- schema discussion
- parser behavior discussion
- importer logic discussion
- workflow design
- Airtable structure discussion
- debugging strategy
- future feature requests
- roadmap planning
- reviewing parser behavior
- reviewing dry-run outputs
- discussing airline logbook logic
- discussion before code changes

Native Codex should:

- stay high-level first
- propose architecture before coding
- avoid unnecessary scope creep
- prioritize maintainability and simplicity
- preserve existing project philosophy
- avoid over-normalization
- avoid unnecessary abstractions

---

## Cursor Agent (implementation)

Use Cursor Agent for:

- writing Python code
- parser implementation
- test writing
- CLI implementation
- Airtable integration code
- refactors
- bug fixes
- file movement logic
- pyproject / dependency work
- dry-run output improvements
- import pipeline implementation

Cursor Agent should:

- implement only approved plans
- avoid changing schema unless explicitly requested
- avoid major architecture changes without approval
- keep functions modular and testable
- prefer explicit/simple code over clever abstractions

---

# Current Project Architecture

## Airtable Tables

Current Airtable tables:

- Flights
- Trips
- Duty Periods
- Aircraft
- Import Batch

---

## Core Data Philosophy

### Flights table

Flights table contains:

```text
Loggable entries
```

NOT strictly literal airline legs.

Flights can represent:

- actual SkyWest flown legs
- deadheads
- legacy summary entries
- future simulator entries if desired

Flights table is the primary source of truth for totals.

---

## Planned vs Actual

### Planned imports

Planned imports:

- create/update Trips
- create/update Duty Periods
- create/update Import Batch
- DO NOT create Flight rows

Planned imports are schedule projections only.

---

### Actual imports

Actual imports:

- create/update Trips
- create/update Duty Periods
- create/update Import Batch
- create actual Flight rows

Actual Flight rows drive:

- totals
- reports
- airline app outputs
- FAA-style summaries

---

# Aircraft Philosophy

Aircraft table primary key matches SkedPlus equipment codes.

Examples:


| Aircraft | FAA Type |
| -------- | -------- |
| CRJ      | CL65     |
| CR5      | CL65     |
| CR7      | CL65     |
| CR9      | CL65     |


This allows:

- direct SkedPlus import mapping
- FAA type aggregation
- subtype reporting

Tail numbers belong ONLY on Flights.

Aircraft table is NOT one row per tail number.

---

# Current Importer Status

## Implemented

Current importer foundation exists under:

```text
logbook-tools/
```

Implemented:

- Python package structure
- parser architecture
- txt parser
- csv parser
- parser merge logic
- stable key generation
- dry-run planner
- CLI structure
- tests

Current parser behavior:

- txt files are primary source
- csv files enrich aircraft/type info
- RDY/NMD recognized as non-flight duty events
- deadheads recognized
- stable Import Flight Key generation exists
- dry-run mode functional

---

## NOT yet implemented

Still missing:

- Airtable write path
- Airtable upserts
- --commit implementation
- file archival/moves
- production Airtable sync

Current importer intentionally performs:

```text
NO Airtable writes
```

Dry-run only.

---

# Stable Keys

## Trip Key

Format:

```text
{pairing_id}|{start_date}
```

Example:

```text
E3058E|2026-05-09
```

---

## Duty Period Key

Format:

```text
{trip_key}|{duty_date}
```

---

## Import Flight Key

Flights table contains writable field:

```text
Import Flight Key
```

Used for idempotency and upserts.

Format:

```text
{pairing}|{date}|{flight}|{origin}|{destination}|{departure_hhmm}
```

Example:

```text
E3058E|2026-05-09|4266|MSP|INL|1252
```

DO NOT use Airtable autonumber Flight Key for matching.

---

# Important Parsing Rules

## Non-flight schedule events

These are NOT loggable flights:

- RDY
- NMD
- similar duty/admin schedule lines

These:

- contribute to duty structure
- DO NOT create Flight rows

---

## Deadheads

Deadheads SHOULD create Flight rows.

Deadhead rows:

- Deadhead = true
- PIC Time = 0
- SIC Time = 0
- Block Time normally = 0 for totals

Deadheads may still matter later for:

- duty analysis
- audit/reconciliation
- trip reconstruction

---

# Logbook Philosophy

This project prioritizes:

- airline applications
- FAA-style totals
- career totals tracking
- aircraft/category aggregation
- import automation
- maintainability

This project intentionally avoids:

- hyper-detailed operational replay
- dispatch-grade simulation
- excessive normalization
- unnecessary micro-tables

Prefer:

```text
Simple + robust
```

over:

```text
Perfect but overengineered
```

---

# Legacy Flight Data Strategy

Legacy flight data will eventually be imported as:

```text
Summary-style Flight rows
```

NOT reconstructed individual flights.

Example:


| Aircraft | Block | PIC | SIC |
| -------- | ----- | --- | --- |
| H1       | 850   | 600 | 250 |
| B300     | 420   | 0   | 420 |


These will live in the same Flights table as airline data.

---

# CLI Philosophy

Expected CLI style:

```bash
python -m logbook_import.cli import-planned --role sic --operator skw
python -m logbook_import.cli import-actual --role sic --operator skw
```

Flags should set sensible defaults:

```text
--role sic
→ SIC Time = Block Time

--role pic
→ PIC Time = Block Time

--operator skw
→ Operation = Part 121
```

Dry-run should always be safe.

---

# Safety Rules

Until Airtable write path is fully validated:

- prefer dry-run
- avoid destructive operations
- never silently delete records
- avoid automatic schema changes
- avoid implicit overwrites

Importer behavior should be:

```text
Predictable and reversible
```

---

# Development Philosophy

The user prefers:

- progressive / step-by-step implementation
- explicit behavior
- simple debugging
- maintainable code
- minimal magic
- architecture discussion before implementation

Avoid:

- giant refactors without approval
- introducing unnecessary frameworks
- hidden behavior
- speculative abstractions
- excessive async/event architectures

When uncertain:

```text
Choose the simpler implementation.
```

