# Part 117 Compliance Analytics — Planning Document
## Logbook Project

*Status: Research and planning only. No code changes, no Airtable writes.*
*Written: 2026-05-25.*

---

## 1. Executive Summary

14 CFR Part 117 governs the flight and duty limits for every SkyWest trip this pilot flies. The logbook already captures the raw data — Report Time, Release Time, Out Time, In Time, and Block Time — to compute most Part 117 metrics without any schema changes. This document catalogs what is derivable today, what requires modest additions (airport timezone population), and what is too complex to be worth implementing given the "simple + robust" architectural principle.

**The opportunity in one sentence:** FDP length, rest adequacy, and cumulative block-time windows are all computable from current data; the gap is that Part 117's Table B FDP limit requires knowing local report time (not UTC), which requires airport timezone data that is currently unresolved.

**Recommended implementation strategy:**
- **Phase 1 (immediate, Airtable only):** FDP duration, rest period gap, rest adequacy flag — all as formula fields on Duty Periods. No Python, no new data. These deliver immediate compliance awareness.
- **Phase 2 (moderate effort, Python + Airtable):** A `logbook-import compliance-check` CLI command that queries Airtable and prints rolling cumulative totals (100h/672h block, 60h FDP/168h, 190h FDP/672h). Rolling windows cannot be computed in Airtable formula fields; Python is necessary.
- **Phase 3 (later, if airport timezone gap is resolved):** Table B FDP exceedance flags — the exact limit depends on local start time and leg count, which requires populated airport timezone data.

The cumulative block time limits (the "avoid going over 100 hours in 28 days" rule) are likely the most operationally relevant metrics for day-to-day awareness. They are also the ones Airtable cannot compute natively — making the Python compliance-check command the highest-leverage implementation target.

---

## 2. Part 117 Regulation Deep-Dive

### 2.1 What Part 117 Is and Why It Applies

14 CFR Part 117 — "Flight and Duty Limitations and Rest Requirements: Flightcrew Members" — became effective January 4, 2014, replacing the previous Part 121 rest rules. It applies to all Part 121 passenger operations, which includes every SkyWest flight. The rule was the product of post-Colgan Air flight-time/duty-time science and was designed around fatigue physiology rather than the historical administrative limits it replaced.

Part 117 distinguishes sharply between:
- **Flight time** — block hours, what gets logged
- **Flight Duty Period (FDP)** — the broader window from report to aircraft parked after last flight

Both have separate per-period limits AND cumulative rolling limits.

### 2.2 Key Definitions (§117.3)

These are the exact regulatory definitions. Understanding them is essential for correct metric implementation.

**Flight Duty Period (FDP):** "A period that begins when a flightcrew member is required to report for duty with the intention of conducting a flight, a series of flights, or positioning or ferrying flights, and ends when the aircraft is parked after the last flight and there is no intention for further aircraft movement by the same flightcrew member. A flight duty period includes the duties performed by the flightcrew member on behalf of the certificate holder that occur before a flight segment or between flight segments without a required intervening rest period."

Key implication: **FDP ends at block-in on the last flight (when aircraft is parked).** The regulation does not define a separate "post-flight completion time" that extends the FDP clock. Post-flight duties that occur after the aircraft is parked are NOT part of the FDP under the regulatory definition. (Some airline ops specs or SOPs may define release time as block-in + some fixed buffer for administrative duties; that is an airline policy layer on top of the regulation, not the regulation itself.)

**Rest Period:** "A continuous period during which the flightcrew member is free from all restraint by the certificate holder, including freedom from present responsibility for work." This is a strict definition — the pilot must be genuinely free, not merely not flying.

**Acclimated:** "A condition in which a flightcrew member has been in a theater for 72 hours or has been given at least 36 consecutive hours free from duty."

**Theater:** "A geographical area in which the distance between the flightcrew member's flight duty period departure point and arrival point differs by no more than 60 degrees longitude."

**Window of Circadian Low (WOCL):** "A period of maximum sleepiness that occurs between 0200 and 0559 during a physiological night."

**Physiological Night's Rest:** "10 hours of rest that encompasses the hours of 0100 and 0700."

**Deadhead Transportation:** Part 117 explicitly classifies deadhead as "duty and is not rest." Deadhead legs are included within an FDP for FDP-length calculation purposes, but the flight time on a deadhead leg does NOT count as loggable block time for cumulative flight-time limits.

### 2.3 Per-FDP Limits

#### Table A — Maximum Flight Time Per FDP (§117.11)
Applies to unaugmented (minimum crew) operations only. This is the per-FDP block time ceiling.

| Report Time (Acclimated) | Max Flight Time |
|--------------------------|----------------|
| 0000-0459 | 8 hours |
| 0500-1959 | 9 hours |
| 2000-2359 | 8 hours |

The user's operation is single-crew (Captain + FO), so this table applies. For the CRJ flying primarily daytime schedules (0500-1959 report times), the practical limit is **9 block hours per FDP**.

#### Table B — Maximum FDP Duration Per FDP (§117.17)
This is the FDP length limit (report time to aircraft parked). It depends on: (1) scheduled start time (in local acclimated time) and (2) number of scheduled flight segments.

| Scheduled Start (Acclimated) | 1 Seg | 2 Seg | 3 Seg | 4 Seg | 5 Seg | 6 Seg | 7+ Seg |
|------------------------------|-------|-------|-------|-------|-------|-------|--------|
| 0000-0359 | 9.0 | 9.0 | 9.0 | 9.0 | 9.0 | 9.0 | 9.0 |
| 0400-0459 | 10.0 | 10.0 | 10.0 | 10.0 | 9.0 | 9.0 | 9.0 |
| 0500-0559 | 12.0 | 12.0 | 12.0 | 12.0 | 11.5 | 11.0 | 10.5 |
| 0600-0659 | 13.0 | 13.0 | 12.0 | 12.0 | 11.5 | 11.0 | 10.5 |
| 0700-1159 | 14.0 | 14.0 | 13.0 | 13.0 | 12.5 | 12.0 | 11.5 |
| 1200-1259 | 13.0 | 13.0 | 13.0 | 13.0 | 12.5 | 12.0 | 11.5 |
| 1300-1659 | 12.0 | 12.0 | 12.0 | 12.0 | 11.5 | 11.0 | 10.5 |
| 1700-2159 | 12.0 | 12.0 | 11.0 | 11.0 | 10.0 | 9.0 | 9.0 |
| 2200-2259 | 11.0 | 11.0 | 10.0 | 10.0 | 9.0 | 9.0 | 9.0 |
| 2300-2359 | 10.0 | 10.0 | 10.0 | 9.0 | 9.0 | 9.0 | 9.0 |

