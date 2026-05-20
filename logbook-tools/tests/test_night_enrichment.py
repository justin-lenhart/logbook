from datetime import date, datetime, timedelta, timezone

from logbook_import.night_enrichment import civil_twilight_times, compute_night_data

# Minneapolis-Saint Paul International Airport
_LAT = 44.882
_LON = -93.222
_DATE = date(2026, 5, 9)


def test_civil_twilight_times_returns_utc_aware() -> None:
    dawn, dusk = civil_twilight_times(_LAT, _LON, _DATE)
    assert dawn.tzinfo is not None
    assert dusk.tzinfo is not None
    assert dawn.utcoffset() == timedelta(0)
    assert dusk.utcoffset() == timedelta(0)
    # For a US Central location, dusk falls early in the UTC day (evening CDT
    # converted to UTC), and dawn follows later that same UTC morning.
    assert dusk < dawn


def test_daytime_flight_no_night() -> None:
    # 11:00–12:00 UTC = 6–7 AM CDT on May 9.  Dawn at MSP is ~10:17 UTC, so
    # this flight starts after dawn and ends well before dusk.
    out = datetime(2026, 5, 9, 11, 0, tzinfo=timezone.utc)
    inn = datetime(2026, 5, 9, 12, 0, tzinfo=timezone.utc)
    night_hours, day_landing, night_landing = compute_night_data(
        out, inn, _LAT, _LON, _LAT, _LON, True
    )
    assert night_hours == 0.0
    assert day_landing == 1
    assert night_landing == 0


def test_nighttime_flight_full_night() -> None:
    # 06:00–07:00 UTC = 1–2 AM CDT on May 9.  Dusk at MSP is ~02:00 UTC and
    # dawn is ~10:17 UTC (same UTC day), so the entire 1-hour flight is dark.
    out = datetime(2026, 5, 9, 6, 0, tzinfo=timezone.utc)
    inn = datetime(2026, 5, 9, 7, 0, tzinfo=timezone.utc)
    night_hours, day_landing, night_landing = compute_night_data(
        out, inn, _LAT, _LON, _LAT, _LON, True
    )
    assert night_hours == 1.0
    assert day_landing == 0
    assert night_landing == 1


def test_partial_night_departure_at_dusk() -> None:
    # Build a flight that straddles dusk: depart 1 hour before dusk, arrive 1
    # hour after.  The night portion should be exactly the second hour (~1.0 h).
    dawn, dusk = civil_twilight_times(_LAT, _LON, _DATE)
    out = dusk - timedelta(hours=1)
    inn = dusk + timedelta(hours=1)
    assert inn < dawn  # arrival is still before dawn, so night window is valid
    night_hours, day_landing, night_landing = compute_night_data(
        out, inn, _LAT, _LON, _LAT, _LON, True
    )
    # Night portion runs from dusk to arrival = 1 hour (not the full 2 h block).
    assert night_hours == 1.0
    # Arrived after dusk → night landing.
    assert day_landing == 0
    assert night_landing == 1


def test_no_landing_credit() -> None:
    # Nighttime flight on an odd-numbered (PIC) leg: user gets night time logged
    # but no landing credit.
    out = datetime(2026, 5, 9, 6, 0, tzinfo=timezone.utc)
    inn = datetime(2026, 5, 9, 7, 0, tzinfo=timezone.utc)
    night_hours, day_landing, night_landing = compute_night_data(
        out, inn, _LAT, _LON, _LAT, _LON, False
    )
    assert night_hours > 0.0  # night time is still recorded
    assert day_landing == 0
    assert night_landing == 0
