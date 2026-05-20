from __future__ import annotations

from collections import Counter

from pyairtable import Api

from logbook_import import airtable_fields as F

_FLIGHT_FORMULA = (
    "AND({Deadhead} != TRUE(), OR({PIC Time} > 0, {SIC Time} > 0))"
)


def fetch_flight_airport_pairs(api_key: str, base_id: str) -> list[tuple[str, str]]:
    """Fetch non-deadhead flown legs and return (origin, destination) ICAO pairs."""
    table = Api(api_key).base(base_id).table(F.TABLE_FLIGHTS)
    fields = [
        F.F_FLIGHT_DEPARTURE,
        F.F_FLIGHT_ARRIVAL,
        F.F_FLIGHT_DEADHEAD,
        F.F_FLIGHT_PIC_TIME,
        F.F_FLIGHT_SIC_TIME,
    ]
    records = table.all(fields=fields, formula=_FLIGHT_FORMULA)

    pairs: list[tuple[str, str]] = []
    for record in records:
        row = record.get("fields", {})
        origin_raw = row.get(F.F_FLIGHT_DEPARTURE)
        dest_raw = row.get(F.F_FLIGHT_ARRIVAL)
        if not origin_raw or not dest_raw:
            continue
        origin = str(origin_raw).strip().upper()
        dest = str(dest_raw).strip().upper()
        if not origin or not dest:
            continue
        pairs.append((origin, dest))
    return pairs


def resolve_airports(
    flight_pairs: list[tuple[str, str]],
    airport_index: dict[str, dict],
) -> tuple[dict[str, dict], list[tuple[str, str]], list[str]]:
    """Resolve IATA codes and deduplicate normalized route pairs."""
    all_iata: set[str] = set()
    for origin, dest in flight_pairs:
        all_iata.add(origin)
        all_iata.add(dest)

    resolved = {code: airport_index[code] for code in all_iata if code in airport_index}
    missing = sorted(code for code in all_iata if code not in airport_index)

    pair_counts = Counter(
        tuple(sorted((origin, dest))) for origin, dest in flight_pairs
    )
    valid_pairs = [
        pair
        for pair in pair_counts
        if pair[0] in resolved and pair[1] in resolved
    ]
    return resolved, valid_pairs, missing


def build_geojson(
    resolved: dict[str, dict],
    valid_pairs_with_counts: list[tuple[tuple[str, str], int]],
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

    # count enables future Leaflet weight/color styling
    for (origin, dest), count in valid_pairs_with_counts:
        origin_airport = resolved[origin]
        dest_airport = resolved[dest]
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
                    "count": count,
                },
            }
        )

    return {"type": "FeatureCollection", "features": features}
