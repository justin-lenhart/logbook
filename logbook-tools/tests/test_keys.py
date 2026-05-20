from datetime import date, time

from logbook_import.keys import duty_period_key, import_flight_key, trip_key


def test_trip_key() -> None:
    assert trip_key("E3058E", date(2026, 5, 9)) == "E3058E|2026-05-09"


def test_duty_period_key() -> None:
    assert (
        duty_period_key("E3058E", date(2026, 5, 9), date(2026, 5, 10))
        == "E3058E|2026-05-09|2026-05-10"
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
        == "E3058E|2026-05-09|4266|MSP|INL|1252"
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
        == "E3058E|2026-05-12|4298|ATY|MSP|0701"
    )
