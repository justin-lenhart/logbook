"""RSR system-wide report parsing and RSR_Metrics payload merging."""

from __future__ import annotations

import pytest

from logbook_import.grist_client import GristClient, UpsertResult
from logbook_import.grist_rsr import FILL_ONLY, build_payloads, sync_rsr
from logbook_import.grist_settings import GristSettings
from logbook_import.parsers.rsr_pdf import (
    RsrParseError,
    column_months,
    parse_rsr_text,
    parse_value,
)

MONTH_HEADER = "      Oct  Oct  Dec  Jan  Feb  Mar  Apr  May  Jun  Jul  Aug  Sep  Oct\n"


def _report(bid: str = "October 2026", cr200_bk_day: str = "3:54") -> str:
    time_vals = "5:03 5:07 5:05 5:13 5:11 4:56 4:53 4:55 4:50 4:45 4:52 4:56 5:04"
    zero_vals = "5:10 4:59 0:00 0:00 0:00 0:00 5:11 5:13 5:04 4:58 5:05 5:11 5:16"
    bk_dp = "4:30 4:32 4:26 4:29 4:22 4:19 4:20 4:31 4:21 4:13 4:21 4:08 4:18"
    bk_day = f"4:03 4:01 3:53 3:52 3:47 3:53 4:02 4:10 4:03 3:58 4:00 3:45 {cr200_bk_day}"
    ratio = "4.06 3.98 4.03 4.01 4.10 4.22 4.23 4.08 4.25 4.36 4.25 4.43 4.33"
    ratio_zero = "3.88 3.93 0.00 0.00 0.00 0.00 3.89 3.88 3.88 3.98 4.05 4.09 4.16"

    def fleet(name: str, t: str, r: str, dp: str, day: str) -> str:
        return (
            f"   System-Wide Report on ALL Aircraft for {bid} Bid Month\n"
            f"            {name} System-Wide Data\n{MONTH_HEADER}"
            f"   Cr / DP   {t}\n  CR / Day   {t}\n   Bk / DP   {dp}\n  Bk / Day   {day}\n"
            "        Bk / Day     Cr / DP     CR / Day     Bk / DP\n"
            f"            {name} System-Wide Data\n{MONTH_HEADER}"
            f"  TAFB / Bk  {r}\n  TAFB / Cr  {r}\n  Duty / Bk  {r}\n   Duty / Cr {r}\n"
        )

    return (
        "  Regional Scheduling Representative Report\n"
        "      All Domiciles, All Aircraft Types\n"
        + fleet("CRJ 200", time_vals, ratio, bk_dp, bk_day)
        + fleet("CRJ 550", zero_vals, ratio_zero, zero_vals, zero_vals)
    )


def test_parse_value() -> None:
    assert parse_value("4:30") == 4.5
    assert parse_value("3.71") == 3.71
    assert parse_value("0:00") is None
    assert parse_value("0.00") is None
    with pytest.raises(RsrParseError):
        parse_value("N/A")


def test_column_months_cross_year() -> None:
    months = column_months(2026, 10)
    assert months[0] == "2025-10" and months[-1] == "2026-10" and len(months) == 13
    assert column_months(2026, 1)[0] == "2025-01"


def test_months_come_from_bid_month_not_typo_header() -> None:
    rows = parse_rsr_text(_report())
    cr200 = [r for r in rows if r.fleet == "CRJ200"]
    # Header says "Oct Oct Dec" — the second column is still November.
    assert [r.data_month for r in cr200][:3] == ["2025-10", "2025-11", "2025-12"]
    assert all(r.report_month == "2026-10" for r in rows)


def test_parses_both_pages_and_skips_legend() -> None:
    rows = {r.key: r for r in parse_rsr_text(_report())}
    last = rows["SYS|CRJ200|2026-10"].metrics
    assert last["Cr_per_DP"] == pytest.approx(5 + 4 / 60, abs=1e-4)
    assert last["TAFB_per_Cr"] == 4.33
    assert len(last) == 8