**Non-acclimated adjustment (§117.13(b)):** If the crewmember is NOT acclimated (has not been in the current theater for 72 hours OR has not had 36 consecutive hours free from duty), the Table B limit is **reduced by 30 minutes**. Additionally, the lookup uses local time at the theater where the crewmember was LAST acclimated — not necessarily the current location.

For MSP-based domestic flying that doesn't cross more than 60° longitude and stays on a regular schedule, the acclimated assumption almost always holds. True non-acclimated situations require unusual circumstances (e.g., international positioning, extended time zone travel).

**Practical CRJ context:** A typical 4-leg duty day for the CRJ starting at 0700-1159 local has a Table B limit of 13.0 hours. 4-leg days starting at 0600-0659 have a 12.0-hour limit. Early-morning starts (0400-0459) on 4 legs are capped at 10.0 hours.

#### FDP Extensions (§117.19)
Two types of extensions are allowed for unforeseen circumstances:

**Before takeoff:** Up to 2 hours of extension; only one extension >30 min per rest cycle; cannot exceed cumulative FDP limits in §117.23(c); FAA report required if extension > 30 min.

**After takeoff:** Extension "to the extent necessary to safely land the aircraft at the next destination airport or alternate"; only once before rest; MAY exceed §117.23(c) cumulative limits; FAA report required if > 30 min.

### 2.4 Cumulative Limits (§117.23)

These are rolling-window limits, not calendar-period limits. All flight time counts across ALL certificate holders (if flying for multiple carriers, all time aggregates).

#### Flight Time (Block Hours) Cumulative Limits:
- **100 hours in any 672 consecutive hours** (= 28 days)
- **1,000 hours in any 365 consecutive calendar day period**

#### Flight Duty Period Hours Cumulative Limits:
- **60 FDP hours in any 168 consecutive hours** (= 7 days)
- **190 FDP hours in any 672 consecutive hours** (= 28 days)

Note: "672 consecutive hours" = exactly 28 days. This is a rolling window, not a calendar month. The window moves forward every hour. The most conservative compliance interpretation is to compute the window ending at the current moment and look back 672 hours.

**Practical ranges for a SkyWest FO:**
- A typical 4-day trip with ~16h block and ~45h total FDP leaves meaningful buffer within the 28-day limits. The 100h/28-day cap becomes a real constraint in busy months with back-to-back trips, particularly in the spring/summer pick seasons when pilots may hold high-time lines.
- The 60h FDP/168h limit is the tightest shorter-term constraint. A pilot flying two consecutive 4-day trips back-to-back with minimal days off could approach this limit.

### 2.5 Rest Requirements (§117.25)

**Weekly rest:** At least 30 consecutive hours free from all duty within the past 168 consecutive hours.

**Pre-duty rest (the "10/8 rule"):** Before beginning any reserve or flight duty period, the crewmember must receive:
- At least **10 consecutive hours** measured from release from the previous duty
- Of which at least **8 hours** must be uninterrupted sleep opportunity

If the crewmember determines the 10-hour window will not provide 8 hours of uninterrupted sleep, they must notify the company and cannot report until a compliant rest period is received.

**International rest:** After travel crossing more than 60° longitude while away from home base for more than 168 consecutive hours: 56 consecutive hours of rest encompassing three physiological nights. Not applicable for domestic CRJ flying (CONUS spanning ~60° longitude at most).

**Post-deadhead rest:** If deadhead transportation exceeds the Table B FDP limit, the pilot must receive rest equal to the deadhead duration (but not less than the 10-hour standard). This is relevant for cross-country deadheads.

### 2.6 Reserve Rules (§117.21)

**Short-call reserve:** A reserve availability period (RAP) may not exceed 14 hours. The combined time in a RAP plus any subsequent FDP cannot exceed the lesser of: the applicable Table B limit + 4 hours, or 16 hours.

**Long-call reserve:** Crewmember must receive full 10-hour rest before reporting; the RAP time itself does not count toward FDP.

**Key implication for the logbook:** Reserve days typically don't create Duty Period records in the current logbook structure (since no flight is flown). If the pilot gets called from reserve, that creates a normal Duty Period record. Reserve standby time by itself currently has no representation. This is an acceptable gap — tracking reserve availability periods adds significant complexity for limited insight.

### 2.7 Consecutive WOCL Operations (§117.27)

A crewmember may participate in up to **five** consecutive FDPs that infringe the WOCL (0200-0559) IF provided with a rest opportunity in suitable accommodation of at least 2 hours during each nighttime FDP. Without that accommodation, the limit is **three** consecutive nighttime operations.

This is edge-case territory for CRJ MSP-based domestic flying unless a pilot holds a very early morning line (e.g., 0400 report). Worth noting but unlikely to require active tracking for most duty days.

### 2.8 Fatigue Risk Management (§117.7 and §117.9)

§117.9 requires annual fatigue education and awareness training for crewmembers. §117.7 establishes the framework for carriers to adopt a Fatigue Risk Management System (FRMS) to exceed Part 117 limits with FAA approval — this is not relevant to individual pilot tracking. The personal obligation is in §117.5: each crewmember must affirmatively declare fitness before every flight. This is a legal duty on the crewmember; the logbook cannot automate it, but could log fitness declarations if desired (beyond current scope).

---

## 3. Metric Catalog

Each metric below includes: regulatory basis, exact limit, data availability in the current logbook, implementation path, and operational value rating.

---

### Metric 1: FDP Length (Duty Period Duration)

**Regulatory basis:** §117.17 establishes the maximum FDP. The FDP itself (its raw duration) is not separately reported — you compute it to compare against the applicable Table B limit.

**Definition:** Duration from Report Time to Release Time on a Duty Period record. Per §117.3, FDP ends when the aircraft is parked after the last flight. For logbook purposes, Release Time (as recorded in SkedPlus exports and stored in Duty Periods) approximates the FDP end — it typically reflects actual gate-in time for the last leg.

