# Metrics Plan: Efficiency & Variance
## Logbook Project — Planning Document

*Status: Planning only. No code or Airtable changes have been made.*

---

## 1. Executive Summary

This document designs two families of metrics for the logbook project: trip efficiency metrics (how productive is a trip relative to days away from home?) and variance metrics (how does actual flying compare to the schedule?). The efficiency metrics center on TAFB as the denominator, which requires adding one new field to the Trips table. Variance metrics are largely already supported by existing Block Variance and Credit Variance formula fields, but need grouped views or a Month Summary approach to be useful at the monthly level. All recommended metrics are computable from existing or easily-added Airtable fields, with no external pipeline required. The known RDY/NMD credit gap means credit-based metrics should be flagged as unreliable for planned-vs-actual comparison until that issue is resolved.

---

## 2. Efficiency Metrics — Analysis of Candidates

The core question each metric answers is framed first, then computability and value are rated.

### Source data from June 2026 TXT files

Before scoring each metric, the actual numbers ground the recommendations:

| Trip | TAFB (h) | Block (h) | Credit (h) | Legs | Duty Periods |
|------|----------|-----------|------------|------|--------------|
| E3405 (Jun 1, 4-day) | 75.8 | 16.3 | 18.95 | 14 | 4 |
| E3180A (Jun 7, 2-day overnight) | 10.85 | 2.45 | 5.43 | 2 | 2 |
| E3436 (Jun 11, 4-day) | 73.05 | 17.17 | 18.27 | 12 | 4 |
| E3412 (Jun 17, 4-day) | 72.25 | 18.0 | 18.13 | 14 | 4 |
| E3436 (Jun 25, 4-day) | 73.05 | 17.17 | 18.27 | 12 | 4 |

Note: E3180A is a 2-calendar-day overnight trip but only 10.85h of TAFB — the short TAFB combined with high credit relative to block (5.43 credit on 2.45 block) makes it an outlier that stress-tests ratio metrics.

---

### 2.1 Credit Hours per TAFB Day (Credit / TAFB in days)

**What it measures:** Effective pay rate per day of personal time spent. How many credit hours do you accumulate for each day away from home? This is the most direct answer to "was this a good use of my days off?"

**Computability:** Needs TAFB stored in Trips. TAFB is already in the TXT header (`TAFB: 75:48`) and the importer reads it. It needs to be written to a new `Trips.TAFB` number field. Once that field exists, this is a simple formula: `{Planned Credit} / ({Trips.TAFB} / 24)`.

**Rating: HIGH value.** This is the primary efficiency metric for a Part 121 FO. Credit hours are what gets paid; days away is the personal cost. The ratio directly answers the question.

**Caveats:**
- Until the RDY credit gap is fixed, use Planned Credit from the TXT, not Actual Credit rolled up from flights (which will be understated).
- Overnight trips with very short TAFB (E3180A: 10.85h = 0.45 days) will have inflated ratios — e.g., E3180A yields ~12.1 credit/day, which looks great but reflects a short overnight rather than a truly efficient long trip. Context matters.
- Formula denominator should use TAFB in decimal days (divide by 24), not calendar days, to handle the E3180A case correctly.

**June 2026 sample values:**

| Trip | Credit/TAFB Day |
|------|----------------|
| E3405 | 18.95 / 3.16 = **6.0** |
| E3180A | 5.43 / 0.45 = **12.1** (outlier — short overnight) |
| E3436 (Jun 11) | 18.27 / 3.04 = **6.0** |
| E3412 | 18.13 / 3.01 = **6.0** |
| E3436 (Jun 25) | 18.27 / 3.04 = **6.0** |

The four 4-day trips converge tightly around 6.0, which makes sense — the schedule is built to similar block/credit targets. E3180A diverges because the TAFB structure is different.

---

### 2.2 Block Hours per TAFB Day (Block / TAFB days)

**What it measures:** Actual flying intensity per day away. How many hours are you in the air for each day you're gone? This tells you how hard the trip works you operationally.

**Computability:** Same TAFB requirement as 2.1. Formula: `{Actual Block} / ({TAFB} / 24)`. Uses Actual Block (rollup from Flights) once actuals are imported; uses Planned Block before actuals arrive.

