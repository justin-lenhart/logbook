"""Backfill ``Flights.SIC_to_PIC`` from the legacy AnytimeLogbook workbook.

14 CFR 61.51 lets a second in command who is the pilot flying, under the
supervision of a pilot in command, log that time. The old workbook recorded who
was flying in its PF column; Grist never carried the field, so the figure was
simply missing from every application.

This module reads that workbook for **one thing only**: the PF column. Every
other number in it -- its PIC/SIC positions, its totals, its rollups -- is
superseded by Grist, which is canonical. Nothing here reconciles the two and
nothing here reports differences between them.

The rule
--------
``SIC_to_PIC = PF hours on rows logged SIC, excluding flight school``
(T-6B, TH-57B, TH-57C). It is deliberately *not* "all PF except flight school":
142.4 h of that sits on flights already logged PIC and would double-count.

Safety
------
Writing is refused outright unless the per-aircraft reconciliation gate matches
to the tenth, and unless no row would carry SIC-to-PIC while also logging PIC.
Dry-run is the default everywhere; only ``--commit`` writes.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from logbook_import.grist_client import GristClient

# Flight school: instruction received, never supervised SIC time.
SCHOOL_TYPES: frozenset[str] = frozenset({"T6B", "TH57B", "TH57C"})

# Reconciliation gate, in Grist Aircraft codes. Hours to the tenth.
EXPECTED_BY_AIRCRAFT: dict[str, float] = {
    "UC-12W": 244.7,   # Airplane
    "AH-1Z": 210.7,    # Rotorcraft  ─┐
    "AH-1W": 1.3,      #              ├─ 212.6
    "UH-1Y": 0.6,      #             ─┘
    "MV-22": 0.3,      # Powered Lift
}
EXPECTED_TOTAL = 457.6

# Proof that the right workbook column was read at all.
EXPECTED_PF_ALL = 739.2
EXPECTED_PF_EXCL_SCHOOL = 600.5

# The workbook's "Print" sheet: 560 flight rows totalling 1506.3 h. The "_ATP"
# variant of this file gives 556 / 1500.5 and is wrong -- refuse it.
SHEET = "Print"
EXPECTED_ROWS = 560
EXPECTED_BLOCK = 1506.3

# "Print" sheet columns (1-based letters): B date, C type, D ident, F total,
# W PF (inside the PIC group: V=AC, W=PF, X=PIC), Y SIC.
COL_DATE, COL_TYPE, COL_IDENT, COL_TOTAL, COL_PF, COL_SIC = 1, 2, 3, 5, 22, 24
FIRST_DATA_ROW = 4

# Workbook type spellings squash to the Grist ones, except the Osprey, whose
# workbook code carries a block-letter suffix the Aircraft table does not use.
CODE_ALIASES: dict[str, str] = {"MV22B": "MV22"}


class BackfillError(RuntimeError):
    """A gate failed. Nothing has been written."""


def squash(value: object) -> str:
    """``"AH-1Z"`` / ``"AH1Z"`` -> ``"AH1Z"``; a numeric ident -> its digits.

    Join key normaliser for aircraft codes and tail numbers, so a punctuation
    difference between the two systems cannot break a match.
    """
    code = re.sub(r"[^A-Za-z0-9]", "", str(value if value is not None else "")).upper()
    return CODE_ALIASES.get(code, code)


def tenths(hours: float) -> int:
    """Hours as an integer number of tenths -- the logbook's real precision."""
    return round(hours * 10)


@dataclass(frozen=True)
class WorkbookRow:
    date: date
    code: str          # squashed aircraft code
    tail: str          # squashed tail / ident
    block: float
    sic: float
    pf: float

    @property
    def is_school(self) -> bool:
        return self.code in SCHOOL_TYPES

    @property
    def sic_to_pic(self) -> float:
        """PF, but only on a row logged SIC and not flown at flight school."""
        if self.is_school or self.sic <= 0:
            return 0.0
        return self.pf


@dataclass(frozen=True)
class GristRow:
    id: int
    date: date
    aircraft: str      # Grist Aircraft code, e.g. "UC-12W"
    code: str          # squashed
    tail: str          # squashed
    block: float
    pic: float