**Data availability:** COMPLETE. `Duty Periods.Report Time` and `Duty Periods.Release Time` are both stored as UTC datetimes.

**Implementation path:** Airtable formula field on Duty Periods.

Formula (Airtable):
```
DATETIME_DIFF({Release Time}, {Report Time}, 'hours')
```
or more precisely for decimal precision:
```
(DATETIME_DIFF({Release Time}, {Report Time}, 'minutes')) / 60
```

**Complexity:** Trivial. This is the simplest possible formula — two stored datetimes, one subtraction.

**Operational value:** HIGH. FDP length is the foundational metric. Knowing "this duty day was 11.2 hours" is immediately useful for monitoring schedule intensity and checking against the applicable Table B limit.

**Caveats:** The formula yields FDP length in hours but does NOT tell you whether that length is within the applicable Table B limit — that requires knowing local start time and leg count (see Metric 8).

---

### Metric 2: Rest Period Between Consecutive Duties

**Regulatory basis:** §117.25(e) — minimum 10 consecutive hours immediately before beginning any FDP, measured from release.

**Definition:** The gap between `Release Time` of duty period N and `Report Time` of duty period N+1 within the same trip.

**Data availability:** COMPLETE for within-trip rest (consecutive Duty Periods within the same Trip). The between-trip rest gap (from the last Duty Period of one trip to the first of the next) requires knowing which Duty Periods are consecutive — achievable by sorting all Duty Periods by Report Time.

**Implementation path:** 
- **Within a trip:** Airtable cannot easily reference a "previous record" within a linked set. An Airtable automation or scripting block could compute this, but it's not a formula field.
- **Across all duties:** Python is the clean path. A `compliance-check` command can sort all Duty Periods by Report Time and compute pairwise rest gaps.

**Complexity:** Moderate. The data exists; the challenge is Airtable's inability to do cross-record sequential math.

**Operational value:** HIGH. Rest adequacy is a core legal requirement. Knowing "my minimum rest gap this month was 9.8 hours on [date]" is both compliance-relevant and fatigue-awareness useful.

---

### Metric 3: Rest Adequacy Flag (Does Each Rest Period Meet the 10-Hour Minimum?)

**Regulatory basis:** §117.25(e) — 10 consecutive hours minimum.

**Definition:** Boolean: did the rest period between consecutive duties meet ≥ 10.0 hours?

**Data availability:** COMPLETE for within-trip consecutive duties (same trip). Cross-trip requires Python (see Metric 2).

**Implementation path:** Python compliance-check command. Can emit a flag for any rest gap < 10.0 hours: "WARNING: Rest between [date] DP1 and [date] DP2 was 9.8h (< 10.0h minimum)."

**Complexity:** Trivial once rest gaps are computed.

**Operational value:** HIGH. A direct legal compliance check. Even one violation is significant.

---

### Metric 4: Daily Flight Time (Block Hours Per FDP vs. Table A Limit)

**Regulatory basis:** §117.11 Table A — maximum block hours per FDP based on report time.

**Definition:** Sum of block hours flown in a single FDP vs. the Table A limit for that FDP's start time.