def test_zero_months_are_blank() -> None:
    rows = {r.key: r for r in parse_rsr_text(_report())}
    assert all(v is None for v in rows["SYS|CRJ550|2025-12"].metrics.values())


def test_per_day_above_per_dp_is_dropped_with_warning() -> None:
    rows = {r.key: r for r in parse_rsr_text(_report(cr200_bk_day="4:26"))}
    row = rows["SYS|CRJ200|2026-10"]  # Bk/DP 4:18 < Bk/Day 4:26: impossible
    assert row.metrics["Bk_per_Day"] is None
    assert row.warnings and "Bk_per_Day" in row.warnings[0]


def test_domicile_report_yields_nothing() -> None:
    assert parse_rsr_text("Regional Scheduling Representative Report\n DFW CRJ\n") == []


def test_wrong_column_count_raises() -> None:
    bad = _report().replace("4.06 3.98", "4.06", 1)
    with pytest.raises(RsrParseError, match="expected 13"):
        parse_rsr_text(bad)


def test_build_payloads_newest_value_wins_and_blanks_never_clear() -> None:
    older = parse_rsr_text(_report(bid="September 2026"))
    newer = parse_rsr_text(_report(bid="October 2026", cr200_bk_day="4:26"))
    payloads = {
        p["Key"]: p
        for p in build_payloads(older + newer, {"2026-09": "sep.pdf", "2026-10": "oct.pdf"})
    }
    # Sep 2026 appears in both; the October report is newer and wins.
    sep = payloads["SYS|CRJ200|2026-09"]
    assert sep["Report_Month"] == "2026-10" and sep["Source_File"] == "oct.pdf"
    # Oct 2026 Bk/Day was dropped as impossible, so it is absent, not None.
    assert "Bk_per_Day" not in payloads["SYS|CRJ200|2026-10"]
    assert all(v is not None for p in payloads.values() for v in p.values())
    assert not payloads["SYS|CRJ200|2026-09"][FILL_ONLY]
    # CRJ550 months with no data in any report produce no row at all.
    assert "SYS|CRJ550|2025-12" not in payloads


def test_oldest_column_only_fills_gaps() -> None:
    # The Oct-2026 report's oldest column is Oct 2025; a Sep-2026 report also
    # covers Oct 2025 in a non-oldest column, so that one must win.
    sep = parse_rsr_text(_report(bid="September 2026"))
    oct_ = parse_rsr_text(_report(bid="October 2026"))
    payloads = {p["Key"]: p for p in build_payloads(sep + oct_, {})}
    assert payloads["SYS|CRJ200|2025-10"]["Report_Month"] == "2026-09"
    # Sep 2025 exists only as the Sep report's oldest column: still used.
    assert payloads["SYS|CRJ200|2025-09"]["Report_Month"] == "2026-09"


class _RecordingClient(GristClient):
    def __init__(self, existing: set[str]) -> None:
        super().__init__(GristSettings(url="http://t", api_key="k", doc_id="d"))
        self.existing = existing
        self.written: list[dict] = []

    def fetch_key_index(self, table, key_col, keys):  # type: ignore[override]
        return {k: 1 for k in keys if k in self.existing}

    def upsert_by_key(self, table, payloads, key_col):  # type: ignore[override]
        self.written = payloads
        return UpsertResult()


def test_sync_never_overwrites_stored_month_from_oldest_column() -> None:
    # A lone Oct-2026 report: its oldest column (Oct 2025) must not replace a
    # stored row, but may create one that does not exist yet.
    payloads = build_payloads(parse_rsr_text(_report(bid="October 2026")), {})
    client = _RecordingClient(existing={"SYS|CRJ200|2025-10"})
    sync_rsr(client, payloads)
    keys = {p["Key"] for p in client.written}
    assert "SYS|CRJ200|2025-10" not in keys
    assert "SYS|CRJ550|2025-10" in keys  # not stored yet: gap gets filled
    assert all(FILL_ONLY not in p for p in client.written)
