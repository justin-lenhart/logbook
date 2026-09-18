"""Parse SkyWest RSR (Regional Scheduling Representative) system-wide reports.

Each system-wide report carries a 13-month rolling history per fleet for eight
pairing-efficiency metrics. We read the text layer (``pdftotext -layout``) and
anchor on the metric row labels:

    Cr / DP, CR / Day, Bk / DP, Bk / Day        H:MM  (higher is better)
    TAFB / Bk, TAFB / Cr, Duty / Bk, Duty / Cr  ratio (lower is better)

Month headers in the PDFs contain typos (e.g. "Oct Oct Dec"), so column months
are derived from the report's bid month instead: the last column is the bid
month and the 12 before it step back one month each. A value of 0:00 / 0.00
means the fleet had no pairings that month and is returned as ``None``.

Domicile reports (DFW/MSP/ORD) do not include these eight metrics; parsing
them yields no rows.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

COLUMNS = 13

MONTHS = {
    m: i
    for i, m in enumerate(
        ["January", "February", "March", "April", "May", "June", "July",
         "August", "September", "October", "November", "December"],
        start=1,
    )
}

# Heading text before "System-Wide Data" -> RSR fleet bucket.
FLEETS = {
    "CRJ 200": "CRJ200",
    "CRJ 550": "CRJ550",
    "CRJ 700, & 900": "CRJ7&9",
    "E175": "E175",
}

# Row label (lower-cased, spaces removed) -> Grist column id.
METRICS = {
    "cr/dp": "Cr_per_DP",
    "cr/day": "Cr_per_Day",
    "bk/dp": "Bk_per_DP",
    "bk/day": "Bk_per_Day",
    "tafb/bk": "TAFB_per_Bk",
    "tafb/cr": "TAFB_per_Cr",
    "duty/bk": "Duty_per_Bk",
    "duty/cr": "Duty_per_Cr",
}

_BID_MONTH_RE = re.compile(r"System-Wide Report on .+? for (\w+) (\d{4}) Bid Month")
_FLEET_RE = re.compile(r"^\s*(.+?)\s+System-Wide Data\s*$")
_ROW_RE = re.compile(
    r"^\s*(Cr\s*/\s*DP|CR\s*/\s*Day|Bk\s*/\s*DP|Bk\s*/\s*Day|"
    r"TAFB\s*/\s*Bk|TAFB\s*/\s*Cr|Duty\s*/\s*Bk|Duty\s*/\s*Cr)\s+(.+?)\s*$",
    re.IGNORECASE,
)
_HHMM_RE = re.compile(r"^(\d+):([0-5]\d)$")
_DECIMAL_RE = re.compile(r"^\d+\.\d+$")


class RsrParseError(ValueError):
    pass


@dataclass
class RsrMonth:
    scope: str
    fleet: str
    data_month: str  # YYYY-MM
    report_month: str  # YYYY-MM (bid month of the report it came from)
    metrics: dict[str, float | None] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        return f"{self.scope}|{self.fleet}|{self.data_month}"

    @property
    def is_oldest_column(self) -> bool:
        """The year-ago column: where every known bad RSR value has appeared."""
        year, month = map(int, self.report_month.split("-"))
        return column_months(year, month)[0] == self.data_month


def pdf_to_text(path: Path) -> str:
    result = subprocess.run(
        ["pdftotext", "-layout", str(path), "-"],
        check=True, capture_output=True, text=True,
    )
    return result.stdout


def parse_value(token: str) -> float | None:
    """H:MM -> decimal hours, ratio -> float; zero means 'no data'."""
    if m := _HHMM_RE.match(token):
        value = int(m.group(1)) + int(m.group(2)) / 60
    elif _DECIMAL_RE.match(token):
        value = float(token)
    else:
        raise RsrParseError(f"unrecognised RSR value {token!r}")
    return None if value == 0 else round(value, 4)


def column_months(bid_year: int, bid_month: int) -> list[str]:
    months = []
    for back in range(COLUMNS - 1, -1, -1):
        idx = bid_year * 12 + (bid_month - 1) - back
        months.append(f"{idx // 12:04d}-{idx % 12 + 1:02d}")
    return months


def bid_month_of(text: str) -> tuple[int, int]:
    m = _BID_MONTH_RE.search(text)
    if not m or m.group(1) not in MONTHS:
        raise RsrParseError("no 'System-Wide Report on … for <Month> <Year> Bid Month' line")
    return int(m.group(2)), MONTHS[m.group(1)]


def parse_rsr_text(text: str, *, scope: str = "SYS") -> list[RsrMonth]:
    """Return one ``RsrMonth`` per (fleet, month) with every metric found."""
    if "All Domiciles" not in text[:2000]:
        return []  # domicile report: no efficiency-ratio pages
    year, month = bid_month_of(text)
    report_month = f"{year:04d}-{month:02d}"
    months = column_months(year, month)

    rows: dict[tuple[str, str], RsrMonth] = {}
    fleet: str | None = None
    for line in text.splitlines():
        if m := _FLEET_RE.match(line):
            fleet = FLEETS.get(m.group(1).strip())
            continue
        m = _ROW_RE.match(line)
        if not m or fleet is None:
            continue
        label = re.sub(r"\s+", "", m.group(1)).lower()
        tokens = m.group(2).split()
        if not any(_HHMM_RE.match(t) or _DECIMAL_RE.match(t) for t in tokens):
            continue  # chart legend line ("Bk / Day   Cr / DP ..."), not data
        if len(tokens) != COLUMNS:
            raise RsrParseError(
                f"{fleet} {m.group(1)}: expected {COLUMNS} values, got {len(tokens)}"
            )
        column = METRICS[label]
        for data_month, token in zip(months, tokens):
            row = rows.setdefault(
                (fleet, data_month),
                RsrMonth(scope, fleet, data_month, report_month),
            )
            value = parse_value(token)
            if column in row.metrics and row.metrics[column] != value:
                raise RsrParseError(
                    f"{fleet} {data_month} {column}: conflicting values in one report"
                )
            row.metrics[column] = value

    incomplete = [r.key for r in rows.values() if len(r.metrics) != len(METRICS)]
    if not rows:
        raise RsrParseError("system-wide report but no metric rows found")
    if incomplete:
        raise RsrParseError(f"missing metrics for {', '.join(sorted(incomplete)[:5])}")
    for row in rows.values():
        _drop_impossible_per_day(row)
    return sorted(rows.values(), key=lambda r: (r.fleet, r.data_month))


def _drop_impossible_per_day(row: RsrMonth) -> None:
    """Days >= duty periods, so a per-day value can never exceed its per-DP value.

    The oldest column of every system report so far carries a bad CRJ550
    Bk/Day (e.g. 4:26 vs Bk/DP 4:21); newer reports show the real ~3:36.
    Blank the impossible value so it never overwrites a good one.
    """
    for per_day, per_dp in (("Cr_per_Day", "Cr_per_DP"), ("Bk_per_Day", "Bk_per_DP")):
        day, dp = row.metrics.get(per_day), row.metrics.get(per_dp)
        if day is not None and dp is not None and day > dp:
            row.warnings.append(
                f"{row.key}: {per_day} {day:.2f} > {per_dp} {dp:.2f} in the "
                f"{row.report_month} report — ignored"
            )
            row.metrics[per_day] = None


def parse_rsr_pdf(path: Path) -> list[RsrMonth]:
    return parse_rsr_text(pdf_to_text(path))
