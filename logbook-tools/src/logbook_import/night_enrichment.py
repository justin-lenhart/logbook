from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from astral import LocationInfo, Observer
from astral.sun import elevation, sun


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


# Night (14 CFR 1.1): the time between the end of evening civil twilight and
# the beginning of morning civil twilight, i.e. the sun's centre more than 6
# degrees below the horizon.
_CIVIL_TWILIGHT_ELEVATION = -6.0
_SAMPLE_SECONDS = 60


def _is_dark(lat: float, lon: float, at_utc: datetime) -> bool:
    """True if the sun is below civil twilight at this place and instant."""
    return elevation(Observer(lat, lon), at_utc, with_refraction=False) < _CIVIL_TWILIGHT_ELEVATION


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

    The flight is sampled once a minute (at each minute's midpoint) at a
    position interpolated between origin and destination, and each sample is
    tested against the sun's elevation directly.

    An earlier version built one [dusk, dawn] window per UTC calendar date and
    dropped it when dusk was not earlier than dawn on that date. That only
    holds while evening dusk falls after 0000Z (US summer); from autumn on,
    dusk falls before 0000Z and every flight came out with zero night. Testing
    the sun's elevation has no calendar-date dependence at all.
    """
    total_seconds = (in_utc - out_utc).total_seconds()
    if total_seconds <= 0:
        return 0.0
    dark = 0.0
    start = 0.0
    while start < total_seconds:
        step = min(_SAMPLE_SECONDS, total_seconds - start)
        frac = (start + step / 2) / total_seconds
        lat = origin_lat + (dest_lat - origin_lat) * frac
        lon = origin_lon + (dest_lon - origin_lon) * frac
        if _is_dark(lat, lon, out_utc + timedelta(seconds=start + step / 2)):
            dark += step
        start += step
    return dark


def _is_night_arrival(
    in_utc: datetime,
    dest_lat: float,
    dest_lon: float,
) -> bool:
    """True if the arrival falls between the end of evening civil twilight and
    the beginning of morning civil twilight at the destination."""
    return _is_dark(dest_lat, dest_lon, in_utc)


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

    Naive datetimes are treated as UTC.

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