@dataclass
class Plan:
    """What a backfill would write, and the evidence that it is right."""

    updates: list[tuple[int, float]] = field(default_factory=list)
    by_aircraft: dict[str, float] = field(default_factory=dict)
    pf_all: float = 0.0
    pf_excl_school: float = 0.0
    matched: int = 0
    unmatched_workbook: list[WorkbookRow] = field(default_factory=list)
    leftover_grist: list[GristRow] = field(default_factory=list)

    @property
    def total(self) -> float:
        return sum(self.by_aircraft.values())

    @property
    def nonzero(self) -> list[tuple[int, float]]:
        return [(rid, v) for rid, v in self.updates if v > 0]


def _num(value: object) -> float:
    return float(value) if isinstance(value, (int, float)) and value is not None else 0.0


def parse_workbook(path: Path) -> list[WorkbookRow]:
    """Flight rows of the ``Print`` sheet.

    Two rows there are non-flight markers -- one with a blank total, one whose
    ident reads ``Baseline`` -- and are correctly skipped.
    """
    import openpyxl

    book = openpyxl.load_workbook(path, read_only=True, data_only=True)
    if SHEET not in book.sheetnames:
        raise BackfillError(f"{path} has no {SHEET!r} sheet (sheets: {book.sheetnames})")
    rows: list[WorkbookRow] = []
    for raw in book[SHEET].iter_rows(min_row=FIRST_DATA_ROW, values_only=True):
        day, code, ident, total = (raw[COL_DATE], raw[COL_TYPE],
                                   raw[COL_IDENT], raw[COL_TOTAL])
        if not isinstance(day, datetime):
            continue
        if not isinstance(total, (int, float)) or not total:
            continue                                    # blank-total marker
        if str(ident).strip() == "Baseline":
            continue                                    # baseline marker
        rows.append(WorkbookRow(
            date=day.date(), code=squash(code), tail=squash(ident),
            block=round(float(total), 1),
            sic=_num(raw[COL_SIC]), pf=_num(raw[COL_PF]),
        ))
    return rows


def check_workbook(rows: list[WorkbookRow]) -> None:
    """Refuse the wrong file before reading anything into it."""
    block = sum(tenths(r.block) for r in rows)
    if len(rows) != EXPECTED_ROWS or block != tenths(EXPECTED_BLOCK):
        raise BackfillError(
            f"wrong workbook: {SHEET} gave {len(rows)} rows / {block / 10:.1f} h, "
            f"expected {EXPECTED_ROWS} / {EXPECTED_BLOCK}. "
            "556 rows / 1500.5 h means this is the '_ATP' file, which is wrong."
        )
    pf_all = sum(tenths(r.pf) for r in rows)
    pf_excl = sum(tenths(r.pf) for r in rows if not r.is_school)
    if pf_all != tenths(EXPECTED_PF_ALL) or pf_excl != tenths(EXPECTED_PF_EXCL_SCHOOL):
        raise BackfillError(
            f"PF column does not reconcile: {pf_all / 10:.1f} h all types "
            f"(expected {EXPECTED_PF_ALL}), {pf_excl / 10:.1f} h excluding flight "
            f"school (expected {EXPECTED_PF_EXCL_SCHOOL}). Wrong column read."
        )


LEGACY_SQL = """
SELECT f.id               AS id,
       f."Flight_Date"    AS flight_date,
       f."Tail_Number"    AS tail,
       f."Block_Time"     AS block,
       f."PIC_Time"       AS pic,
       a."Aircraft"       AS aircraft
FROM "Flights" f
LEFT JOIN "Aircraft" a ON a.id = f."Aircraft"
WHERE f."Legacy_Summary" AND COALESCE(f."Deadhead", 0) = 0
ORDER BY f.id
"""


def load_grist_rows(client: GristClient) -> list[GristRow]:
    """The pre-2026 logbook rows -- the only rows this backfill may touch."""
    out: list[GristRow] = []
    for row in client.sql(LEGACY_SQL):
        stamp = row.get("flight_date")
        if stamp is None:
            continue
        aircraft = str(row.get("aircraft") or "")
        out.append(GristRow(
            id=int(row["id"]),
            date=datetime.fromtimestamp(stamp, tz=timezone.utc).date(),
            aircraft=aircraft,
            code=squash(aircraft),
            tail=squash(row.get("tail")),
            block=round(_num(row.get("block")), 1),
            pic=_num(row.get("pic")),
        ))
    return out