**Rating: MEDIUM value.** Useful for understanding trip workload, but less financially meaningful than credit/day. Block/day is interesting to compare across trip types (short-haul regional vs. longer legs) and to track fatigue risk.

**Caveats:**
- Deadhead legs don't contribute to Block, but they do consume duty time and extend TAFB. Trips with deadheads will have artificially low block/day.
- SDuty trips (e.g., E3097A) have very low block for a trip day — block/day will look poor even if the rig structure makes it credit-efficient.

**June 2026 sample values:**

| Trip | Block/TAFB Day |
|------|---------------|
| E3405 | 16.3 / 3.16 = **5.16** |
| E3180A | 2.45 / 0.45 = **5.44** |
| E3436 (Jun 11) | 17.17 / 3.04 = **5.65** |
| E3412 | 18.0 / 3.01 = **5.98** |
| E3436 (Jun 25) | 17.17 / 3.04 = **5.65** |

---

### 2.3 Credit:Block Ratio (Credit / Block)

**What it measures:** How favorable is the rig? A ratio above 1.0 means you're getting paid more than you fly — the guarantee, rig rules, or short-segment minimum pay is working in your favor. The higher the ratio, the better the contract protection.

**Computability:** Easy. Both fields already exist on Trips. Formula: `{Planned Credit} / {Planned Block}` (or Actual equivalents). No new fields needed.

**Rating: HIGH value.** This is a classic airline scheduling metric that every FO cares about. Short-haul regional flying typically yields higher credit:block ratios than mainline because minimum segment pay rules inflate credit on short legs.

**Caveats:**
- SDuty trips (single-duty, very short) will have extremely high ratios (E3097A: 2.0 / 1.5 = 1.33) that are structurally high but not truly representative of contract benefit — they're just short trips with minimum pay kicking in hard.
- Planned vs Actual ratio will diverge until RDY credit is resolved — use Planned Credit as numerator for now.
- A ratio close to 1.0 doesn't mean the trip is bad; it just means you flew close to block-for-block with the schedule.

**June 2026 sample values:**

| Trip | Credit:Block |
|------|-------------|
| E3405 | 18.95 / 16.3 = **1.16** |
| E3180A | 5.43 / 2.45 = **2.22** (high — short TAFB with rig) |
| E3436 (Jun 11) | 18.27 / 17.17 = **1.06** |
| E3412 | 18.13 / 18.0 = **1.01** |
| E3436 (Jun 25) | 18.27 / 17.17 = **1.06** |

The 4-day trips are tightly clustered between 1.01 and 1.16, which reflects a fairly efficient schedule relative to block. E3412 nearly flying credit = block is notable.

---

### 2.4 Legs per Duty Day (Total Legs / Number of Duty Periods)

**What it measures:** Operational busyness — how many takeoffs and landings per duty period on average? Higher = more segments, more workload, more switching costs.

**Computability:** Easy. `{Planned Legs}` already exists on Trips. Duty period count is a linked field. Formula: `{Planned Legs} / {Number of Duty Periods}`.

**Rating: MEDIUM value.** Useful context for understanding workload but not directly financial. Helpful for comparing trip types (lots of short hops vs. fewer longer legs).

**Caveats:**
- Deadhead legs inflate leg count without adding to workload in the same way (passenger, not flying crew). Should note or exclude deadheads in the metric if the goal is "flying workload."
- E3180A at 2 legs / 2 duty periods = 1.0 is a floor that will look misleadingly low — it's just a 2-leg overnight, not an easy trip per se.

**June 2026 sample values:**

| Trip | Legs/Duty Period |
|------|-----------------|
| E3405 | 14 / 4 = **3.5** |
| E3180A | 2 / 2 = **1.0** |
| E3436 (Jun 11) | 12 / 4 = **3.0** |
| E3412 | 14 / 4 = **3.5** |
| E3436 (Jun 25) | 12 / 4 = **3.0** |

---

### 2.5 Duty Utilization (Total Block / Sum of Duty Lengths)

**What it measures:** What fraction of time on-duty are you actually in the air? High utilization means you're flying most of your duty period; low means lots of ground time between legs.

**Computability:** HARD. Requires summing duty lengths across all Duty Periods for a trip. Duty lengths are computable from Report and Release times but those fields aren't currently stored in a directly summable way in Airtable. This would need either: (a) a duration formula field on Duty Periods + rollup to Trips, or (b) external computation.

