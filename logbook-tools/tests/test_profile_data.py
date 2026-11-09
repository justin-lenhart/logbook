"""profile_data: row -> Leg mapping, predicates, aggregators (no network)."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from logbook_import import profile_data as pd
from logbook_import.grist_client import GristClient
from logbook_import.grist_settings import GristSettings
from logbook_import.profile_data import Leg

PROVENANCE = "Historical line-item import from workbook (Master row 6)."

COBRA = dict(aircraft="AH-1Z", faa_type="H1", category="Helicopter",
             aircraft_class="Rotorcraft", engine_category="Turbine",
             engine_type="Turboshaft", operation="Military", historical=True)
CRJ = dict(aircraft="CR7", faa_type="CL65", category="Airplane",
           aircraft_class="Multi-Engine Land", engine_category="Turbine",
           engine_type="Turbofan", operation="Part 121")
SKYHAWK = dict(aircraft="C172", faa_type="C172", category="Airplane",
               aircraft_class="Single-Engine Land", engine_category="Reciprocating",
               engine_type="Reciprocating", operation="Part 91", historical=True)
OSPREY = dict(aircraft="MV-22", faa_type="V22", category="Powered Lift",
              aircraft_class="Multi-Engine Land", engine_category="Turbine",
              engine_type="Turboshaft", operation="Military", historical=True)


def leg(n: int, day: str, kind: dict, **hours: Any) -> Leg:
    return Leg(id=n, date=date.fromisoformat(day), **kind, **hours)


@pytest.fixture
def legs() -> list[Leg]:
    return [
        leg(1, "2015-03-01", SKYHAWK, block=1.0, dual_received=1.0, xc=0.5),
        leg(2, "2019-06-01", COBRA, block=2.0, pic=2.0, night=1.0, nvg=1.0,
            mil_sortie=1, combat=2.0, night_landings=2, dual_given=2.0),
        leg(3, "2020-06-01", COBRA, block=1.5, sic=1.5, mil_sortie=1),
        leg(4, "2021-01-01", OSPREY, block=0.6, sic=0.6, mil_sortie=1),
        leg(5, "2026-05-10", CRJ, block=2.2, sic=2.2, night=0.4, xc=2.2),
        leg(6, "2026-11-01", CRJ, block=1.8, sic=1.8),
    ]


class FakeClient(GristClient):
    def __init__(self, rows: list[dict]) -> None:
        super().__init__(GristSettings(url="http://test", api_key="k", doc_id="d"))
        self.rows = rows
        self.calls: list[tuple[str, str, Any]] = []

    def _request(self, method: str, path: str, body: Any | None = None) -> Any:
        self.calls.append((method, path, body))
        return {"records": [{"fields": r} for r in self.rows]}


def test_load_legs_maps_rows_and_is_one_read_only_query() -> None:
    client = FakeClient([{
        "id": 166, "flight_date": 1425081600, "out_time": None, "airline": "",
        "flight_number": "", "tail": "N348SP", "operation": "Part 91", "historical": 1,
        "notes": PROVENANCE + "\nLogbook remark: IFS, 5R4",
        "block": 0.6, "pic": 0, "sic": 0, "dual_received": 0.6, "dual_given": 0,
        "night": None, "instrument": None, "xc": 0.1, "day_landings": 1,
        "night_landings": None, "mil_sortie": 0, "nvg": 0, "combat": 0,
        "aircraft": "C172", "faa_type": "C172", "category": "Airplane",
        "aircraft_class": "Single-Engine Land", "engine_category": "Reciprocating",
        "engine_type": "Reciprocating", "origin": None, "dest": None,
    }])
    [got] = pd.load_legs(client)

    assert got.date == date(2015, 2, 28)
    assert (got.block, got.dual_received, got.night) == (0.6, 0.6, 0.0)
    assert got.historical is True
    assert got.remark == "IFS, 5R4"
    assert got.origin == "" and got.tail == "N348SP"

    [(method, path, body)] = client.calls
    assert path.endswith("/sql")
    sql = body["sql"].upper()
    assert sql.lstrip().startswith("SELECT")
    assert 'COALESCE(F."DEADHEAD", 0) = 0' in sql          # deadheads excluded
    assert sql.count('JOIN "AIRPORTS"') == 2 and 'JOIN "AIRCRAFT"' in sql
    assert not any(word in sql for word in ("UPDATE ", "INSERT ", "DELETE "))


def test_leg_without_aircraft_link_has_no_category() -> None:
    got = pd.leg_from_row({"id": 1, "flight_date": "2026-10-03", "block": 1.2,
                           "sic": 1.2, "aircraft": None, "category": None})
    assert got.aircraft == "" and got.category == ""
    assert not pd.is_airplane(got)


@pytest.mark.parametrize("notes, expected", [
    (PROVENANCE + "\nLogbook remark: FAM-1, NVG", "FAM-1, NVG"),
    (PROVENANCE, ""),                       # provenance alone is not a remark
    ("", ""),
    (None, ""),
    ("Logbook remark:   padded  ", "padded"),
])
def test_parse_remark(notes: str | None, expected: str) -> None:
    assert pd.parse_remark(notes) == expected


def test_predicates(legs: list[Leg]) -> None:
    skyhawk, cobra, _, osprey, crj, _ = legs
    assert pd.is_airplane(crj) and pd.is_multi(crj) and pd.is_turbine(crj)
    assert pd.is_jet(crj) and pd.is_part121(crj) and not pd.is_military(crj)
    assert pd.is_single(skyhawk) and not pd.is_turbine(skyhawk)
    assert pd.is_rotorcraft(cobra) and pd.is_military(cobra) and pd.is_pic(cobra)
    # Powered lift is "Multi-Engine Land" in the Aircraft table but is not AMEL.
    assert pd.is_powered_lift(osprey) and not pd.is_multi(osprey)
    assert not pd.is_airplane(osprey)


def test_total_and_role_partition(legs: list[Leg]) -> None:
    assert pd.total(legs) == pytest.approx(9.1)
    assert pd.total(legs, where=pd.is_airplane) == pytest.approx(5.0)
    assert pd.total(legs, where=pd.is_rotorcraft) == pytest.approx(3.5)
    assert pd.total(legs, where=pd.is_powered_lift) == pytest.approx(0.6)
    assert pd.total(legs, "pic", pd.all_of(pd.is_airplane, pd.is_turbine)) == 0
    roles = sum(pd.total(legs, f) for f in ("pic", "sic", "dual_received"))
    assert roles == pytest.approx(pd.total(legs))


def test_total_share_splits_by_role() -> None:
    mixed = [leg(1, "2026-01-01", CRJ, block=2.0, pic=0.5, sic=1.5, night=1.0),
             leg(2, "2026-01-02", CRJ, block=0.0, night=1.0)]   # zero block: no share
    assert pd.total(mixed, "night", share="pic") == pytest.approx(0.25)
    assert pd.total(mixed, "night", share="sic") == pytest.approx(0.75)


def test_within_is_calendar_months_inclusive_of_as_of(legs: list[Leg]) -> None:
    as_of = date(2026, 11, 1)
    assert [l.id for l in pd.within(legs, 12, as_of)] == [5, 6]
    assert [l.id for l in pd.within(legs, 5, as_of)] == [6]      # 2026-06-01 < d
    # A flight exactly N months back is outside the window.
    assert [l.id for l in pd.within(legs, 12, date(2027, 5, 10))] == [6]


def test_months_before_clamps_day() -> None:
    assert pd.months_before(date(2026, 3, 31), 1) == date(2026, 2, 28)
    assert pd.months_before(date(2024, 3, 31), 1) == date(2024, 2, 29)
    assert pd.months_before(date(2026, 1, 15), 13) == date(2024, 12, 15)


def test_last_flown(legs: list[Leg]) -> None:
    assert pd.last_flown(legs) == date(2026, 11, 1)
    assert pd.last_flown([]) is None


def test_by_type_groups_and_orders_by_block(legs: list[Leg]) -> None:
    aggs = pd.by_type(legs)
    assert [a.key for a in aggs] == ["CR7", "AH-1Z", "C172", "MV-22"]
    cobra = aggs[1]
    assert cobra.total() == pytest.approx(3.5)
    assert cobra.total("mil_sortie") == 2
    assert cobra.last_flown == date(2020, 6, 1)
    by_faa = pd.by_type(legs, key=lambda l: l.faa_type)
    assert {a.key for a in by_faa} == {"CL65", "H1", "C172", "V22"}
