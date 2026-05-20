from datetime import date, datetime
from unittest.mock import MagicMock, patch

import pytest

from logbook_import.airtable_settings import AirtableSettings
from logbook_import.airtable_sync import AirtableImporter
from logbook_import.import_planner import build_import_batch, build_import_plan
from logbook_import.models import (
    CrewRole,
    ImportBatchRecord,
    ImportMode,
    ImportPlan,
    Operator,
    PlannedDutyPeriodRecord,
    PlannedTripRecord,
)
from logbook_import.config import PairingFileSet
from logbook_import.parsers.merge import load_pairing_export


def _minimal_plan() -> ImportPlan:
    trip = PlannedTripRecord(
        trip_key="E7748|2026-05-08",
        pairing_id="E7748",
        start_date=date(2026, 5, 8),
        end_date=date(2026, 5, 8),
        base="MSP",
        equipment_family="CRJ",
        planned_block=2.3,
        planned_credit=4.2,
        planned_duty_periods=1,
        planned_legs=3,
        status="Actual",
    )
    duty = PlannedDutyPeriodRecord(
        duty_period_key="E7748|2026-05-08|2026-05-08",
        trip_key="E7748|2026-05-08",
        duty_date=date(2026, 5, 8),
        report_at=datetime(2026, 5, 8, 14, 0),
        release_at=datetime(2026, 5, 8, 22, 0),
        planned_block=2.3,
        planned_credit=4.2,
        planned_legs=3,
        status="Actual",
    )
    return ImportPlan(
        mode=ImportMode.ACTUAL,
        pairing_id="E7748",
        source_txt="/inbox/test.txt",
        source_csv=None,
        trips=[trip],
        duty_periods=[duty],
        flights=[],
        import_batch=ImportBatchRecord(
            batch_name="E7748|2026-05-08|Actual",
            import_type="Actual",
            source_filename="test.txt",
            source_folder="inbox",
        ),
    )


def _upsert_result(records: list[dict]) -> dict:
    return {
        "createdRecords": [record["id"] for record in records],
        "updatedRecords": [],
        "records": records,
    }


@patch("logbook_import.airtable_sync.fetch_airport_index", return_value={})
@patch("logbook_import.airtable_sync.Api")
def test_sync_plan_upserts_in_order(mock_api_cls: MagicMock, _mock_airports: MagicMock) -> None:
    settings = AirtableSettings(api_key="key", base_id="appTESTBASE000000")

    aircraft_table = MagicMock()
    aircraft_table.all.return_value = [
        {"id": "recAIRCR5", "fields": {"Aircraft": "CR5"}},
    ]

    batch_table = MagicMock()
    trips_table = MagicMock()
    duty_table = MagicMock()
    flights_table = MagicMock()

    batch_table.batch_upsert.return_value = _upsert_result(
        [{"id": "recBATCH1", "fields": {"Batch Name": "E7748|2026-05-08|Actual"}}]
    )
    trips_table.batch_upsert.return_value = _upsert_result(
        [{"id": "recTRIP1", "fields": {"Trip Key": "E7748|2026-05-08"}}]
    )
    duty_table.batch_upsert.return_value = _upsert_result(
        [
            {
                "id": "recDUTY1",
                "fields": {"Duty Period Key": "E7748|2026-05-08|2026-05-08"},
            }
        ]
    )
    flights_table.batch_upsert.return_value = _upsert_result([])

    base = MagicMock()
    base.table.side_effect = lambda name: {
        "Import Batch": batch_table,
        "Trips": trips_table,
        "Duty Periods": duty_table,
        "Flights": flights_table,
        "Aircraft": aircraft_table,
    }[name]

    mock_api_cls.return_value.base.return_value = base

    importer = AirtableImporter(settings)
    result = importer.sync_plan(_minimal_plan())

    assert result.batch_record_id == "recBATCH1"
    assert result.trips.created == 1
    assert result.duty_periods.created == 1
    batch_table.update.assert_called_once()
    trips_payload = trips_table.batch_upsert.call_args[0][0][0]["fields"]
    assert trips_payload["Import Batch"] == ["recBATCH1"]


def test_build_import_batch_from_pairing(e7748_txt, e7748_csv) -> None:
    pairing, _ = load_pairing_export(
        PairingFileSet("E7748", txt_path=e7748_txt, csv_path=e7748_csv)
    )
    batch = build_import_batch(pairing, ImportMode.ACTUAL)
    assert batch.batch_name == "E7748|2026-05-08|Actual"
    assert batch.import_type == "Actual"

    plan = build_import_plan(
        pairing,
        ImportMode.ACTUAL,
        role=CrewRole.SIC,
        operator=Operator.SKW,
    )
    assert plan.import_batch.batch_name.endswith("|Actual")