**Rating: LOW value for now.** While the concept is operationally interesting, it's computationally heavy relative to the insight it adds, and the data isn't structured for easy Airtable formula calculation. Defer.

---

### 2.6 Average Block per Leg (Total Block / Total Legs)

**What it measures:** Average leg length. Short-haul regional flying has inherently short average legs; longer averages reflect fewer, longer segments.

**Computability:** Easy. Both fields exist. Formula: `{Planned Block} / {Planned Legs}`.

**Rating: LOW value as a primary metric, MEDIUM as a secondary/context metric.** Average block per leg is a useful descriptor of trip character but doesn't directly answer "how good was this trip?" It's more useful in aggregate (what's my typical leg length across all trips?) than per-trip.

**Caveats:**
- Doesn't vary much within a single fleet type flying a fixed network. All CRJ trips from MSP will cluster in similar ranges.
- More useful for fleet/route analysis than trip efficiency analysis.

**June 2026 sample values:**

| Trip | Avg Block/Leg |
|------|--------------|
| E3405 | 16.3h / 14 = **1.16h (1:10)** |
| E3180A | 2.45h / 2 = **1.23h (1:14)** |
| E3436 (Jun 11) | 17.17h / 12 = **1.43h (1:26)** |
| E3412 | 18.0h / 14 = **1.29h (1:17)** |
| E3436 (Jun 25) | 17.17h / 12 = **1.43h (1:26)** |

---

### 2.7 Credit Efficiency Index (Credit / TAFB hours, not days)

**What it measures:** Effectively the same as metric 2.1 but expressed per hour of TAFB rather than per day. This is 1/24th of metric 2.1 and adds no additional information. It's the same question with a less intuitive unit.

**Rating: LOW value — redundant with 2.1.** Drop this in favor of credit/TAFB-day which is more human-readable.

---

## 3. Recommended Efficiency Metric Set (Priority Order)

### Tier 1 — Implement first

**3.1 Credit:Block Ratio** (`Planned Credit` / `Planned Block`)
- No new fields needed
- Immediately computable as a formula field on Trips
- High financial relevance for Part 121 FO
- Works today with existing data

**3.2 Credit per TAFB Day** (`Planned Credit` / (`Trips.TAFB` / 24))
- Requires one new field: `Trips.TAFB` (number, decimal hours)
- Requires importer to write TAFB from TXT header on planned imports
- Highest insight metric — directly answers "how much do I get paid per day away?"

### Tier 2 — Add after TAFB field exists

**3.3 Block per TAFB Day** (`Actual Block` / (`Trips.TAFB` / 24))
- Same TAFB dependency as 3.2
- Good complement to credit/day — shows flying intensity alongside pay rate

**3.4 Legs per Duty Period** (`Planned Legs` / linked Duty Period count)
- No new fields needed if duty period count is already a linked-record count
- Secondary/contextual metric for workload characterization

### Tier 3 — Consider later

- Average block per leg: useful in aggregate Airtable views but low per-trip insight
- Duty utilization: skip for now due to computation complexity

---

## 4. Efficiency Visualizations

### 4.1 Credit:Block Ratio — Bar Chart by Trip

**Chart type:** Horizontal bar chart, one bar per trip (Trip Key on Y-axis, ratio value on X-axis)

**What to show:** A vertical reference line at 1.0 (break-even). Bars extending right of 1.0 show favorable rig. Sort by ratio descending to quickly identify best-rigged trips.

**Grouping:** By trip. A secondary view grouped by month shows if the rig trend is improving or worsening over time.

**Airtable implementation:** Bar chart using `Credit:Block Ratio` formula field. X-axis = ratio, Y-axis = Trip Key. The built-in bar chart extension supports this directly. Filter to Actual status trips only for clean display.

**Rationale:** This is the easiest chart to build (no new fields) and immediately tells you which trips are contract-performing well.

---

### 4.2 Credit per TAFB Day — Bar Chart by Trip + Line Over Time

**Chart type (per-trip view):** Vertical bar chart, one bar per trip, sorted by start date. Shows the efficiency of each trip in sequence.

**Chart type (trend view):** Line chart with Trip Start Date on X-axis, Credit/TAFB-Day on Y-axis. Shows whether trip efficiency is trending up or down over time. Not expected to vary much (the schedule is built to similar targets), but useful to detect anomalies.

**Grouping options:**
- By trip (primary): bar chart showing each trip's efficiency
- By month: use a grouped summary view to show average credit/day for the month
- Scatter (advanced): plot Credit/TAFB-Day on Y vs. TAFB on X. This reveals whether longer trips are more or less efficient per day. E3180A would be a clear outlier — high efficiency but very short trip.

**Airtable implementation:** Formula field `Credit per TAFB Day` on Trips, then bar chart using that field with Trip Key. Requires `Trips.TAFB` field to exist first.

---

### 4.3 Block per TAFB Day — Paired Bar with Credit per TAFB Day

**Chart type:** Grouped bar chart with two bars per trip — one for credit/day and one for block/day. This directly shows the spread between what you're paid for and what you actually fly.

**Airtable implementation:** Airtable's grouped bar chart can display two numeric fields side by side per record. Both fields must exist as formula fields on Trips.

**Rationale:** The gap between credit/day and block/day visualizes how much of your credit is "free" rig time vs. actual flying. Wide gaps = favorable scheduling; narrow gaps = flying block-for-block.

---

### 4.4 Trip Scorecard View

**Recommendation: YES, implement a Scorecard-style Gallery or Grid view in Airtable.**

A Gallery view in Airtable filtered to Actual trips, sorted by Start Date, showing:
- Trip Key
- Status
- TAFB (hours)
- Planned Block / Actual Block
- Planned Credit / Actual Credit
- Credit:Block Ratio (formula)
- Credit/TAFB Day (formula)
- Block Variance / Credit Variance (existing)

This gives an at-a-glance per-trip scorecard without any external tooling. The formula fields live directly on the Trips table.

**Do NOT build a separate "scorecard" table** — that would be over-engineering for the data volume involved. A filtered Grid or Gallery view is sufficient.

---

## 5. Variance Metrics — What to Show and How

The existing Block Variance and Credit Variance formula fields on Trips and Duty Periods are already the right foundation. The design question is how to aggregate and display them meaningfully.

### 5.1 Month-Level Planned vs. Actual Summary

**What to show:** For a given calendar month:
- Sum of Planned Block across all trips with start date in that month
- Sum of Actual Block (rollup from Flights)
- Net block variance (Actual − Planned)
- Same for Credit (with caveat noted below)
- "Scheduled X hours, flew Y, variance Z" statement

**Implementation options:**
- **Option A (preferred): Grouped Grid View.** Group the Trips table view by month (group by `Start Date` field, grouped by month). Airtable will automatically sum formula and rollup fields within groups. This requires no new table and no schema change.
- **Option B: Month Summary table.** A dedicated table with one row per month, with rollup fields linked to Trips. More powerful for charting but overkill for current data volume.

**Recommendation:** Start with Option A (grouped view). If the grouped view's aggregation becomes limiting (e.g., you want to chart month-level data over time), add Option B later.

**Credit variance caveat:** Until the RDY/NMD credit gap is resolved, Actual Credit will systematically read lower than Planned Credit for any trip that included RDY or NMD events. The variance will appear as a negative even when the trip ran on-schedule. Label this clearly in the view (e.g., a note in the view name: "Credit variance — undercount until RDY fix").

---

### 5.2 Per-Trip Variance Visualization

**What to show:** Which trips ran long or short vs. plan, and by how much?

**Chart type (primary):** Vertical bar chart with one bar per trip (sorted by date), showing Block Variance. Bars above zero = flew more than planned; below zero = flew less. A horizontal zero line is the reference.

**Chart type (secondary):** Same layout for Credit Variance, displayed as a companion chart or a separate tab. Credit Variance will be systematically negative until RDY fix — which itself is a useful visual for motivating that fix.

**Grouping:** No grouping needed at the per-trip level. Trip Key on X-axis is sufficient.

**Handling actuals-only trips (no planned import):** Trips like E3919B (Planned Block = 0, no planned import) will show a large negative Block Variance in the current formula (Actual − 0 = full negative). This is misleading. Two options:
- Filter these trips OUT of the variance chart using a view filter (`Status = Actual` AND `Planned Block > 0`)
- Display them separately in a second view labeled "Actuals only — no plan comparison"

**Recommendation:** Filter them out of the variance chart. They aren't comparable. Document in the view name.

---

### 5.3 Trend Over Time — Cumulative Variance

**What to show:** Does the schedule systematically run long or short? Is there a drift pattern?

**Chart type:** Line chart with Date on X-axis, Cumulative Block Variance on Y-axis. Each point is the running sum of Block Variance across all trips up to that date.

**Implementation:** This requires a running cumulative sum, which Airtable formula fields cannot compute natively (they're per-record, not cross-record). Options:
- **Airtable grouped view:** Group by month, show sum of Block Variance per month as a bar chart. Not truly cumulative but shows the per-month trend.
- **External computation:** A simple Python script or Airtable scripting block that queries Trips, sorts by date, computes cumulative sum, and outputs a table or chart.

**Recommendation:** Start with a monthly-grouped bar chart of Block Variance in Airtable (zero computation overhead). If you want true cumulative tracking, add a lightweight Airtable scripting block later — not worth building a Python pipeline for this.

---

### 5.4 Absolute vs. Percentage Variance

**Recommendation: Show both, but primary display is absolute hours.**

Absolute variance (e.g., +0.1h) is immediately meaningful to a pilot — you know what 0.1h is. Percentage variance (e.g., +0.7%) requires mental translation.

However, percentage variance is useful for normalizing across trips of different sizes: a 1-hour variance on a 2-hour trip (50%) is very different from a 1-hour variance on an 18-hour trip (5.6%).

**Proposed field structure on Trips:**
- `Block Variance` — already exists (Actual Block − Planned Block)
- `Block Variance %` — new formula: `{Block Variance} / {Planned Block}` (expressed as percentage)
- Same pair for Credit Variance

These are trivial formula fields. Add them when building the first variance chart.

---

### 5.5 Mixed Planned/Actual Months

For months where some trips have actuals and others are still planned (e.g., late June once actuals start coming in):

**Recommendation:** Create two views within the same month grouping:
- "Flown" filter: `Status = Actual`
- "Planned" filter: `Status = Planned`

The Charts extension can be pointed at either view. Do NOT mix planned credit totals with actual credit totals in the same chart — it creates a meaningless hybrid number.

A "planned vs. flown" progress bar within a month (% of scheduled trips with actuals imported) could be a useful dashboard element, but isn't critical.

---

## 6. Airtable Implementation Notes

### 6.1 New Field Required: `Trips.TAFB`

- **Type:** Number (decimal hours, e.g., 75.8)
- **Populated by:** Planned import — parsed from TXT header line `TAFB: HH:MM`, converted to decimal hours
- **Used by:** Credit/TAFB-Day formula, Block/TAFB-Day formula
- **Fallback:** For actuals-only trips with no TXT, TAFB can be computed from `first Duty Period Report Time` to `last Duty Period Release Time` — but this requires cross-record computation. Leave NULL for actuals-only trips until a manual entry or importer enhancement handles it.

**Importer note:** The TXT header `TAFB: HH:MM` is already read by the parser (it appears on line 2 of every TXT file reviewed). The planned importer needs one additional field write to push this value to `Trips.TAFB`.

---

### 6.2 New Formula Fields on Trips

All of these are simple Airtable formula fields, no external computation needed:

| Field Name | Formula | Depends On |
|------------|---------|------------|
| `Credit:Block Ratio` | `{Planned Credit} / {Planned Block}` | existing fields |
| `Actual Credit:Block Ratio` | `{Actual Credit (rollup)} / {Actual Block (rollup)}` | existing rollups |
| `Credit per TAFB Day` | `{Planned Credit} / ({TAFB} / 24)` | new TAFB field |
| `Block per TAFB Day` | `{Planned Block} / ({TAFB} / 24)` | new TAFB field |
| `Block Variance %` | `{Block Variance} / {Planned Block}` | existing fields |
| `Credit Variance %` | `{Credit Variance} / {Planned Credit}` | existing fields |
| `Legs per Duty Period` | `{Planned Legs} / COUNT({Duty Periods})` | existing linked field |

**Guard against divide-by-zero:** Wrap each formula in an IF: `IF({Planned Block} > 0, {Planned Credit} / {Planned Block}, "")`. Important for planned-only trips with no actuals and for actuals-only trips with no planned.

---

### 6.3 What Does NOT Need a New Table

- Month summaries: use grouped Grid view, not a new table
- Trip scorecards: use a Gallery or filtered Grid view, not a new table
- Variance tracking: use existing formula fields + chart extensions

The data volume (tens of trips per year, not thousands) does not warrant a dedicated Month Summary table at this stage. Add one if the grouped view approach becomes a bottleneck.

---

### 6.4 Recommended Airtable View Structure

**Trips table — suggested views to create:**

1. **All Trips Grid** (default, sorted by Start Date) — master reference
2. **Trip Scorecard** — filtered to Actual, showing efficiency metrics, sorted by Start Date
3. **Variance by Trip** — filtered to Actual + Planned Block > 0, sorted by Start Date
4. **Monthly Rollup** — grouped by Start Date (month), sum of Block/Credit/Variance fields
5. **Planned Upcoming** — filtered to Planned, sorted by Start Date

---

### 6.5 Credit Variance — Interim Handling Until RDY Fix

Until RDY/NMD ground events are captured and create Credit entries, treat Credit Variance as informational only for actuals. Document in the Variance by Trip view name that credit variance is understated. When building charts:
- Use Block Variance as the primary variance indicator (it is accurate)
- Display Credit Variance with a visible note or in a separate section labeled "Planned credit only — actual credit understated"
- Do not use Actual Credit in efficiency calculations as the primary metric until the gap is fixed

---

### 6.6 Computability Summary

| Metric | Computable Today? | Requires |
|--------|------------------|---------|
| Credit:Block Ratio | Yes | New formula field only |
| Actual Credit:Block Ratio | Yes | New formula field only |
| Credit per TAFB Day | No | TAFB field + importer write |
| Block per TAFB Day | No | TAFB field + importer write |
| Block Variance % | Yes | New formula field only |
| Credit Variance % | Yes | New formula field only |
| Legs per Duty Period | Yes | New formula field only |
| Cumulative Variance | No | Scripting block or external |
| Duty Utilization | No | Significant schema + computation work |

---

## 7. Open Questions for the User to Decide

**7.1 TAFB field priority**
Is adding `Trips.TAFB` and updating the planned importer to write it the right next step? Or should Credit:Block ratio (which needs no new field) come first?

**7.2 Credit variance display stance**
Until RDY credit is fixed, do you want credit variance charts hidden, shown with a warning label, or shown in a separate view where the systematic undercount is explicitly documented?

**7.3 E3180A trip character**
E3180A (Jun 7) is a 2-day overnight with 10.85h TAFB, 2 legs, and a 2.22 Credit:Block ratio. It's a structural outlier in efficiency charts. Should it be tagged or classified differently (e.g., a "trip type" field: Standard / Overnight / SDuty) so it can be filtered or color-coded in charts?

**7.4 Month Summary table**
At what data volume would a dedicated Month Summary table become worthwhile? Currently there are ~10-15 actual trips in the base. At 50+, the grouped view approach may become unwieldy. Define the trigger point now or revisit later?

**7.5 Deadhead exclusion in leg metrics**
For Legs per Duty Period, should deadhead legs be excluded from the count? (They inflate leg count without adding flying workload.) If yes, the Trips table needs a `Deadhead Legs` count field (rollup from Flights where Deadhead = true) to subtract.

**7.6 Actuals-only trips in variance views**
Confirmed approach: filter actuals-only trips (no planned import) OUT of variance charts, and list them separately. Does this match your intent, or would you prefer they appear in the chart with a visual marker (e.g., a different color bar)?

**7.7 External scripting for cumulative variance**
The cumulative variance trend requires either an Airtable scripting block or a Python CLI command. Which fits better with the project's current tooling posture? Given the import CLI already talks to Airtable, a `logbook-import report-variance` command would be consistent — but that's new reporting scope the AGENTRULES say to keep out of the import CLI. An Airtable scripting block is more self-contained.

---

*Document written 2026-05-25. No code changes, no Airtable writes. For implementation, take specific sections to Cursor (code) or Airtable directly (formula fields and views).*
