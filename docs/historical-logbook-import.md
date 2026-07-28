# Historical line-item logbook import (2015–2025)

Imported the pilot's full pre-2026 handwritten logbook into Grist `Flights`, replacing the
12 aggregate `Legacy_Summary` rows with **560 per-flight rows** (keys `HIST-0001…HIST-0560`,
`Legacy_Summary = true`). Completed 2026-07-27 on mintbox.

- **Source:** `LEN2J-AnytimeLogbook2025.12.01.xlsx`, **`Master` sheet only** (the other sheets
  hold credentials and were never opened). Extraction was done by reading `worksheets/sheet4.xml`
  directly and resolving only the shared-string indices that Master cells reference, so no
  string from a sensitive sheet was ever surfaced. The workbook was never copied into any repo;
  raw extracts were deleted after use. Working scripts + the normalized intermediate live in the
  gitignored `homelab/migration/historical/`.
- **Data region:** Master rows 6–567 = 562 dated rows; **560 real flights** + 2 non-flight
  markers excluded (row 305 `ident="Baseline"`, row 148 blank total).

## Column mapping (derived + proven)

The sheet's header rows are offset by merged cells and its row-5 `SUM()` cache is **stale**
(a column was shifted at some point; e.g. `E5` caches 1506.3 but its formula sums the empty
column `F`). So the mapping was proven from data + the `SUMIF` relationships that generated the
existing per-aircraft rollups, not from header positions.

| Field | Master column | Notes |
|---|---|---|
| Date | `A` (28 rows) / `B` (534) | coalesce A-then-B |
| Aircraft type | `C` (detailed: `C172`,`T6B`,`AH1Z`,`TH-57B/C`,`MV22B`,…) | drives aircraft + TH-57 split |
| Tail / BuNo | `D` | → `Tail_Number` |
| **Block (TOTAL)** | `E` | → `Block_Time`; Σ = 1506.3 |
| Position flags | `AI`/`AK`/`AL`/`AJ` | 1-valued **counts**, NOT hours (PIC 98 / SIC 301 / Dual 117 / Instr 12) |
| Night / Instrument / XC / Landings | `O·P`/`Q·R`/`T`/`N·O` | contaminated by running-totals in the 46 unflagged rows — **not** used per-flight (see below) |
| Remarks | — | not present in Master |

## Position attribution (PIC / SIC / dual-received)

Each flight's block time is partitioned into exactly one of PIC / SIC / dual (so
`PIC + SIC + Dual = Block`). Rule, reproducing every existing per-aircraft rollup exactly:

- `SIC` flag → SIC; `PIC` flag → PIC.
- `Dual` flag: **H57 (TH-57) → SIC** (dual-flagged in the sheet but logged as SIC — the +123.3
  that turns 929.0 into 1052.3); T-6 → dual.
- Unflagged: PA-44 & pre-2016 C172 → dual (primary/multi training); recent C172 → PIC.
- Civilian GA fine-tuning to match the existing rollups: PA-44 row 546 = the multi-engine
  checkride (only PA44 with a Pilot-Flying marker, E=3.1) → PIC in full; 2024 C172 re-currency
  rows 547 (fully) + 548 (1.1h) → dual, giving C172 PIC 30.3 / dual 15.1.

**Reconciliation (exact):** block **1506.3**, PIC **348.4**, SIC **1052.3**, dual **105.6**.
Per-aircraft-type block and PIC/SIC all match the pre-existing values to 0.1h.

## Aircraft mapping (no new rows created)

`C→C172(4)`, `T6→T-6B(14)`, `PA44→PA-44(13)`, `MV22B→MV-22(9)`, `UC12W→UC-12W(10, FAA B300)`,
`AH1Z→AH-1Z(1)`, `AH1W→AH1-W(8)`, `UH1Y→UH-1Y(2)`; **H57 split by detailed type** →
`TH-57B(11)` / `TH-57C(12)` (33.7 / 89.6 SIC).

## Operation

`Military` for all 8 military types; `Part 91` for C172 & PA-44 (matches the retired aggregates'
Operation split; the Operation×block pivot is unchanged: Military 1435.5 / Part 91 70.8).

## Secondary hours (night / instrument / XC / landings / dual-given)

Not recoverable per-flight (same contamination/shift as the position columns; military XC is a
derived ≈block value). To keep the per-aircraft `Night_Hours`/`Cross_Country_Hours`/landing
rollups (which feed the 8710 / airline-application tables) **exactly** as before, each aircraft
type's known aggregate was distributed **proportional to block** across that type's flights, with
residual correction — so per-aircraft totals are exact and no flight shows night/XC exceeding its
own block time. `Dual_Given` (41.8, AH-1Z instructor time) maps to the instructor-flagged flights.
Preserved totals: night 213.7, instrument 223.9, XC 1436.0, day/night landings 1605/369,
dual-given 41.8.

## Notable change: `Dual_Received` 233.1 → 105.6

The retired aggregates double-counted military TH-57 SIC-training as dual (SIC = Dual on those
rows). The new rows use the clean partition (`Dual = Block − PIC − SIC`), so the career
`Dual_Received` field now equals the acceptance target **105.6**. Total/PIC/SIC are unchanged.

## Downstream verified

Metabase career tiles (total 1699.9 / PIC 348.4 / SIC 1245.9) unchanged; per-aircraft & 8710
category/class rollups preserved; flight map unaffected (historical rows carry no airports →
0 routes). Departure/Arrival airports intentionally left empty (not recorded in the source).
