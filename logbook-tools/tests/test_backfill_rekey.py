import importlib.util
import sys
from datetime import date
from pathlib import Path

from logbook_import.grist_mapper import format_grist_date

_spec = importlib.util.spec_from_file_location(
    "backfill", Path(__file__).resolve().parents[1] / "scripts" / "backfill_duty_tz_tafb.py"
)
backfill = importlib.util.module_from_spec(_spec)
sys.modules["backfill"] = backfill  # dataclasses need the module registered
_spec.loader.exec_module(backfill)


def test_rekey_strips_suffix_from_first_segment_only() -> None:
    assert backfill.rekey("E3436D|2026-06-11") == "E3436|2026-06-11"
    assert backfill.rekey("E3405A|2026-06-01|2026-06-02") == "E3405|2026-06-01|2026-06-02"
    assert backfill.rekey("E3058E|2026-05-09|4266|MSP|INL|1252") == "E3058|2026-05-09|4266|MSP|INL|1252"
    assert backfill.rekey("T4729C|2026-08-12|Actual") == "T4729|2026-08-12|Actual"
    # Unchanged: already suffix-free, 5-char ids ending in a letter, HIST keys.
    for key in ("E3405|2026-06-01", "E3A08|2026-05-19", "HIST-0001", "", "E3436D"):
        assert backfill.rekey(key) == key


def test_rekey_pairing_id() -> None:
    assert backfill.rekey_pairing_id("O1262A") == "O1262"
    assert backfill.rekey_pairing_id("E3A08") == "E3A08"
    assert backfill.rekey_pairing_id("E3405") == "E3405"


def test_find_collisions() -> None:
    rows = [
        (14, "E3405A|2026-06-01|2026-06-01"),
        (1, "E3405|2026-06-01|2026-06-01"),
        (2, "E3436D|2026-06-11|2026-06-11"),
        (3, "E3436|2026-06-25|2026-06-25"),   # same pairing, other date: distinct
        (4, "E3412|2026-06-17|2026-06-17"),
    ]
    assert backfill.find_collisions(rows) == {
        "E3405|2026-06-01|2026-06-01": [(14, "E3405A|2026-06-01|2026-06-01"),
                                        (1, "E3405|2026-06-01|2026-06-01")],
    }


def test_missing_days_to_cancel() -> None:
    today = date(2026, 7, 10)
    rows = [
        {"key": "O1262|2026-07-02|2026-07-02", "status": "Actual", "date": format_grist_date(date(2026, 7, 2))},
        {"key": "O1262|2026-07-02|2026-07-04", "status": "Planned", "date": format_grist_date(date(2026, 7, 4))},
        {"key": "O1262|2026-07-02|2026-07-05", "status": "Replaced", "date": format_grist_date(date(2026, 7, 5))},
        {"key": "O1262|2026-07-02|2026-07-11", "status": "Planned", "date": format_grist_date(date(2026, 7, 11))},
    ]
    out = backfill.missing_days_to_cancel(rows, {"O1262|2026-07-02|2026-07-02"}, today)
    assert [r["key"] for r in out] == ["O1262|2026-07-02|2026-07-04"]
