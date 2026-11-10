from datetime import date, time

from logbook_import import grist_fields as F
from logbook_import.cross_country import cross_country_hours, great_circle_nm
from logbook_import.grist_sync import GristImporter
from logbook_import.import_planner import build_import_plan
from logbook_import.models import DutyDay, ImportMode, Leg, PairingExport

from test_grist_sync import FakeClient

_ORD = (41.9786, -87.9048)
_MKE = (42.9472, -87.8966)   # 58 nm from ORD
_MDW = (41.7868, -87.7522)   # 13 nm from ORD
_MSP = (44.882, -93.222)


def test_great_circle_distance() -> None:
    assert 285 < great_circle_nm(*_ORD, *_MSP) < 295
    assert 57 < great_circle_nm(*_ORD, *_MKE) < 59
    assert great_circle_nm(*_ORD, *_ORD) == 0.0


def test_cross_country_needs_more_than_50_nm() -> None:
    assert cross_country_hours(0.9, *_ORD, *_MKE) == 0.9   # just over 50 nm
    assert cross_country_hours(0.4, *_ORD, *_MDW) == 0.0   # short reposition
    assert cross_country_hours(0.6, *_ORD, *_ORD) == 0.0   # air return


def _ap(rid: int, pos: tuple[float, float]) -> dict:
    return {"record_id": rid, "tz": "America/Chicago", "lat": pos[0], "lon": pos[1]}


def test_import_writes_zero_xc_for_air_return_and_deadhead() -> None:
    legs = [
        Leg(1, "5108", "N1", "ORD", "ORD", time(12, 0), time(12, 36), 50, 0.6, 0.6),
        Leg(2, "5822", "N1", "ORD", "MKE", time(13, 25), time(14, 18), 50, 0.9, 0.9),
        Leg(3, "4989", "", "MKE", "MSP", time(15, 0), time(16, 30), 0, 0.0, 1.5,
            deadhead_indicator="F"),
    ]
    pairing = PairingExport(
        employee_id="1", employee_name="Test Pilot", base="ORD", equipment_family="CRJ",
        role="FO", pairing_id="O1162", start_date=date(2026, 11, 5),
        block_hours=1.5, credit_hours=3.0, tafb_hours=6.0,
        duty_days=[DutyDay(date(2026, 11, 5), time(11, 0), time(17, 0), legs=legs)],
    )
    index = {"ORD": _ap(1, _ORD), "MKE": _ap(2, _MKE), "MSP": _ap(3, _MSP)}
    plan = build_import_plan(pairing, ImportMode.ACTUAL, airport_index=index)
    client = FakeClient(existing_trip_keys=set())
    GristImporter(None, airport_index=index, client=client).sync_plan(plan)
    xc = [p[F.F_FLIGHT_XC_TIME] for p in client.payloads[F.TABLE_FLIGHTS]]
    assert xc == [0.0, 0.9, 0.0]
