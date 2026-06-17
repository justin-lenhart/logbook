"""Unit tests for the airline/FAA application report aggregation."""

from __future__ import annotations

import datetime

from logbook_import import app_report as R


def _flight(name, **f):
    """Build a raw Airtable-shaped flight record linked to aircraft `name`."""
    fields = {"Aircraft": [name]}  # use the name itself as the record id
    fields.update(f)
    return {"id": "rec" + name, "fields": fields}


AC_BY_ID = {
    "AH-1Z": "AH-1Z",
    "TH-57B": "TH-57B",
    "C172": "C172",
    "CR9": "CR9",
}


def test_military_non_pic_time_counts_as_sic():
    # Student helicopter time logged as dual received (PIC=SIC=0) must surface
    # as SIC for airline applications (block - PIC - instructor).
    rows = R.normalize(
        [_flight("TH-57B", **{"Block Time": 123.3, "Operation": "Military",
                              "Dual Received": 123.3, "Legacy Summary": True})],
        AC_BY_ID,
    )
    aggs = R.aggregate(rows)
    assert aggs["H57"].app_sic == 123.3
    assert aggs["H57"].sic == 0.0  # FAA-sense SIC unchanged


def test_sortie_conversion():
    rows = R.normalize(
        [_flight("AH-1Z", **{"Block Time": 692.3, "PIC Time": 242.5,
                            "SIC Time": 449.8, "Operation": "Military",
                            "Legacy Summary": True})],
        AC_BY_ID,
    )
    a = R.aggregate(rows)["AH1Z"]
    # AH1Z seeded sorties: PIC 82, SIC 191 → +24.6 / +57.3.
    assert round(a.conv_pic, 1) == 267.1
    assert round(a.conv_sic, 1) == 507.1


def test_civilian_time_not_converted():
    rows = R.normalize(
        [_flight("C172", **{"Block Time": 45.4, "PIC Time": 30.3,
                          "Operation": "Part 91", "Legacy Summary": True})],
        AC_BY_ID,
    )
    a = R.aggregate(rows)["C172"]
    assert a.conv_pic == a.pic == 30.3  # no sorties for civilian type


def test_simulator_excluded():
    rows = R.normalize(
        [_flight("CR9", **{"Block Time": 4.0, "Operation": "Simulator"})],
        AC_BY_ID,
    )
    assert rows == []


def test_faa_bucketing_and_grand_totals():
    rows = R.normalize(
        [
            _flight("AH-1Z", **{"Block Time": 100.0, "PIC Time": 100.0,
                              "Operation": "Military"}),
            _flight("CR9", **{"Block Time": 50.0, "SIC Time": 50.0,
                            "Operation": "Part 121"}),
        ],
        AC_BY_ID,
    )
    t = R.grand_totals(R.aggregate(rows))
    assert t.rotorcraft == 100.0
    assert t.airplane == 50.0
    assert t.fw_turbine == 50.0  # CRJ is a jet


def test_recency_buckets():
    today = datetime.date(2026, 6, 1)
    rows = R.normalize(
        [
            _flight("CR9", **{"Block Time": 10.0, "Flight Date": "2026-05-01",
                            "SIC Time": 10.0, "Operation": "Part 121"}),
            _flight("CR9", **{"Block Time": 20.0, "Flight Date": "2024-01-01",
                            "SIC Time": 20.0, "Operation": "Part 121"}),
        ],
        AC_BY_ID,
    )
    a = R.aggregate(rows, today=today)["CRJ"]
    assert a.recency["12"] == 10.0
    assert a.recency["36"] == 20.0
