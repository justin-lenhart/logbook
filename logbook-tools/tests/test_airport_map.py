import pytest
from logbook_import.airport_map import aggregate_route_stats, build_geojson, resolve_airports

_AIRPORT_INDEX = {
    "MSP": {
        "name": "Minneapolis-Saint Paul International Airport",
        "city": "Minneapolis",
        "country": "US",
        "lat": 44.882,
        "lon": -93.2218,
    },
    "RAP": {
        "name": "Rapid City Regional Airport",
        "city": "Rapid City",
        "country": "US",
        "lat": 43.98,
        "lon": -101.2,
    },
}

_FLIGHT_RECORDS = [
    {"origin": "MSP", "dest": "RAP", "block": 1.5, "credit": 1.6},
    {"origin": "RAP", "dest": "MSP", "block": 1.4, "credit": 1.5},
]


def test_aggregate_route_stats_counts_and_stats() -> None:
    stats = aggregate_route_stats(_FLIGHT_RECORDS)
    assert len(stats) == 1
    key = ("MSP", "RAP")
    assert key in stats
    s = stats[key]
    assert s["count"] == 2
    assert s["avg_block"] == pytest.approx(1.45)
    assert s["min_block"] == pytest.approx(1.4)
    assert s["max_block"] == pytest.approx(1.5)
    assert s["avg_credit"] == pytest.approx(1.55)


def test_aggregate_route_stats_none_values() -> None:
    records = [{"origin": "MSP", "dest": "RAP", "block": None, "credit": None}]
    stats = aggregate_route_stats(records)
    s = stats[("MSP", "RAP")]
    assert s["count"] == 1
    assert s["avg_block"] is None
    assert s["min_block"] is None
    assert s["max_block"] is None
    assert s["avg_credit"] is None


def test_resolve_airports_all_found() -> None:
    stats = aggregate_route_stats(_FLIGHT_RECORDS)
    resolved, missing = resolve_airports(stats, _AIRPORT_INDEX)
    assert missing == []
    assert set(resolved) == {"MSP", "RAP"}


def test_resolve_airports_some_missing() -> None:
    records = [
        {"origin": "MSP", "dest": "XXX", "block": 1.0, "credit": 1.0},
        {"origin": "YYY", "dest": "RAP", "block": 1.0, "credit": 1.0},
    ]
    stats = aggregate_route_stats(records)
    resolved, missing = resolve_airports(stats, _AIRPORT_INDEX)
    assert missing == ["XXX", "YYY"]
    assert set(resolved) == {"MSP", "RAP"}


def test_resolve_airports_route_deduplication() -> None:
    """Bidirectional legs normalise to a single route key."""
    stats = aggregate_route_stats(_FLIGHT_RECORDS)
    assert len(stats) == 1
    assert ("MSP", "RAP") in stats
    assert stats[("MSP", "RAP")]["count"] == 2


def test_resolve_airports_missing_excluded_from_geojson() -> None:
    records = [
        {"origin": "AAA", "dest": "BBB", "block": 1.0, "credit": 1.0},
        {"origin": "MSP", "dest": "RAP", "block": 1.0, "credit": 1.0},
    ]
    stats = aggregate_route_stats(records)
    resolved, missing = resolve_airports(stats, _AIRPORT_INDEX)
    assert set(missing) == {"AAA", "BBB"}
    geojson = build_geojson(resolved, stats)
    line_features = [f for f in geojson["features"] if f["geometry"]["type"] == "LineString"]
    # AAA/BBB route must be excluded since airports are unresolved
    assert len(line_features) == 1
    assert line_features[0]["properties"]["origin"] == "MSP"


def test_build_geojson_structure() -> None:
    stats = aggregate_route_stats(_FLIGHT_RECORDS)
    resolved, _ = resolve_airports(stats, _AIRPORT_INDEX)
    geojson = build_geojson(resolved, stats)

    assert geojson["type"] == "FeatureCollection"
    features = geojson["features"]
    assert len(features) == 3  # 2 points + 1 line

    point_features = [f for f in features if f["geometry"]["type"] == "Point"]
    line_features = [f for f in features if f["geometry"]["type"] == "LineString"]
    assert len(point_features) == 2
    assert len(line_features) == 1

    first_point_idx = next(
        i for i, f in enumerate(features) if f["geometry"]["type"] == "Point"
    )
    first_line_idx = next(
        i for i, f in enumerate(features) if f["geometry"]["type"] == "LineString"
    )
    assert first_point_idx < first_line_idx

    msp_point = next(f for f in point_features if f["properties"]["iata"] == "MSP")
    assert msp_point["geometry"]["coordinates"] == [-93.2218, 44.882]

    line = line_features[0]
    assert line["geometry"]["coordinates"] == [
        [-93.2218, 44.882],
        [-101.2, 43.98],
    ]
    assert line["properties"]["origin"] == "MSP"
    assert line["properties"]["destination"] == "RAP"
    assert line["properties"]["count"] == 2
    assert line["properties"]["avg_block"] is not None
    assert line["properties"]["min_block"] is not None
    assert line["properties"]["max_block"] is not None
    assert line["properties"]["avg_credit"] is not None
