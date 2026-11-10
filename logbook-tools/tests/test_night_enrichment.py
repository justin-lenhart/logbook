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


# --- Seasonal regression: evening dusk falls BEFORE 0000Z from autumn on -----
# The old per-UTC-date [dusk, dawn] window was discarded in that case and
# every flight logged zero night. Cases below are real 2026 legs.

_ORD = (41.9786, -87.9048)
_SBN = (41.7087, -86.3173)
_MSP = (44.882, -93.222)
_YYZ = (43.6772, -79.6306)
_GNV = (29.6900, -82.2718)
_PHX = (33.4343, -112.0116)
_SGF = (37.2457, -93.3886)
_UTC = timezone.utc


def test_autumn_dusk_before_midnight_utc() -> None:
    # In November, dusk at ORD is ~2300Z and dawn ~1200Z on the same UTC date.
    dawn, dusk = civil_twilight_times(*_ORD, date(2026, 11, 7))
    assert dusk > dawn


def test_autumn_evening_leg_logs_night() -> None:
    # 5674 ORD-SBN 07 Nov 2026, 2222Z-2316Z: lands after evening civil twilight.
    night, day_ldg, night_ldg = compute_night_data(
        datetime(2026, 11, 7, 22, 22, tzinfo=_UTC), datetime(2026, 11, 7, 23, 16, tzinfo=_UTC),
        *_ORD, *_SBN, True,
    )
    assert 0.1 <= night <= 0.4
    assert (day_ldg, night_ldg) == (0, 1)


def test_autumn_overnight_leg_is_all_night() -> None:
    # 3866 MSP-YYZ 31 Oct 2026, 0322Z-0517Z: entirely dark.
    night, day_ldg, night_ldg = compute_night_data(
        datetime(2026, 10, 31, 3, 22, tzinfo=_UTC), datetime(2026, 10, 31, 5, 17, tzinfo=_UTC),
        *_MSP, *_YYZ, True,
    )
    assert night == 1.9
    assert (day_ldg, night_ldg) == (0, 1)


def test_autumn_leg_crossing_midnight_utc_westbound() -> None:
    # 9917 GNV-PHX 25 Sep 2026, 2349Z-0405Z: departs after dusk at GNV and
    # chases the terminator west but never catches it.
    night, _, night_ldg = compute_night_data(
        datetime(2026, 9, 25, 23, 49, tzinfo=_UTC), datetime(2026, 9, 26, 4, 5, tzinfo=_UTC),
        *_GNV, *_PHX, True,
    )
    assert night == 4.3
    assert night_ldg == 1


def test_autumn_predawn_departure_partial_night() -> None:
    # 4073 YYZ-MSP 05 Oct 2026, 1006Z-1245Z: departs in the dark, lands in daylight.
    night, day_ldg, night_ldg = compute_night_data(
        datetime(2026, 10, 5, 10, 6, tzinfo=_UTC), datetime(2026, 10, 5, 12, 45, tzinfo=_UTC),
        *_YYZ, *_MSP, True,
    )
    assert 0.9 <= night <= 1.5
    assert (day_ldg, night_ldg) == (1, 0)


def test_autumn_midday_leg_has_no_night() -> None:
    # 5852 ORD-SGF 08 Nov 2026, 1431Z-1605Z: mid-morning local.
    night, day_ldg, night_ldg = compute_night_data(
        datetime(2026, 11, 8, 14, 31, tzinfo=_UTC), datetime(2026, 11, 8, 16, 5, tzinfo=_UTC),
        *_ORD, *_SGF, True,
    )
    assert (night, day_ldg, night_ldg) == (0.0, 1, 0)
