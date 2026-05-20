from datetime import date, datetime

from logbook_import import airtable_fields as F
from logbook_import.airtable_mapper import (
    map_duty_period_fields,
    map_flight_fields,
    map_import_batch_fields,
    map_trip_fields,
)
from logbook_import.models import (
    ImportBatchRecord,
    PlannedDutyPeriodRecord,
    PlannedFlightRecord,
    PlannedTripRecord,
)


def test_map_trip_fields() -> None:
    trip = PlannedTripRecord(
        trip_key="E3058E|2026-05-09",
        pairing_id="E3058E",
        start_date=date(2026, 5, 9),
        end_date=date(2026, 5, 12),
        base="MSP",
        equipment_family="CRJ",
        planned_block=13.8,
        planned_credit=19.3,
        planned_duty_periods=4,
        planned_legs=14,
        status="Actual",
    )
    fields = map_trip_fields(trip)
    assert fields[F.F_TRIP_KEY] == "E3058E|2026-05-09"
    assert fields[F.F_TRIP_PAIRING_ID] == "E3058E"
    assert fields[F.F_TRIP_START_DATE] == "2026-05-09"
    assert F.F_TRIP_EQUIPMENT_FAMILY not in fields

    with_equipment = map_trip_fields(trip, include_equipment_family=True)
    assert with_equipment[F.F_TRIP_EQUIPMENT_FAMILY] == "CRJ"


def test_map_flight_fields() -> None:
    flight = PlannedFlightRecord(
        import_flight_key="E3058E|2026-05-09|4266|MSP|INL|1252",
        trip_key="E3058E|2026-05-09",
        duty_period_key="E3058E|2026-05-09|2026-05-09",
        duty_date=date(2026, 5, 9),
        flight_number="4266",
        tail_number="N713EV",
        origin="MSP",
        destination="INL",
        out_time=datetime(2026, 5, 9, 12, 52),
        in_time=datetime(2026, 5, 9, 14, 10),
        block_hours=1.3,
        credit_hours=1.3,
        pic_hours=0.0,
        sic_hours=1.3,
        deadhead=False,
        aircraft_code="CR5",
        operation="Part 121",
        airline="SKW",
    )
    fields = map_flight_fields(flight)
    assert fields[F.F_IMPORT_FLIGHT_KEY] == "E3058E|2026-05-09|4266|MSP|INL|1252"
    assert fields[F.F_FLIGHT_OPERATION] == "Part 121"
    assert fields[F.F_FLIGHT_DEADHEAD] is False


def test_map_duty_and_batch_fields() -> None:
    duty = PlannedDutyPeriodRecord(
        duty_period_key="E3058E|2026-05-09|2026-05-09",
        trip_key="E3058E|2026-05-09",
        duty_date=date(2026, 5, 9),
        report_at=datetime(2026, 5, 9, 11, 30),
        release_at=datetime(2026, 5, 9, 18, 0),
        planned_block=4.2,
        planned_credit=5.8,
        planned_legs=4,
        status="Actual",
    )
    assert map_duty_period_fields(duty)[F.F_DUTY_REPORT_TIME] == "2026-05-09T11:30:00"

    batch = ImportBatchRecord(
        batch_name="E3058E|2026-05-09|Actual",
        import_type="Actual",
        source_filename="121807_20260509_E3058E.txt",
        source_folder="inbox",
    )
    fields = map_import_batch_fields(batch, imported_at=datetime(2026, 5, 16, 10, 0))
    assert fields[F.F_BATCH_NAME] == "E3058E|2026-05-09|Actual"
    assert fields[F.F_BATCH_IMPORT_STATUS] == "Imported"
