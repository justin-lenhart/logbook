from datetime import date, time

from logbook_import.keys import (
    duty_period_key,
    import_flight_key,
    normalize_pairing_id,
    trip_key,
)


def test_normalize_pairing_id_strips_revision_suffix() -> None:
    # A trip revised/reflown gains a trailing revision letter past the 5-char base.
    assert normalize_pairing_id("E3405A") == "E3405"
    assert normalize_pairing_id("E3436D") == "E3436"
    assert normalize_pairing_id("O1414J") == "O1414"
    assert normalize_pairing_id("E3058E") == "E3058"


def test_normalize_pairing_id_preserves_base() -> None:
    # 5-char bases are never stripped, even when they end in a letter.
    assert normalize_pairing_id("E3405") == "E3405"
    assert normalize_pairing_id("E3A08") == "E3A08"
    assert normalize_pairing_id("e7748") == "E7748"


def test_trip_key_collapses_revision() -> None:
    # Planned (E3405) and the later actual (E3405A) share one Trip Key.
    assert trip_key("E3058E", date(2026, 5, 9)) == "E3058|2026-05-09"
    assert trip_key("E3405", date(2026, 6, 1)) == trip_key("E3405A", date(2026, 6, 1))


def test_duty_period_key() -> None:
    assert (
        duty_period_key("E3058E", date(2026, 5, 9), date(2026, 5, 10))
        == "E3058|2026-05-09|2026-05-10"
    )


def test_import_flight_key_example() -> None:
    assert (
        import_flight_key(
            "E3058E",
            date(2026, 5, 9),
            "4266",
            "MSP",
            "INL",
            time(12, 52),
        )
        == "E3058|2026-05-09|4266|MSP|INL|1252"
    )


def test_import_flight_key_strips_star_prefix() -> None:
    assert (
        import_flight_key(
            "E3058E",
            date(2026, 5, 12),
            "*4298",
            "ATY",
            "MSP",
            time(7, 1),
        )
        == "E3058|2026-05-12|4298|ATY|MSP|0701"
    )
