from collections import Counter

from logbook_import.airport_map import build_geojson, resolve_airports

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


def test_resolve_airports_all_found() -> None:
    pairs = [("MSP", "RAP")]
    resolved, valid_pairs, missing = resolve_airports(pairs, _AIRPORT_INDEX)
    assert missing == []
    assert set(resolved) == {"MSP", "RAP"}
    assert valid_pairs == [("MSP", "RAP")]


def test_resolve_airports_some_missing() -> None:
    pairs = [("MSP", "XXX"), ("YYY", "RAP")]
    resolved, valid_pairs, missing = resolve_airports(pairs, _AIRPORT_INDEX)
    assert missing == ["XXX", "YYY"]
    assert set(resolved) == {"MSP", "RAP"}
    assert valid_pairs == []


def test_resolve_airports_route_deduplication() -> None:
    pairs = [("MSP", "RAP"), ("RAP", "MSP")]
    resolved, valid_pairs, missing = resolve_airports(pairs, _AIRPORT_INDEX)
    assert missing == []
    assert valid_pairs == [("MSP", "RAP")]
    counts = Counter(tuple(sorted(pair)) for pair in pairs)
    assert counts[("MSP", "RAP")] == 2


def test_resolve_airports_both_missing_excluded_from_valid_pairs() -> None:
    pairs = [("AAA", "BBB"), ("MSP", "RAP")]
    resolved, valid_pairs, missing = resolve_airports(pairs, _AIRPORT_INDEX)
    assert set(missing) == {"AAA", "BBB"}
    assert valid_pairs == [("MSP", "RAP")]


def test_build_geojson_structure() -> None:
    resolved = _AIRPORT_INDEX
    valid_pairs_with_counts = [(("MSP", "RAP"), 2)]
    geojson = build_geojson(resolved, valid_pairs_with_counts)

    assert geojson["type"] == "FeatureCollection"
    features = geojson["features"]
    assert len(features) == 4  # 2 points + 1 line

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
    assert all(
        features[i]["geometry"]["type"] == "Point"
        for i in range(first_line_idx)
    )

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
