"""Cross-country time under 14 CFR 61.1(b) (ATP / military-pilot definition).

A leg counts as cross-country when its destination is more than 50 nautical
miles straight-line distance from the point of departure. The whole block time
counts or none of it does; no landing is required by this definition.
"""

from __future__ import annotations

import math

XC_MIN_DISTANCE_NM = 50.0
_EARTH_RADIUS_NM = 3440.065


def great_circle_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle (haversine) distance in nautical miles."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat = p2 - p1
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    return 2 * _EARTH_RADIUS_NM * math.asin(math.sqrt(a))


def cross_country_hours(
    block_hours: float,
    origin_lat: float,
    origin_lon: float,
    dest_lat: float,
    dest_lon: float,
) -> float:
    """Block time if the leg ends more than 50 nm from where it began, else 0."""
    distance = great_circle_nm(origin_lat, origin_lon, dest_lat, dest_lon)
    return block_hours if distance > XC_MIN_DISTANCE_NM else 0.0