def _key(day: date, code: str, tail: str, block: float) -> tuple:
    return (day, code, tail, tenths(block))


def build_plan(workbook: list[WorkbookRow], grist: list[GristRow]) -> Plan:
    """Join on (date, type, tail, block), assigning in order within duplicates."""
    buckets: dict[tuple, list[GristRow]] = defaultdict(list)
    for row in grist:
        buckets[_key(row.date, row.code, row.tail, row.block)].append(row)

    plan = Plan(
        pf_all=sum(r.pf for r in workbook),
        pf_excl_school=sum(r.pf for r in workbook if not r.is_school),
    )
    by_aircraft: dict[str, float] = defaultdict(float)
    for wrow in workbook:
        bucket = buckets.get(_key(wrow.date, wrow.code, wrow.tail, wrow.block))
        if not bucket:
            plan.unmatched_workbook.append(wrow)
            continue
        grow = bucket.pop(0)
        plan.matched += 1
        hours = wrow.sic_to_pic
        plan.updates.append((grow.id, round(hours, 1)))
        if hours:
            if grow.pic > 0:
                raise BackfillError(
                    f"flight {grow.id} ({grow.date}, {grow.aircraft}) logs "
                    f"{grow.pic:.1f} h PIC; SIC-to-PIC cannot overlap PIC"
                )
            by_aircraft[grow.aircraft] += hours
    plan.leftover_grist = [r for rows in buckets.values() for r in rows]
    plan.by_aircraft = {k: round(v, 1) for k, v in sorted(by_aircraft.items())}
    return plan


def check_gate(plan: Plan) -> None:
    """Hard refusal unless every reconciliation figure matches exactly."""
    if plan.unmatched_workbook:
        sample = ", ".join(
            f"{r.date} {r.code} {r.tail} {r.block}" for r in plan.unmatched_workbook[:5])
        raise BackfillError(
            f"{len(plan.unmatched_workbook)} workbook rows did not match a Grist "
            f"flight: {sample}"
        )
    got = {k: tenths(v) for k, v in plan.by_aircraft.items()}
    want = {k: tenths(v) for k, v in EXPECTED_BY_AIRCRAFT.items()}
    if got != want:
        lines = [
            f"  {ac:8s} got {got.get(ac, 0) / 10:7.1f}  expected {want[ac] / 10:7.1f}"
            for ac in sorted(set(got) | set(want))
        ]
        raise BackfillError(
            "SIC-to-PIC reconciliation failed; nothing written:\n" + "\n".join(lines)
        )
    if tenths(plan.total) != tenths(EXPECTED_TOTAL):
        raise BackfillError(
            f"SIC-to-PIC total {plan.total:.1f} h, expected {EXPECTED_TOTAL}"
        )
    if tenths(plan.pf_all) != tenths(EXPECTED_PF_ALL):
        raise BackfillError(f"PF total {plan.pf_all:.1f} h, expected {EXPECTED_PF_ALL}")
    if tenths(plan.pf_excl_school) != tenths(EXPECTED_PF_EXCL_SCHOOL):
        raise BackfillError(
            f"PF excluding flight school {plan.pf_excl_school:.1f} h, "
            f"expected {EXPECTED_PF_EXCL_SCHOOL}"
        )


CHUNK = 250


def apply_plan(client: GristClient, plan: Plan) -> int:
    """Write SIC_to_PIC. Caller must have run ``check_gate`` first.

    Only rows that actually carry supervised SIC time are written. A blank
    Numeric already reads as 0.0 everywhere (and the 2026+ rows the importer
    writes leave it blank), so PATCHing an explicit 0.0 onto the other legacy
    rows would change nothing except to fire the ``Edited`` trigger formula on
    them. Every record in a chunk carries the identical field set, which is
    what Grist's PATCH requires.
    """
    updates: list[tuple[int, dict[str, Any]]] = [
        (rid, {"SIC_to_PIC": value}) for rid, value in plan.nonzero
    ]
    for start in range(0, len(updates), CHUNK):
        client.update_records("Flights", updates[start:start + CHUNK])
    return len(updates)
