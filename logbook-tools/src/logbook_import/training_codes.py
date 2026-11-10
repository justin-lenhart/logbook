"""Parse military training event codes out of the historical logbook remarks.

The pre-2026 logbook recorded the flight's training events as 4-digit codes
concatenated into one field. A spreadsheet somewhere along the way stored that
field as a *number*, so the remark arrives in Grist as a digit string -- and,
once it grows past what a float can hold exactly, as scientific notation.

``Flights.Notes`` holds them as ``Logbook remark: <text>``. This module
rewrites that field to the comma-separated codes alone. A separate stored
column for them would only duplicate Notes, so there isn't one.

What survives
-------------
Up to 16 digits the value is stored exactly (2^53 covers every 16-digit
integer), so 4 / 8 / 12 / 16-digit remarks split cleanly and lose nothing. The
trailing zeros in those are real code endings, not padding: ``6300610219016100``
is 6300 / 6102 / 1901 / 6100.

Beyond that the value went through a float and only the leading ~15 significant
decimal digits are trustworthy. Rounding the literal to 15 significant digits
repairs the float's artifacts in both directions -- ``...0022999`` back to
``...0023000`` and ``...29001`` back to ``...29000`` -- after which the first
four codes are sound and everything past them is zero padding. So
``2.8002100230029001E+19`` yields 2800 / 2300 / 2100 / 2900 and drops the rest.

Flight-school remarks are free text ("IFS, 5R4") and are left alone. This
module deliberately has no code-to-description lookup: that mapping is the
pilot's to maintain and is a separate request.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from logbook_import.grist_client import GristClient
from logbook_import.profile_data import parse_remark

CODE_LEN = 4

# IEEE-754 double precision guarantees 15 significant decimal digits.
RELIABLE_DIGITS = 15

_DIGITS = re.compile(r"\d+")
_JOINED = re.compile(r"\d{4}(?:\s*,\s*\d{4})*")   # already-parsed codes
_SCIENTIFIC = re.compile(r"\d(?:\.\d+)?[Ee][+-]?\d+")

EXACT = "exact"                  # stored losslessly, every code survives
RECONSTRUCTED = "reconstructed"  # went through a float; tail dropped
TEXT = "text"                    # flight school free text, left alone
EMPTY = "empty"                  # no remark


@dataclass(frozen=True)
class ParsedRemark:
    """Codes recovered from one remark, and what had to be thrown away."""

    kind: str
    codes: tuple[str, ...] = ()
    dropped: int = 0

    @property
    def joined(self) -> str:
        return ", ".join(self.codes)


def _split(digits: str) -> list[str]:
    return [digits[i:i + CODE_LEN] for i in range(0, len(digits), CODE_LEN)]


def _reconstruct(remark: str) -> ParsedRemark:
    """Recover the digit string from a scientific-notation remark.

    The literal text is read with ``Decimal`` (so no further float error is
    introduced), rounded to the 15 significant digits a double can be trusted
    for, then zero-padded back to its true magnitude. Codes that start beyond
    the reliable region are padding and are dropped.
    """
    value = Decimal(remark)
    magnitude = value.adjusted() + 1                 # total digits in the integer
    if magnitude <= RELIABLE_DIGITS:                 # nothing was ever lost
        digits = str(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))
    else:
        shift = magnitude - RELIABLE_DIGITS
        rounded = value.scaleb(-shift).quantize(Decimal(1), rounding=ROUND_HALF_UP)
        digits = str(rounded) + "0" * shift
    groups = _split(digits)
    # Keep a code only if it begins inside the reliable digits; the rest is
    # zero padding that happens to look like codes.
    keep = [g for i, g in enumerate(groups) if i * CODE_LEN < RELIABLE_DIGITS]
    return ParsedRemark(RECONSTRUCTED, tuple(keep), len(groups) - len(keep))


def parse_codes(remark: str | None) -> ParsedRemark:
    """Classify one remark and pull its 4-digit codes out of it."""
    text = (remark or "").strip()
    if not text:
        return ParsedRemark(EMPTY)
    if _DIGITS.fullmatch(text):
        groups = _split(text)
        # A trailing partial group cannot be a 4-digit code; drop it.
        whole = [g for g in groups if len(g) == CODE_LEN]
        return ParsedRemark(EXACT, tuple(whole), len(groups) - len(whole))
    if _SCIENTIFIC.fullmatch(text):
        return _reconstruct(text)
    if _JOINED.fullmatch(text):
        # Already cleaned on an earlier run: re-reading must be a no-op.
        return ParsedRemark(EXACT, tuple(c.strip() for c in text.split(",")))
    return ParsedRemark(TEXT)


def parse_notes(notes: str | None) -> ParsedRemark:
    """``Flights.Notes`` -> the codes in its ``Logbook remark:`` line."""
    return parse_codes(parse_remark(notes))


NOTES_SQL = """
SELECT f.id AS id, f."Notes" AS notes
FROM "Flights" f
WHERE f."Legacy_Summary"
ORDER BY f.id
"""


@dataclass
class CodePlan:
    """What a training-code backfill would write, per row id."""

    updates: list[tuple[int, dict[str, Any]]]
    counts: dict[str, int]
    dropped: int
    codes_written: int
    notes_cleaned: int
    rows_with_codes: int = 0

    @property
    def rows(self) -> int:
        return len(self.updates)

    @property
    def code_rows(self) -> int:
        return self.rows_with_codes


def clean_notes(remark: str, parsed: ParsedRemark) -> str:
    """What ``Notes`` should hold once the import provenance is dropped.

    Every historical row carried a "Historical line-item import from ..."
    preamble. It says nothing a reader needs -- all of the pre-2026 flights
    came from that one workbook -- and the proportional-distribution caveat it
    mentions is documented in ``docs/historical-logbook-import.md`` and printed
    on every export as ``SYNTHETIC_NOTE``. So the field keeps the remark alone:
    the training codes where there are any, the pilot's own words otherwise.
    """
    if parsed.codes:
        return parsed.joined
    return remark if parsed.kind == TEXT else ""


def build_plan(rows: list[dict[str, Any]]) -> CodePlan:
    updates: list[tuple[int, dict[str, Any]]] = []
    counts: dict[str, int] = {EXACT: 0, RECONSTRUCTED: 0, TEXT: 0, EMPTY: 0}
    dropped = written = cleaned = 0
    for row in rows:
        notes = row.get("notes") or ""
        remark = parse_remark(notes)
        parsed = parse_codes(remark)
        counts[parsed.kind] = counts.get(parsed.kind, 0) + 1
        dropped += parsed.dropped

        fields: dict[str, Any] = {}
        if parsed.codes:
            written += len(parsed.codes)
        wanted = clean_notes(remark, parsed)
        if wanted != notes:
            fields["Notes"] = wanted
            cleaned += 1
        if fields:
            updates.append((int(row["id"]), fields))
    with_codes = sum(1 for row in rows if parse_codes(parse_remark(row.get("notes") or "")).codes)
    return CodePlan(updates, counts, dropped, written, cleaned, with_codes)


def load_plan(client: GristClient) -> CodePlan:
    return build_plan(client.sql(NOTES_SQL))


CHUNK = 250


def apply_plan(client: GristClient, plan: CodePlan) -> int:
    """Write the cleaned Notes. Every record carries the same single field,
    which is what Grist's uniform-field-set rule requires."""
    for start in range(0, len(plan.updates), CHUNK):
        client.update_records("Flights", plan.updates[start:start + CHUNK])
    return len(plan.updates)