**Data availability:** NEAR-COMPLETE. 
- Block hours per FDP: available as `Duty Periods.Actual Block` (rollup from linked Flights).
- Table A limit lookup: requires knowing the local time of FDP start (UTC is stored, but Table A uses the pilot's acclimated local time).

**Implementation path:** 
- The block hours rollup is already a field on Duty Periods.
- Table A lookup requires local time resolution. For CRJ MSP-based flying, UTC-6 (CST) or UTC-5 (CDT) covers most operations. A pragmatic approximation: if the base is MSP (Central Time), the UTC offset is well-known. The precision of whether a 0700 local report is in the 0500-1959 bucket or the 2000-2359 bucket matters only for very early/late FDPs.
- Python implementation with timezone logic is the right approach for correctness. Airtable formula can do a rough check using UTC offsets applied globally.

**Complexity:** Moderate (timezone conversion required for correctness).

**Operational value:** MEDIUM. Table A caps (8-9h) are rarely approached on regional CRJ flying — most duty days have 3-5 hours of block. This is more of a "catch the extreme outlier" check than a day-to-day concern.

---

### Metric 5: 28-Day Rolling Block Time (100h / 672h Limit)

**Regulatory basis:** §117.23(b)(1) — 100 hours of flight time in any 672 consecutive hours.

**Definition:** Sum of block hours (excluding deadhead legs) flown in the 672-hour window ending at a given point in time.

**Data availability:** COMPLETE. `Flights.Block Time` exists for every non-deadhead flight. `Flights.Out Time` (UTC) provides the timestamp for window computation.

**Implementation path:** PYTHON REQUIRED. This is a rolling-window aggregation — it cannot be expressed as an Airtable formula field, which is per-record only. 

The Python compliance-check command:
1. Fetches all Flight records with `Out Time` and `Block Time` fields.
2. Filters to non-deadhead flights.
3. For a query date (defaulting to today), looks back 672 hours and sums block time.
4. Reports current cumulative total and headroom to the 100h limit.

**Complexity:** Moderate. The data is clean; the query and window logic are straightforward Python.

**Operational value:** VERY HIGH. This is the most practically important compliance metric for a busy FO. Running up against 100h in 28 days is a real operational risk in a high-time month. Knowing "you have 23.4h of flight time in the last 28 days, with 76.6h remaining" is immediately useful.

---

### Metric 6: 7-Day Rolling FDP Hours (60h / 168h Limit)

**Regulatory basis:** §117.23(c)(1) — 60 FDP hours in any 168 consecutive hours.

**Definition:** Sum of FDP hours (Report Time to Release Time) across all Duty Periods in the trailing 168 hours.

**Data availability:** COMPLETE. `Duty Periods.Report Time` and `Duty Periods.Release Time` are UTC datetimes.

**Implementation path:** PYTHON REQUIRED. Same rolling-window structure as Metric 5.

The compliance-check command computes FDP duration per Duty Period (Release - Report, in hours) and sums those falling within the trailing 168-hour window.

**Complexity:** Moderate. The data exists; Python rolling-window logic is the same pattern as Metric 5.

**Operational value:** HIGH. The 60h/7-day FDP limit is a tighter near-term constraint than the 28-day limits. A pilot who flies back-to-back 4-day trips with only 2 days between could approach this. Knowing current FDP-hour exposure helps.

---

### Metric 7: 28-Day Rolling FDP Hours (190h / 672h Limit)

**Regulatory basis:** §117.23(c)(2) — 190 FDP hours in any 672 consecutive hours.

**Definition:** Sum of FDP hours across all Duty Periods in the trailing 672 hours.

**Data availability:** COMPLETE.

**Implementation path:** PYTHON REQUIRED. Identical pattern to Metrics 5 and 6.

**Complexity:** Trivial (same code handles all rolling-window metrics).

**Operational value:** MEDIUM. The 190h/28-day FDP limit is harder to hit than the 60h/7-day limit. At ~10h FDP per duty day × 4 duty days per trip × 2 trips in 28 days = ~80h — well below 190. This becomes a concern in very heavy flying months. Worth tracking as a background metric.

---

### Metric 8: Annual Block Time (1000h / 365-Day Limit)

**Regulatory basis:** §117.23(b)(2) — 1,000 hours in any 365 consecutive calendar day period.

**Definition:** Sum of all block hours (non-deadhead) in the trailing 365 days.

**Data availability:** COMPLETE for all data in Airtable. The logbook currently contains data back to approximately late 2025 (based on import file dates seen). If legacy logbook data is eventually imported, the 365-day window will eventually span pre-SkyWest flying too.

**Implementation path:** PYTHON REQUIRED. Same rolling-window logic as other cumulative metrics. The 365-day period makes this the simplest to approach: just sum all block hours since `today - 365 days`.

**Complexity:** Trivial (same infrastructure as Metrics 5-7).

**Operational value:** MEDIUM-HIGH. A new FO starting at SkyWest typically accumulates 400-700h/year. At senior FO or upgrade to Captain levels, 1000h/year becomes a real limit. Tracking annual progression is useful for career planning and compliance awareness. Even if it's not close to the limit today, the trend matters.

---

### Metric 9: Table B FDP Exceedance Flag

**Regulatory basis:** §117.17 Table B — was the FDP longer than the regulatory maximum for its start time and leg count?

**Definition:** For each Duty Period: was `FDP Duration > Table B limit` for (local report time, scheduled leg count)?

**Data availability:** PARTIAL.
- FDP Duration: computable (see Metric 1).
- Scheduled leg count: `Duty Periods.Planned Legs` field exists.
- Local report time: MISSING. Table B requires local acclimated time. Report Time is stored as UTC; converting to local requires airport timezone data.

**The timezone gap:** The Airports table has a `UTC Offset` field but it is not currently populated for most airports. The `fetch_airport_index()` function already resolves IANA timezone from airport lat/lon using `timezonefinder` — this data is available at import time but is not stored back to Airtable. The practical options are:
1. **Hardcode the pilot's base timezone** (MSP = Central Time, UTC-6/UTC-5). For a hub-based operation, most FDPs start from home base. This gives correct results ~80-90% of the time.
2. **Use the departure airport's timezone** at import time to enrich Duty Period records with a `Local Report Time` field.
3. **Accept UTC approximation** knowing that WOCL-sensitive time bands (0000-0559, 2200-2359) are the most affected, and those are exactly the boundary cases that matter most.

**Implementation path:** Phase 3. Requires either the hardcoded-base-timezone approximation (doable in Python) or populated airport timezone data.

**Complexity:** Complex (timezone resolution required). Medium once timezone data is available.

**Operational value:** HIGH — this is the single most direct legal compliance check in Part 117. But it cannot be done correctly without local time. The approximation approach (assuming CST/CDT for all MSP-base FDPs) would catch most violations with a false negative rate only for trips originating from non-Central-Time outstations.

---

### Metric 10: Weekly Rest Compliance (30h Free from Duty / 168h)

**Regulatory basis:** §117.25(b) — at least 30 consecutive hours free from all duty in the past 168 consecutive hours.

**Definition:** For each week (168-hour window), was there at least one continuous 30-hour block with no Duty Period activity?

**Data availability:** COMPLETE in principle — Duty Periods provide all on-duty timestamps.

**Implementation path:** Python. The compliance-check command can scan duty periods in a 168-hour window and verify that a 30-consecutive-hour gap exists. This is more complex than the simple rolling sum metrics — it requires identifying gaps between duties.

**Complexity:** Moderate. Gap detection logic is more involved than simple summation.

**Operational value:** HIGH. The 30-hour weekly rest rule is a firm legal requirement. A pilot on a very busy bidding month could theoretically approach this limit if trips are scheduled back-to-back.

---

### Metric 11: Statistical Summaries — Rest, FDP, Block, Legs

These are derived analytics, not direct compliance checks. For a given date range (e.g., a month or a quarter):

| Metric | Source Fields | Implementation |
|--------|--------------|----------------|
| Min/Avg/Max FDP length | Release - Report per DP | Python or Airtable formula if per-record |
| Min/Avg/Max rest gap | Gap between consecutive DPs | Python (cross-record) |
| Min/Avg/Max legs per duty day | Planned/Actual Legs per DP | Airtable formula |
| Min/Avg/Max block per duty day | Actual Block per DP (rollup) | Airtable formula |
| Days with WOCL infringement | Local Report Time in 0200-0559 | Python (needs timezone) |

**Operational value:** MEDIUM. These statistical summaries are more useful for career self-assessment and bidding strategy than real-time compliance. "My average FDP this month was 9.2 hours" tells you how demanding the month was.

---

### Metric 12: TAFB and Days Away from Base

**Definition:** Time Away From Base — from first Report Time of the first Duty Period in a trip to the Release Time of the last Duty Period. This is the TAFB metric used for pilot pay purposes under most CBAs.

**Data availability:** NEAR-COMPLETE. TAFB is already parsed from the SkedPlus TXT header (`TAFB: HH:MM`) and available in the `PairingExport.tafb_hours` field. However, per the TODO.md, the planned importer does not yet write TAFB to a `Trips.TAFB` field in Airtable. This is a known gap from the efficiency metrics work.

**Implementation path:** Airtable formula (once TAFB is written as a field). The efficiency metrics plan already calls for `Trips.TAFB` to be added.

**Operational value:** MEDIUM for Part 117 purposes directly. TAFB is more relevant for pay computation and efficiency metrics (as analyzed in `metrics-plan-efficiency-variance.md`). It is not a Part 117 compliance metric per se, but it is related to overall duty exposure.

---

## 4. Data Gap Analysis

### Gap 1: Local FDP Start Time (The Primary Blocker for Table B)

**What is needed:** For Table B lookups, Part 117 requires "scheduled time of start" in the pilot's acclimated local time. Report Time is stored as UTC. The correct local time depends on which timezone the pilot is in at the start of the FDP.

**Current state:** The `fetch_airport_index()` function already resolves IANA timezone strings from airport lat/lon using `timezonefinder`. This data is computed at import time and used for flight UTC conversion — but it is NOT written back to Duty Period records.

**Gap size:** For most trips originating from MSP (hub), the answer is simply "Central Time" (America/Chicago). This handles the large majority of FDPs. The gap is for trips starting at outstations (if a pilot is repositioned and starts a duty period at a non-Central-Time outstation). For a MSP-based CRJ pilot, this edge case is uncommon.

**Pragmatic solution options:**
1. **Base-timezone assumption:** Hardcode `America/Chicago` for all FDP start times. Correctness: ~90%+. Implementation: trivial. The 10% error rate affects boundary cases (FDPs starting very close to the time-band boundaries in the Table B lookup) and outstation starts.
2. **Enrich Duty Periods at import time:** When an actual import is committed, add a `Local Report Time` field to the Duty Period record, computed from the departure airport's IANA timezone. Correctness: 100% for flights with known airports. Implementation: moderate (adds a field and enrichment logic).
3. **Defer Table B lookup entirely:** Skip the FDP exceedance flag (Metric 9) until option 2 is implemented. Implement everything else in Phase 1-2 without it.

**Recommendation:** Option 3 for Phase 1-2. Option 2 for Phase 3 (when Table B exceedance checking is worth implementing). Do not use Option 1 as a "production" compliance check — the approximation is fine for awareness but should be labeled clearly as approximate in any output.

---

### Gap 2: Post-Flight Completion Time

**What is needed:** Part 117 defines FDP end as "when the aircraft is parked after the last flight." The logbook stores Release Time per Duty Period (from the SkedPlus export), which is the company-recorded release time, not a computed block-in time.

**Analysis:** SkedPlus release times are the crew's actual release from duty, which typically includes time for post-flight paperwork, gate exit, etc. This makes Release Time a reasonable proxy for FDP end that likely measures slightly longer than the strict regulatory definition (aircraft parked). This error direction is conservative — a longer FDP length is a more restrictive compliance check — so it is safe for compliance analysis.

**Verdict:** No gap in practice. Release Time from SkedPlus is an appropriate (and slightly conservative) proxy for FDP end. No additional data needed.

---

### Gap 3: Acclimatization Tracking

**What is needed:** Non-acclimated status reduces Table B limits by 30 minutes. Tracking whether a crewmember is acclimated requires knowing: (a) when they arrived in the current theater, or (b) whether they had 36 consecutive hours off since entering the theater.

**Analysis:** For a MSP-based CRJ pilot flying CONUS domestic routes, the "theater" is essentially the entire continental US (< 60° longitude span). Transitioning theaters only happens on very unusual assignments (e.g., flying to Hawaii or extreme CONUS east-west routing that crosses 60° longitude). Under normal CRJ MSP operations, the pilot is always in the same theater and is essentially always acclimated.

**Verdict:** Not worth implementing. The acclimatization adjustment is irrelevant for standard CONUS CRJ flying. Flag it as "assumed acclimated" in any compliance output and note the exception. If the pilot ever operates routes crossing 60° longitude, this assumption should be revisited.

---

### Gap 4: Reserve Day Tracking

**What is needed:** If the pilot has reserve days, the reserve availability period (RAP) length is regulated (max 14h RAP, combined RAP+FDP limits apply). Currently, reserve days with no flights produce no records in the logbook.

**Analysis:** Reserve days where no flight is assigned create no Duty Period records today. If called from reserve, the resulting flight creates a normal Duty Period record. The reserve availability window itself (the 14 hours of on-call time) is not captured.

**For Part 117 compliance:** The cumulative limits (100h block, 60h FDP, etc.) apply to FDP hours, not reserve hours. Reserve time only counts if it converts to an FDP. So the rolling-window compliance metrics (Metrics 5-7) are correct as-is — they count FDP hours from actual duty, not reserve standby.

The 30h/168h weekly rest requirement (Metric 10) is more affected: if a pilot is on reserve and the RAP itself counts as a "duty" constraint (not rest), then reserve days reduce the available rest window. However, since the logbook doesn't track reserve days, this analysis would undercount duty exposure for reserve pilots.

**Verdict:** Acceptable gap for now. The pilot is currently a First Officer on a bid line (not reserve), making this a low-priority gap. If the pilot moves to reserve, this gap becomes more significant. Note it as a known limitation in any compliance report output.

---

### Gap 5: Split Rest

**What is needed:** §117.15 allows "split duty" for unaugmented operations: if the pilot gets a rest opportunity of at least 3 hours in suitable accommodation between 2200-0500 local time, that rest period is NOT counted as part of the FDP. This effectively allows a longer continuous duty window.

**Analysis:** Whether SkyWest uses split duty provisions is not publicly documented. In standard domestic CRJ operations, split rest is uncommon (it requires ground time of 3+ hours in the middle of a duty period, which is unusual for a regional hub-and-spoke operation). It is not currently tracked in the logbook.

**Verdict:** Not worth implementing unless evidence emerges that SkyWest uses split rest provisions. The current FDP calculation (Release - Report) would overcount FDP length if split rest provisions are in effect — which is conservative (safer) for compliance purposes.

---

### Gap 6: SkyWest CBA Provisions More Restrictive Than Part 117

**What is known:** The user references SP-3008.4 as the SkyWest CBA provision for SDuty credit rig rules. Public information on SkyWest's CBA (SWAPA contract) indicates that some provisions may be more restrictive than Part 117 minimums, which is common in airline CBAs. However, the specific flight-time/duty-time provisions of the current SkyWest CBA are not publicly available for verification.

**What this means for the logbook:** If the CBA sets lower limits than Part 117 (e.g., a 12-hour maximum FDP instead of the Part 117 Table B maximum of 14 hours for some start times), then Part 117 compliance analysis would be necessary but not sufficient — CBA compliance would require knowing the contractual limits.

**Recommendation:** The compliance analytics should be labeled as "Part 117 regulatory limits" and the user should compare against CBA limits separately. The logbook should not attempt to hardcode CBA limits that are not publicly verifiable and may change with contract negotiations.

---

## 5. Implementation Architecture

### 5.1 What Airtable Formula Fields Can Do

Airtable formula fields operate on a **per-record basis only**. They can:
- Perform math on fields within the same record
- Reference linked-record rollup/count fields (which ARE computed from multiple records)
- Use date/time functions (`DATETIME_DIFF`, `DATEADD`, etc.)

They CANNOT:
- Look at other records in the same table ("what was the previous Duty Period's Release Time?")
- Compute rolling windows across arbitrary time ranges
- Do Table B lookups (no conditional table logic with multiple inputs in a single field)

**What this means for Part 117:** All per-record metrics (FDP length, block hours per FDP) are perfect for Airtable formulas. All rolling-window cumulative metrics (28-day block, 7-day FDP hours, 365-day block) REQUIRE Python.

### 5.2 Airtable Formula Fields — Phase 1 Additions

These can be added directly in Airtable without any Python changes.

**On Duty Periods table:**

| Field Name | Formula | Type | Notes |
|------------|---------|------|-------|
| `FDP Duration (hrs)` | `DATETIME_DIFF({Release Time}, {Report Time}, 'minutes') / 60` | Number (2dp) | Precise to the minute |
| `Rest Before (hrs)` | Cannot do cross-record in formula — skip | — | Needs Python or linked-record trick |
| `Planned Legs` | Already exists | — | |
| `Block Efficiency` | `IF({FDP Duration (hrs)} > 0, {Actual Block} / {FDP Duration (hrs)}, "")` | Number | What % of FDP was actual flight time |

**On Trips table:**

| Field Name | Formula | Type | Notes |
|------------|---------|------|-------|
| `Total FDP Hours` | Needs rollup from Duty Periods | Rollup (SUM) | Sum of linked DP FDP durations |

Note: "Total FDP Hours" requires the `FDP Duration (hrs)` field to exist on Duty Periods first, then a rollup on Trips can sum it. This would give trip-level total FDP time, useful for trip intensity analysis.

### 5.3 The Python Compliance-Check Command

**Recommended: a new `logbook-import compliance-check` subcommand.**

This is consistent with the existing CLI philosophy and the fact that the Airtable client is already wired up. It queries Airtable, computes rolling-window metrics, and prints a compliance summary. It does NOT write to Airtable (read-only by design, consistent with AGENTRULES).

**What it outputs:**

```
=== Part 117 Compliance Check (as of 2026-05-25) ===

--- ROLLING FLIGHT TIME LIMITS ---
28-day window (672h): 34.2h block flown / 100.0h limit | 65.8h remaining
365-day window:      312.5h block flown / 1000.0h limit | 687.5h remaining

--- ROLLING FDP HOUR LIMITS ---
7-day window (168h): 18.3h FDP / 60.0h limit | 41.7h remaining
28-day window (672h): 82.1h FDP / 190.0h limit | 107.9h remaining

--- RECENT REST PERIODS ---
2026-05-25 DP1 → 2026-05-25 DP2: 12.4h rest  [OK]
2026-05-24 DP4 → 2026-05-25 DP1: 11.2h rest  [OK]
2026-05-22 DP3 → 2026-05-24 DP1: 58.3h rest  [OK - between trips]

--- WEEKLY REST CHECK (30h free in each 168h window) ---
Week ending 2026-05-25: max consecutive rest gap = 58.3h  [OK]

--- DUTY PERIOD SUMMARY (last 30 days) ---
Duty periods:         12
Avg FDP length:       6.8h
Min FDP length:       4.1h  (2026-05-09)
Max FDP length:       10.2h (2026-05-17)
Avg block per DP:     3.8h
Total block flown:    45.6h
Total FDP hours:      81.4h

--- NOTES ---
Table B exceedance check: NOT performed (requires local time resolution)
Acclimatization: Assumed acclimated (CONUS domestic only)
Reserve days: Not tracked in logbook
CBA limits: Not checked (contractual, not regulatory)
```

**Key design decisions:**
- Read-only: no Airtable writes
- Prints to stdout (consistent with dry-run style of other commands)
- Default date is today; could accept `--as-of YYYY-MM-DD` for historical queries
- Fetches: all Duty Periods (Report Time, Release Time) and all Flights (Out Time, Block Time, Deadhead flag)
- Warns clearly about what IS NOT checked (Table B, acclimatization, CBA)

**Why NOT integrate into `import-actual --commit` output:** The compliance check is a read/query operation that is useful on demand, not only after imports. Separating it is cleaner and allows running it any time.

### 5.4 Future: Table B Enrichment Path

When airport timezone data is reliable (Phase 3), the Duty Period importer can be enhanced to write a `Local Report Time` field (as a formatted string: "0712 CST") or a numeric hour (e.g., 7.2). With that field available:

- An Airtable formula field `Table B Limit` can implement the multi-tier IF logic (or the compliance-check Python can do it and write results back)
- A derived field `FDP Over Limit` = `FDP Duration > Table B Limit` becomes a simple boolean formula
- Airtable filters and views can then show "any duty day that exceeded its Table B limit"

The complexity of implementing the Table B IF logic in Airtable's formula language (which supports IF but not switch/case tables) is significant — 10 rows × conditional structure means a nested IF chain. Python is cleaner for this lookup.

---

## 6. Visualization Strategy

### 6.1 What Can Be Shown in Airtable Today

With Phase 1 formula fields added:

**Duty Periods table views:**
- Grid view sorted by Duty Date showing FDP Duration, Actual Block, Block Efficiency, Planned/Actual Legs
- Bar chart: FDP Duration by Duty Date (shows duty intensity over time)
- Bar chart: Actual Block per Duty Period (flight load by day)

**Trips table views:**
- Rollup of Total FDP Hours per trip (once Duty Periods have FDP Duration field)
- Grouped view by month showing sum of FDP hours and block hours
- Existing variance views (Block Variance, Credit Variance) from efficiency metrics plan

### 6.2 Python-Generated Compliance Dashboard

The `compliance-check` command output (section 5.3) is the primary "dashboard" for Phase 2. It is intentionally terminal-based, consistent with the existing import workflow.

For Phase 3+, if a visual dashboard is desired, the existing Leaflet map infrastructure in `docs/index.html` demonstrates that static HTML files hosted on GitHub Pages work well. A `compliance-chart.html` could be generated by Python, similar to how `map_data.geojson` is generated:

- **28-day rolling block time:** A sparkline or bar chart showing daily cumulative block for the past 28 days vs. the 100h ceiling. This is the most useful visual — seeing the trend approaching or retreating from the limit.
- **Rest gap histogram:** Bar chart showing rest gap lengths, with a 10h reference line. Quickly identifies which duty transitions were tight.
- **FDP length scatter:** Dots on a timeline, y-axis = FDP length in hours, with Table B limit band overlaid (if timezone data available). Outlier FDPs are immediately visible.

However, the static HTML dashboard should be deferred until Phase 2 is working. The terminal output is sufficient and consistent with the project's "simple + robust" principle.

### 6.3 Airtable Charts Extension (Current Capability)

Airtable's built-in Charts extension can display:
- **Bar chart of FDP Duration by Duty Date** — once the formula field is added, this is a 2-minute setup in Airtable. Shows duty intensity across the logbook history.
- **Grouped bar: FDP vs Block per Duty Period** — shows how much of each FDP was actual flight vs. ground duty.
- **Grouped by month: total FDP hours and block hours** — requires the rollup on Trips and a grouped Trips view.

These are all achievable without any Python or external tools once Phase 1 formula fields are added.

### 6.4 What NOT to Build

Per the "simple + robust" principle:
- Do NOT build a dedicated "compliance" Airtable table to store computed rolling totals. They go stale and create maintenance burden. Compute them on-demand in Python.
- Do NOT build a separate "rest periods" table. Rest gaps are derivable from Duty Periods without materializing them.
- Do NOT build a fatigue score model. Part 117 provides the regulatory limits; biomathematical fatigue models (SAFTE/FAST, Boeing WOCL model) are complex and beyond scope.

---

## 7. Phased Roadmap

### Phase 1: Airtable Formula Fields (Low Effort, Immediate Value)

**Prerequisite:** None. Works with current data.

**Deliverables:**
1. Add `FDP Duration (hrs)` formula field to Duty Periods table
   - Formula: `DATETIME_DIFF({Release Time}, {Report Time}, 'minutes') / 60`
   - Immediately shows FDP length for every historical duty period
   
2. Add `Block Efficiency` formula field to Duty Periods table
   - Formula: `IF(AND({FDP Duration (hrs)} > 0, {Actual Block} > 0), {Actual Block} / {FDP Duration (hrs)}, "")`
   - Shows what fraction of each duty period was actual flight
   
3. Add `Total FDP Hours` rollup to Trips table
   - Rollup: SUM of `FDP Duration (hrs)` from linked Duty Periods
   - Enables trip-level FDP intensity analysis
   
4. Build Airtable Charts: Bar chart of FDP Duration by Duty Date

**Effort:** 30-60 minutes in Airtable. Zero Python changes.

**Value delivered:** Every historical duty period now has computable FDP length. Trend visibility into duty intensity. Foundation for Phase 2 statistical analysis.

---

### Phase 2: Python Compliance-Check Command (Moderate Effort, High Value)

**Prerequisite:** Phase 1 complete. Airtable API credentials working (already established).

**Deliverables:**
1. New `compliance-check` CLI subcommand in `cli.py`
2. New `compliance.py` module (or `part117.py`) implementing:
   - `fetch_duty_periods()` — queries Airtable for all Duty Periods (Report Time, Release Time)
   - `fetch_flight_totals()` — queries Airtable for all Flights (Out Time, Block Time, Deadhead)
   - `compute_rolling_block(flights, window_hours, as_of)` — 28-day and 365-day cumulative block
   - `compute_rolling_fdp(duty_periods, window_hours, as_of)` — 7-day and 28-day cumulative FDP hours
   - `compute_rest_gaps(duty_periods)` — sequential rest gap analysis
   - `check_weekly_rest(duty_periods)` — 30h/168h compliance check
   - `format_compliance_report(...)` — human-readable terminal output

3. Tests for rolling-window logic (edge cases: crossing midnight, duplicate dates, empty windows)

**Effort:** 3-6 hours. Well-scoped, no new dependencies needed (Airtable client already exists).

**Value delivered:** The core rolling-window compliance metrics. "Am I approaching 100h in 28 days?" answered on demand.

---

### Phase 3: Table B Exceedance Checking (Higher Effort, Completes the Picture)

**Prerequisite:** Phase 2 complete. Reliable airport timezone data.

**Option A: Hardcoded-base approach (faster)**
- Assume all FDPs start in the pilot's base timezone (America/Chicago for MSP)
- Implement Table B lookup in `compliance.py`
- Flag FDPs where `FDP Duration > Table B limit`
- Label output: "Local time estimated (base timezone assumed for all FDPs)"
- Effort: 2-3 hours

**Option B: Enriched local time (complete)**
- Enhance `import_planner.py` (on actual imports) to write `Local Report Time` (HHMM integer) to Duty Period records
- New field: `Duty Periods.Local Report Time` (number field)
- Once populated, compliance-check uses this field for precise Table B lookups
- Effort: 4-8 hours (field addition, import enrichment, compliance logic)

**Additional Phase 3 deliverable:** If a visual HTML compliance dashboard is desired, build it as a static page similar to `docs/index.html`, generated by a new `export-compliance-chart` CLI command.

---

### Phase 4: Consider-Later Items

These are mentioned for completeness but should not be implemented without a clear user need:

- **Reserve day tracking** — only relevant if the pilot moves to reserve
- **WOCL infringement flag** — counts FDPs touching 0200-0559; needs local time (same dependency as Phase 3)
- **Split duty tracking** — unlikely to be needed for standard CRJ operations
- **CBA limit checking** — requires access to the actual contract text
- **Biomathematical fatigue score** — out of scope per architectural principles

---

## 8. Open Questions / Items Needing User Input

### 8.1 Table B Approach Decision (Phase 3 Entry Point)

**Question:** For the Table B FDP exceedance check, which approach is preferred?
- Option A: Assume base timezone (America/Chicago) for all FDP starts. Fast to implement; correct for ~90%+ of cases. Output labeled as approximate.
- Option B: Enrich Duty Period records with `Local Report Time` at import time (requires schema change + importer update). Correct for all cases. Higher implementation effort.
- Option C: Skip Table B checking entirely until a later milestone.

**User context needed:** How often does the pilot start FDPs at non-MSP outstations? If it's rare, Option A is fine.

---

### 8.2 Compliance-Check Command: Scope and Behavior

**Question:** Should `compliance-check` accept a `--as-of` date to query historical windows? Or is today-only sufficient?

**Question:** Should it write any computed values back to Airtable (e.g., a `Running Block 28 Days` field on a Duty Period record), or remain read-only?

**Recommendation:** Start read-only. If real-time compliance fields in Airtable become valuable later, they can be added as a separate enrichment command (similar to `enrich-night`).

---

### 8.3 SkyWest CBA Limits

**Question:** Are there specific SkyWest CBA provisions that are MORE restrictive than Part 117 and that the pilot wants to track? Examples:
- Maximum FDP different from Table B
- Minimum rest different from 10 hours
- Monthly block hour cap different from the 100h/28-day limit

If the user provides the contractual limits, they can be added to the compliance-check output as an additional layer ("CBA limit: 12.0h max FDP, regulatory limit: 13.0h — you are within both").

---

### 8.4 Historical Data Availability

**Question:** How far back does Airtable flight data currently go? The 365-day cumulative limit (Metric 8) requires a full year of block time data. If the logbook only goes back to early 2026, the 365-day total will be underestimated until a full year of data is in the system.

**Consideration:** Once the legacy logbook import is completed (see TODO.md — "Legacy Logbook Import" milestone), the 365-day window can be computed correctly using the summary Flight records.

---

### 8.5 Compliance-Check Command Location

**Question:** Should `compliance-check` live in the `logbook-import` CLI (consistent with current tooling) or as a separate standalone script?

**Recommendation:** Keep it in the `logbook-import` CLI. It uses the same Airtable credentials and the same `pyairtable` client. A separate command in the same entry point is the simplest approach and consistent with the existing pattern (`import-actual`, `enrich-night`, `export-map` all in one CLI).

---

### 8.6 Fatigue Awareness vs. Strict Compliance

**Question:** What is the primary use case for Part 117 analytics — (a) strict regulatory compliance auditing, or (b) personal fatigue/workload awareness and bidding strategy?

This matters because:
- Strict compliance requires accurate local times, precise rolling windows, and conservative assumptions
- Fatigue/workload awareness can use approximate values (UTC as proxy for local, calendar-day groupings, rounded windows) and is still highly useful

The answer shapes how much precision to invest in the implementation. For most day-to-day use, awareness-grade accuracy (within 30 minutes on any metric) is probably sufficient. Only if the pilot is approaching a legal limit does sub-hour precision matter.

---

### 8.7 Notification / Alert Threshold

**Question:** At what percentage of each limit should the compliance-check output change from "OK" to "WARNING"?

Suggested defaults:
- Block time 28-day: WARNING at ≥ 80h (80% of 100h limit)
- Block time 365-day: WARNING at ≥ 800h (80% of 1000h limit)
- FDP hours 7-day: WARNING at ≥ 50h (83% of 60h limit)
- FDP hours 28-day: WARNING at ≥ 160h (84% of 190h limit)
- Rest gap: WARNING at < 11h (10h is the minimum; flagging below 11h provides a 1h buffer)

These thresholds are soft suggestions and can be adjusted based on user preference.

---

## Appendix A: Part 117 Quick Reference

| Limit Type | Metric | Window | Regulatory Limit |
|-----------|--------|--------|-----------------|
| Block time | Flight hours | 672h (28 days) | 100 hours |
| Block time | Flight hours | 365 calendar days | 1,000 hours |
| FDP time | FDP hours | 168h (7 days) | 60 hours |
| FDP time | FDP hours | 672h (28 days) | 190 hours |
| Rest | Minimum per-duty | Before each FDP | 10 consecutive hours |
| Rest | Sleep opportunity | Within 10h rest | 8 uninterrupted hours |
| Rest | Weekly free time | Per 168h | 30 consecutive hours |
| FDP per-FDP | Duration (Table B) | Per FDP | 9-14h (start time + leg count) |
| Flight time | Per FDP (Table A) | Per FDP | 8-9h (start time) |
| Reserve | Availability period | Per RAP | ≤14h max |
| WOCL ops | Consecutive nights | Per cycle | ≤3 (or 5 with accommodation) |

---

## Appendix B: Data Availability Summary

| Metric | Available Now? | Blocker If Not |
|--------|---------------|---------------|
| FDP duration | YES | — |
| Block time per FDP | YES | — |
| Rest gap between duties | YES (Python) | — |
| Rest adequacy (10h min) | YES (Python) | — |
| 28-day rolling block | YES (Python) | — |
| 7-day rolling FDP hrs | YES (Python) | — |
| 28-day rolling FDP hrs | YES (Python) | — |
| 365-day rolling block | YES (Python; partial history) | Full history after legacy import |
| Table B exceedance | PARTIAL | Local report time (timezone) |
| Table A exceedance | PARTIAL | Local report time (timezone) |
| WOCL infringement | NO | Local time at FDP start |
| Weekly 30h rest check | YES (Python) | — |
| Acclimatization status | ASSUMED | Non-issue for CONUS domestic |
| Reserve day tracking | NO | Fundamental data model gap |

---

*Document written 2026-05-25. No code changes, no Airtable writes have been made. Research based on eCFR 14 CFR Part 117 regulatory text and FAA guidance. CBA provisions intentionally excluded pending access to the current SkyWest CBA document.*
