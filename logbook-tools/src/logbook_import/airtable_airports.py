from __future__ import annotations

from functools import lru_cache

from pyairtable import Api

from logbook_import import airtable_fields as F


@lru_cache(maxsize=1)
def _timezone_finder():
    from timezonefinder import TimezoneFinder

    return TimezoneFinder()


def _parse_coordinate(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def fetch_airport_index(api_key: str, base_id: str) -> dict[str, dict]:
    """
    Fetch the Airports table and return a lookup index keyed by IATA code.

    Each entry includes an IANA timezone (``tz``) computed from lat/lon, which
    downstream code uses to convert SkedPlus local times to UTC.
    """
    table = Api(api_key).base(base_id).table(F.TABLE_AIRPORTS)
    fields = [
        F.F_AIRPORT_IATA,
        F.F_AIRPORT_NAME,
        F.F_AIRPORT_CITY,
        F.F_AIRPORT_COUNTRY,
        F.F_AIRPORT_LAT,
        F.F_AIRPORT_LON,
    ]
    records = table.all(fields=fields)

    tf = _timezone_finder()

    index: dict[str, dict] = {}
    for record in records:
        row = record.get("fields", {})
        iata_raw = row.get(F.F_AIRPORT_IATA)
        if not iata_raw or not str(iata_raw).strip():
            continue
        iata = str(iata_raw).strip().upper()

        lat = _parse_coordinate(row.get(F.F_AIRPORT_LAT))
        lon = _parse_coordinate(row.get(F.F_AIRPORT_LON))
        if lat is None or lon is None:
            continue

        tz = tf.timezone_at(lat=lat, lng=lon) or ""

        index[iata] = {
            "name": str(row.get(F.F_AIRPORT_NAME) or ""),
            "city": str(row.get(F.F_AIRPORT_CITY) or ""),
            "country": str(row.get(F.F_AIRPORT_COUNTRY) or ""),
            "lat": lat,
            "lon": lon,
            "tz": tz,
        }
    return index
