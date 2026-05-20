from __future__ import annotations

from datetime import date, datetime, timezone

from astral import LocationInfo
from astral.sun import sun


def civil_twilight_times(
    lat: float,
    lon: float,
    for_date: date,
) -> tuple[datetime, datetime]:
    """
    Return (dawn_utc, dusk_utc) — civil twilight begin and end — for a given
    lat/lon and calendar date, both as UTC-aware datetimes.

    For US locations in summer, dusk falls very early in the UTC calendar day
    (e.g., 02:00 UTC = 9 PM CDT the "previous" evening) and dawn falls later
    that same UTC day (e.g., 10:17 UTC = 5:17 AM CDT).  So dusk < dawn within
    the returned pair.

    Raises ValueError if the sun does not cross the civil twilight horizon
    (e.g., polar regions in summer or winter).
    """
    location = LocationInfo(latitude=lat, longitude=lon)
    try:
        s = sun(location.observer, date=for_date, tzinfo=timezone.utc)
    except ValueError as exc:
        raise ValueError(
            f"Cannot compute twilight at lat={lat}, lon={lon}, date={for_date}: {exc}"
        ) from exc
    return s["dawn"], s["dusk"]


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _night_overlap_seconds(
    out_utc: datetime,
    in_utc: datetime,
    origin_lat: float,
    origin_lon: float,
    dest_lat: float,
    dest_lon: float,
) -> float:
    """
    Return the total seconds during [out_utc, in_utc] that fall in darkness.

    For each UTC calendar day touched by the flight, we compute the night
    window as [dusk, dawn] for that date.  For US airports the two values are
    on the same UTC day (dusk ≈ 02:xx, dawn ≈ 10:xx).  We sum any overlaps
    from every day the flight spans.
    """
    total = 0.0
    checked: set[date] = set()
    for dt in (out_utc, in_utc):
        d = dt.date()
        if d in checked:
            continue
        checked.add(d)
        try:
            _, dusk = civil_twilight_times(origin_lat, origin_lon, d)
            dawn, _ = civil_twilight_times(dest_lat, dest_lon, d)
        except ValueError:
            continue
        if dusk >= dawn:
            continue  # degenerate twilight (polar edge case)
        overlap_start = max(out_utc, dusk)
        overlap_end = min(in_utc, dawn)
        total += max(0.0, (overlap_end - overlap_start).total_seconds())
    return total


def _is_night_arrival(
    in_utc: datetime,
    dest_lat: float,
    dest_lon: float,
) -> bool:
    """
    True if the arrival time falls after civil twilight end and before civil
    twilight begin at the destination on the arrival UTC date.
    """
    try:
        dawn, dusk = civil_twilight_times(dest_lat, dest_lon, in_utc.date())
    except ValueError:
        return False
    if dusk >= dawn:
        return False  # polar edge case
    return dusk <= in_utc < dawn


def compute_night_data(
    out_time: datetime,
    in_time: datetime,
    origin_lat: float,
    origin_lon: float,
    dest_lat: float,
    dest_lon: float,
    gets_landing_credit: bool,
) -> tuple[float, int, int]:
    """
    Compute night time and landing credit for one flight leg.

    Returns (night_hours, day_landing, night_landing).
    - night_hours: decimal hours flown at night, rounded to 1 decimal place.
    - day_landing: 1 if gets_landing_credit and arrival is before civil twilight
      end at the destination; otherwise 0.
    - night_landing: 1 if gets_landing_credit and arrival is at or after civil
      twilight end at the destination; otherwise 0.

    Naive datetimes are treated as UTC.  If twilight data is unavailable (polar
    route or astral computation failure), returns (0.0, 0, 0).

    # TODO: Confirm SkyWest takeoff credit rule.  Currently assumes takeoffs
    # alternate on the same odd/even leg pattern as landings (PIC=odd, SIC=even).
    # Correct this once the FOM reference is verified.
    """
    out_utc = _ensure_utc(out_time)
    in_utc = _ensure_utc(in_time)

    night_seconds = _night_overlap_seconds(
        out_utc, in_utc, origin_lat, origin_lon, dest_lat, dest_lon
    )
    night_hours = round(night_seconds / 3600, 1)

    if not gets_landing_credit:
        return night_hours, 0, 0

    if _is_night_arrival(in_utc, dest_lat, dest_lon):
        return night_hours, 0, 1
    return night_hours, 1, 0
