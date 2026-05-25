from __future__ import annotations

from collections import defaultdict

from pyairtable import Api

from logbook_import import airtable_fields as F

_FLIGHT_FORMULA = (
    "AND({Deadhead} != TRUE(), OR({PIC Time} > 0, {SIC Time} > 0))"
)


def _resolve_iata(raw: object, record_id_to_iata: dict[str, str]) -> str:
    """Resolve a departure/arrival field value to an IATA code.

    Airtable linked record fields return a list of record IDs; plain text
    fields return a string. Both formats are handled here.
    """
    if isinstance(raw, list):
        return record_id_to_iata.get(raw[0], "") if raw else ""
    return str(raw).strip().upper()


def fetch_flight_records(
    api_key: str,
    base_id: str,
    airport_index: dict[str, dict],
) -> list[dict]:
    """Fetch non-deadhead flown legs and return per-flight dicts.

    Each dict has keys: origin, dest, block (float|None), credit (float|None).
    """
    record_id_to_iata = {v["record_id"]: k for k, v in airport_index.items()}

    table = Api(api_key).base(base_id).table(F.TABLE_FLIGHTS)
    fields = [
        F.F_FLIGHT_DEPARTURE,
        F.F_FLIGHT_ARRIVAL,
        F.F_FLIGHT_DEADHEAD,
        F.F_FLIGHT_PIC_TIME,
        F.F_FLIGHT_SIC_TIME,
        F.F_FLIGHT_BLOCK_TIME,
        F.F_FLIGHT_CREDIT_TIME,
    ]
    records = table.all(fields=fields, formula=_FLIGHT_FORMULA)

    flights: list[dict] = []
    for record in records:
        row = record.get("fields", {})
        origin_raw = row.get(F.F_FLIGHT_DEPARTURE)
        dest_raw = row.get(F.F_FLIGHT_ARRIVAL)
        if not origin_raw or not dest_raw:
            continue
        origin = _resolve_iata(origin_raw, record_id_to_iata)
        dest = _resolve_iata(dest_raw, record_id_to_iata)
        if not origin or not dest:
            continue

        block_raw = row.get(F.F_FLIGHT_BLOCK_TIME)
        credit_raw = row.get(F.F_FLIGHT_CREDIT_TIME)

        flights.append({
            "origin": origin,
            "dest": dest,
            "block": float(block_raw) if block_raw is not None else None,
            "credit": float(credit_raw) if credit_raw is not None else None,
        })
    return flights


def aggregate_route_stats(
    flight_records: list[dict],
) -> dict[tuple[str, str], dict]:
    """Compute per-route stats from a list of flight dicts.

    Groups by normalized (sorted) route key. Returns a dict keyed by
    (origin, dest) tuple with keys: count, avg_block, min_block, max_block,
    avg_credit. Time values are decimal hours (float) or None if no data.
    """
    buckets: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for f in flight_records:
        key = tuple(sorted((f["origin"], f["dest"])))
        buckets[key].append(f)  # type: ignore[arg-type]

    stats: dict[tuple[str, str], dict] = {}
    for key, flights in buckets.items():
        blocks = [f["block"] for f in flights if f["block"] is not None]
        credits_ = [f["credit"] for f in flights if f["credit"] is not None]
        stats[key] = {
            "count": len(flights),
            "avg_block": sum(blocks) / len(blocks) if blocks else None,
            "min_block": min(blocks) if blocks else None,
            "max_block": max(blocks) if blocks else None,
            "avg_credit": sum(credits_) / len(credits_) if credits_ else None,
        }
    return stats


def resolve_airports(
    route_stats: dict[tuple[str, str], dict],
    airport_index: dict[str, dict],
) -> tuple[dict[str, dict], list[str]]:
    """Resolve IATA codes from route stats against the airport index.

    Returns (resolved, missing) where resolved maps IATA → airport dict
    and missing is a sorted list of codes not found in the index.
    """
    all_iata: set[str] = set()
    for origin, dest in route_stats:
        all_iata.add(origin)
        all_iata.add(dest)

    resolved = {code: airport_index[code] for code in all_iata if code in airport_index}
    missing = sorted(code for code in all_iata if code not in airport_index)
    return resolved, missing


def build_geojson(
    resolved: dict[str, dict],
    route_stats: dict[tuple[str, str], dict],
) -> dict:
    """Build a GeoJSON FeatureCollection of airport points and route lines."""
    features: list[dict] = []

    for iata in sorted(resolved):
        airport = resolved[iata]
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [airport["lon"], airport["lat"]],
                },
                "properties": {
                    "iata": iata,
                    "name": airport["name"],
                    "city": airport["city"],
                    "country": airport["country"],
                },
            }
        )

    for (origin, dest), stats in route_stats.items():
        if origin not in resolved or dest not in resolved:
            continue
        origin_airport = resolved[origin]
        dest_airport = resolved[dest]

        def _round(v: float | None) -> float | None:
            return round(v, 4) if v is not None else None

        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [
                        [origin_airport["lon"], origin_airport["lat"]],
                        [dest_airport["lon"], dest_airport["lat"]],
                    ],
                },
                "properties": {
                    "origin": origin,
                    "destination": dest,
                    "count": stats["count"],
                    "avg_block": _round(stats["avg_block"]),
                    "min_block": _round(stats["min_block"]),
                    "max_block": _round(stats["max_block"]),
                    "avg_credit": _round(stats["avg_credit"]),
                },
            }
        )

    return {"type": "FeatureCollection", "features": features}
