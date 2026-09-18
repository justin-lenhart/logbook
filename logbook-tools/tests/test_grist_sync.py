from datetime import date, time

from logbook_import import grist_fields as F
from logbook_import.grist_client import UpsertResult
from logbook_import.grist_mapper import format_grist_date
from logbook_import.grist_sync import GristImporter, missing_duty_days_to_cancel
from logbook_import.import_planner import build_import_plan
from logbook_import.models import DutyDay, ImportMode, Leg, PairingExport


class FakeClient:
    """In-memory stand-in for GristClient: records upsert payloads."""

    def __init__(self, existing_trip_keys: set[str]) -> None:
        self.rows: dict[str, dict[str, int]] = {F.TABLE_TRIPS: {k: 1 for k in existing_trip_keys}}
        self.payloads: dict[str, list[dict]] = {}
        self.updates: list[tuple[str, list]] = []
        self.fail_table: str | None = None
        self.duty_rows: list[dict] = []   # returned for the Duty_Periods-by-trip query
        self._next_id = 100

    def sql(self, query: str, args=None) -> list[dict]:
        if f'FROM "{F.TABLE_DUTY_PERIODS}"' in query:
            return self.duty_rows
        return []

    def fetch_key_index(self, table: str, key_col: str, keys: list[str]) -> dict[str, int]:
        return {k: rid for k, rid in self.rows.get(table, {}).items() if k in keys}

    def upsert_by_key(self, table: str, payloads: list[dict], key_col: str) -> UpsertResult:
        if table == self.fail_table:
            raise RuntimeError("HTTP 400 on " + table)
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
        self.updates.append((table, list(updates)))

    def notes(self) -> list[str]:
        return [
            fields[F.F_BATCH_NOTES]
            for table, ups in self.updates if table == F.TABLE_IMPORT_BATCH
            for _, fields in ups
        ]


def _plan(mode: ImportMode = ImportMode.PLANNED):
    leg = Leg(1, "5907", "N975SW", "GRB", "ORD", time(15, 26), time(16, 51), 50, 1.4, 1.4)
    pairing = PairingExport(
        employee_id="1", employee_name="Test Pilot", base="ORD", equipment_family="CRJ",
        role="FO", pairing_id="O1251A", start_date=date(2026, 7, 22),
        block_hours=1.4, credit_hours=4.2, tafb_hours=10.0,
        duty_days=[DutyDay(date(2026, 7, 22), time(14, 50), time(17, 30), legs=[leg])],
    )
    tz = {"record_id": 1, "tz": "America/Chicago", "lat": 0.0, "lon": 0.0}
    return build_import_plan(pairing, mode, airport_index={"GRB": tz, "ORD": tz})


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


def test_batch_notes_replaced_with_all_warnings() -> None:
    plan = _plan(ImportMode.ACTUAL)
    assert plan.flights
    plan.warnings[:0] = ["Warning: O1251A has no matching .csv export"]
    client = FakeClient(existing_trip_keys=set())
    result = GristImporter(None, airport_index={}, client=client).sync_plan(plan)
    notes = client.notes()
    assert len(notes) == 1                     # one write, replaces the old value
    lines = notes[0].splitlines()
    assert lines[0] == "WARN: Warning: O1251A has no matching .csv export"
    # Sync-time warnings (airports not in the index here) are included too.
    assert any("Departure Airport link omitted" in line for line in lines)
    assert all(line.startswith("WARN: ") for line in lines)
    assert len(lines) == len(result.warnings)


def test_batch_notes_empty_when_no_warnings() -> None:
    plan = _plan()
    plan.flights.clear()
    client = FakeClient(existing_trip_keys=set())
    GristImporter(None, airport_index={}, client=client).sync_plan(plan)
    assert client.notes() == [""]


def test_batch_notes_record_error_then_reraise() -> None:
    plan = _plan()
    client = FakeClient(existing_trip_keys=set())
    client.fail_table = F.TABLE_DUTY_PERIODS
    try:
        GristImporter(None, airport_index={}, client=client).sync_plan(plan)
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected RuntimeError")
    assert client.notes()[0].splitlines()[0] == "ERROR: RuntimeError: HTTP 400 on Duty_Periods"


def _epoch(d: date) -> int:
    return format_grist_date(d)


def test_missing_duty_days_to_cancel_rules() -> None:
    today = date(2026, 7, 10)
    rows = [
        {"id": 1, "k": "O1262|2026-07-02|2026-07-02", "d": _epoch(date(2026, 7, 2)), "s": "Actual"},
        {"id": 3, "k": "O1262|2026-07-02|2026-07-04", "d": _epoch(date(2026, 7, 4)), "s": "Planned"},
        {"id": 4, "k": "O1262|2026-07-02|2026-07-05", "d": _epoch(date(2026, 7, 5)), "s": "Planned"},
        {"id": 5, "k": "O1262|2026-07-02|2026-07-10", "d": _epoch(today), "s": "Planned"},
        {"id": 6, "k": "O1262|2026-07-02|2026-07-11", "d": _epoch(date(2026, 7, 11)), "s": "Planned"},
        {"id": 7, "k": "O1262|2026-07-02|2026-07-06", "d": _epoch(date(2026, 7, 6)), "s": "Replaced"},
        {"id": 8, "k": "O1262|2026-07-02|2026-07-03", "d": _epoch(date(2026, 7, 3)), "s": "Planned"},
    ]
    in_file = {"O1262|2026-07-02|2026-07-02", "O1262|2026-07-02|2026-07-03"}
    # 3, 4 and 5 (today): Planned, not in file, dated <= today. 6 is future,
    # 7 is not "Planned", 8 is in the file.
    assert [rid for rid, _ in missing_duty_days_to_cancel(rows, in_file, today)] == [3, 4, 5]


def test_actual_import_cancels_missing_planned_days_and_sets_flown_span() -> None:
    plan = _plan(ImportMode.ACTUAL)
    client = FakeClient(existing_trip_keys={"O1251|2026-07-22"})
    client.duty_rows = [
        {"id": 50, "k": "O1251|2026-07-22|2026-07-22", "d": _epoch(date(2026, 7, 22)), "s": "Actual"},
        {"id": 51, "k": "O1251|2026-07-22|2026-07-23", "d": _epoch(date(2026, 7, 23)), "s": "Planned"},
    ]
    result = GristImporter(None, airport_index={}, client=client).sync_plan(plan)
    duty_updates = [ups for table, ups in client.updates if table == F.TABLE_DUTY_PERIODS]
    assert duty_updates == [[(51, {F.F_DUTY_STATUS: "Cancelled"})]]
    assert any("2026-07-23: not in the actual export" in w for w in result.warnings)
    # The trip's dates follow the actual export (flown span).
    trip = client.payloads[F.TABLE_TRIPS][0]
    assert trip[F.F_TRIP_START_DATE] == _epoch(date(2026, 7, 22))
    assert trip[F.F_TRIP_END_DATE] == _epoch(date(2026, 7, 22))


def test_planned_import_never_cancels() -> None:
    client = FakeClient(existing_trip_keys=set())
    client.duty_rows = [
        {"id": 51, "k": "O1251|2026-07-22|2026-07-23", "d": _epoch(date(2026, 7, 23)), "s": "Planned"},
    ]
    GristImporter(None, airport_index={}, client=client).sync_plan(_plan())
    assert not [u for table, u in client.updates if table == F.TABLE_DUTY_PERIODS]
