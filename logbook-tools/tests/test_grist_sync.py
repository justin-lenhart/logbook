from datetime import date, time

from logbook_import import grist_fields as F
from logbook_import.grist_client import UpsertResult
from logbook_import.grist_sync import GristImporter
from logbook_import.import_planner import build_import_plan
from logbook_import.models import DutyDay, ImportMode, Leg, PairingExport


class FakeClient:
    """In-memory stand-in for GristClient: records upsert payloads."""

    def __init__(self, existing_trip_keys: set[str]) -> None:
        self.rows: dict[str, dict[str, int]] = {F.TABLE_TRIPS: {k: 1 for k in existing_trip_keys}}
        self.payloads: dict[str, list[dict]] = {}
        self._next_id = 100

    def sql(self, query: str, args=None) -> list[dict]:
        return []

    def fetch_key_index(self, table: str, key_col: str, keys: list[str]) -> dict[str, int]:
        return {k: rid for k, rid in self.rows.get(table, {}).items() if k in keys}

    def upsert_by_key(self, table: str, payloads: list[dict], key_col: str) -> UpsertResult:
        self.payloads[table] = payloads
        result = UpsertResult()
        table_rows = self.rows.setdefault(table, {})
        for p in payloads:
            key = str(p[key_col])
            if key not in table_rows:
                self._next_id += 1
                table_rows[key] = self._next_id
                result.created_ids.append(self._next_id)
            else:
                result.updated_ids.append(table_rows[key])
            result.key_to_id[key] = table_rows[key]
        return result

    def update_records(self, table: str, updates) -> None:
        pass


def _plan():
    leg = Leg(1, "5907", "N975SW", "GRB", "ORD", time(15, 26), time(16, 51), 50, 1.4, 1.4)
    pairing = PairingExport(
        employee_id="1", employee_name="Test Pilot", base="ORD", equipment_family="CRJ",
        role="FO", pairing_id="O1251A", start_date=date(2026, 7, 22),
        block_hours=1.4, credit_hours=4.2, tafb_hours=10.0,
        duty_days=[DutyDay(date(2026, 7, 22), time(14, 50), time(17, 30), legs=[leg])],
    )
    tz = {"record_id": 1, "tz": "America/Chicago", "lat": 0.0, "lon": 0.0}
    return build_import_plan(pairing, ImportMode.PLANNED, airport_index={"GRB": tz, "ORD": tz})


def test_base_written_only_when_trip_is_created() -> None:
    plan = _plan()
    client = FakeClient(existing_trip_keys=set())
    GristImporter(None, airport_index={}, client=client).sync_plan(plan)
    trip = client.payloads[F.TABLE_TRIPS][0]
    assert trip[F.F_TRIP_BASE] == "GRB"
    assert trip[F.F_TRIP_PAIRING_ID] == "O1251"
    assert "Equipment_Family" not in trip


def test_base_not_overwritten_on_reimport() -> None:
    plan = _plan()
    client = FakeClient(existing_trip_keys={"O1251|2026-07-22"})
    GristImporter(None, airport_index={}, client=client).sync_plan(plan)
    trip = client.payloads[F.TABLE_TRIPS][0]
    assert F.F_TRIP_BASE not in trip
    assert trip[F.F_TRIP_TAFB] == 10.0
