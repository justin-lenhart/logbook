"""Grist flight-records fetch for export-map.

Mirrors ``airport_map.fetch_flight_records`` (the only Airtable-touching piece
of the map pipeline). The Airtable filter formula
``AND({Deadhead} != TRUE(), OR({PIC Time} > 0, {SIC Time} > 0))`` becomes a SQL
WHERE over the stored columns; departure/arrival resolve by joining Airports.
The pure aggregation/GeoJSON builders in ``airport_map`` are reused unchanged.
"""

from __future__ import annotations

from logbook_import import grist_fields as F
from logbook_import.grist_client import GristClient

_FLIGHT_SQL = f"""
SELECT UPPER(TRIM(dep."{F.F_AIRPORT_IATA}")) AS origin,
       UPPER(TRIM(arr."{F.F_AIRPORT_IATA}")) AS dest,
       f."{F.F_FLIGHT_BLOCK_TIME}"  AS block,
       f."{F.F_FLIGHT_CREDIT_TIME}" AS credit
FROM "{F.TABLE_FLIGHTS}" f
LEFT JOIN "{F.TABLE_AIRPORTS}" dep ON dep.id = f."{F.F_FLIGHT_DEPARTURE}"
LEFT JOIN "{F.TABLE_AIRPORTS}" arr ON arr.id = f."{F.F_FLIGHT_ARRIVAL}"
WHERE COALESCE(f."{F.F_FLIGHT_DEADHEAD}", 0) = 0
  AND (f."{F.F_FLIGHT_PIC_TIME}" > 0 OR f."{F.F_FLIGHT_SIC_TIME}" > 0)
"""


def fetch_flight_records(client: GristClient) -> list[dict]:
    """Fetch non-deadhead flown legs; same shape as the Airtable version:
    dicts with origin, dest, block (float|None), credit (float|None)."""
    flights: list[dict] = []
    for row in client.sql(_FLIGHT_SQL):
        origin = str(row.get("origin") or "").strip()
        dest = str(row.get("dest") or "").strip()
        if not origin or not dest:
            continue  # unlinked airport — mirror Airtable-version skip
        block = row.get("block")
        credit = row.get("credit")
        flights.append({
            "origin": origin,
            "dest": dest,
            "block": float(block) if block is not None else None,
            "credit": float(credit) if credit is not None else None,
        })
    return flights
