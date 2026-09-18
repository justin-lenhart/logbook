from datetime import date, datetime, timezone

import pytest

from logbook_import import grist_fields as F
from logbook_import.grist_mapper import (
    encode_choice_list,
    format_batch_notes,
    format_grist_date,
    format_grist_datetime,
    map_duty_period_fields,
    map_flight_fields,
    map_import_batch_fields,
    map_trip_fields,
)
from logbook_import.models import (
    ImportBatchRecord,
    ImportMode,
    PlannedDutyPeriodRecord,
    PlannedFlightRecord,
    PlannedTripRecord,
)


def _trip(**overrides) -> PlannedTripRecord:
    base = dict(
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
    base.update(overrides)
    return PlannedTripRecord(**base)


# --- value formats ---------------------------------------------------------

def test_format_grist_date_is_utc_midnight_epoch() -> None:
    # 2026-05-09 00:00:00 UTC
    assert format_grist_date(date(2026, 5, 9)) == 1778284800


def test_format_grist_datetime_epoch_seconds() -> None:
    dt = datetime(2026, 5, 9, 14, 30, tzinfo=timezone.utc)
    assert format_grist_datetime(dt) == 1778337000


def test_encode_choice_list() -> None:
    assert encode_choice_list(["SDuty"]) == ["L", "SDuty"]
    assert encode_choice_list(["Ferry", "Other (See Notes)"]) == [
        "L", "Ferry", "Other (See Notes)",
    ]


# --- trips -----------------------------------------------------------------

def test_map_trip_fields() -> None:
    fields = map_trip_fields(_trip())
    assert fields[F.F_TRIP_KEY] == "E3058E|2026-05-09"
    assert fields[F.F_TRIP_PAIRING_ID] == "E3058E"
    assert fields[F.F_TRIP_START_DATE] == format_grist_date(date(2026, 5, 9))
    assert fields[F.F_TRIP_END_DATE] == format_grist_date(date(2026, 5, 12))
    # The txt header equipment is not trip data: never written.
    assert "Equipment_Family" not in fields
    # Base only when the sync layer creates the trip row.
    assert F.F_TRIP_BASE not in fields
    assert map_trip_fields(_trip(), include_base=True)[F.F_TRIP_BASE] == "MSP"
    assert F.F_TRIP_BASE not in map_trip_fields(_trip(base=""), include_base=True)


def test_map_trip_fields_actual_credit_only_on_actual() -> None:
    trip = _trip(actual_credit=18.3)
    assert map_trip_fields(trip, mode=ImportMode.ACTUAL)[F.F_TRIP_ACTUAL_CREDIT] == 18.3
    assert F.F_TRIP_ACTUAL_CREDIT not in map_trip_fields(trip, mode=ImportMode.PLANNED)
    assert F.F_TRIP_ACTUAL_CREDIT not in map_trip_fields(_trip(), mode=ImportMode.ACTUAL)


def test_map_trip_fields_planned_only_writes() -> None:
    trip = _trip(tafb_hours=75.8)
    planned = map_trip_fields(trip)
    assert planned[F.F_TRIP_PLANNED_BLOCK] == 13.8
    assert planned[F.F_TRIP_TAFB] == 75.8
    # Actual import must not touch planned fields (preserves scheduled values).
    actual = map_trip_fields(trip, mode=ImportMode.ACTUAL)
    for key in (
        F.F_TRIP_PLANNED_BLOCK,
        F.F_TRIP_PLANNED_CREDIT,
        F.F_TRIP_PLANNED_LEGS,
        F.F_TRIP_PLANNED_DUTY_PERIODS,
    ):
        assert key not in actual


def test_map_trip_fields_tafb_written_by_both_modes() -> None:
    # TAFB has no planned/actual split: the last import wins.
    planned = map_trip_fields(_trip(tafb_hours=72.9), mode=ImportMode.PLANNED)
    actual = map_trip_fields(_trip(tafb_hours=72.2), mode=ImportMode.ACTUAL)
    assert planned[F.F_TRIP_TAFB] == 72.9
    assert actual[F.F_TRIP_TAFB] == 72.2
    # No header TAFB parsed -> leave the column alone.
    assert F.F_TRIP_TAFB not in map_trip_fields(_trip(tafb_hours=0.0), mode=ImportMode.ACTUAL)


def test_map_duty_period_fields_utc_aware_epoch() -> None:
    # O1251 day 3: report EAU 13:50 CDT (18:50Z), release LNS 19:58 EDT (23:58Z).
    duty = PlannedDutyPeriodRecord(
        duty_period_key="O1251|2026-07-22|2026-07-24",
        trip_key="O1251|2026-07-22",
        duty_date=date(2026, 7, 24),
        report_at=datetime(2026, 7, 24, 18, 50, tzinfo=timezone.utc),
        release_at=datetime(2026, 7, 24, 23, 58, tzinfo=timezone.utc),
        planned_block=3.3,
        planned_credit=4.2,
        planned_legs=2,
    )
    fields = map_duty_period_fields(duty, mode=ImportMode.ACTUAL)
    assert fields[F.F_DUTY_REPORT_TIME] == 1784919000
    assert fields[F.F_DUTY_RELEASE_TIME] - fields[F.F_DUTY_REPORT_TIME] == 5 * 3600 + 8 * 60


# --- duty periods ----------------------------------------------------------

def test_map_duty_period_fields() -> None:
    duty = PlannedDutyPeriodRecord(
        duty_period_key="E3058E|2026-05-09|2026-05-09",
        trip_key="E3058E|2026-05-09",
        duty_date=date(2026, 5, 9),
        report_at=datetime(2026, 5, 9, 11, 45, tzinfo=timezone.utc),
        release_at=datetime(2026, 5, 9, 23, 30, tzinfo=timezone.utc),
        planned_block=6.5,
        planned_credit=7.2,
        planned_legs=4,
        status="Planned",
    )
    fields = map_duty_period_fields(duty)
    assert fields[F.F_DUTY_PERIOD_KEY] == "E3058E|2026-05-09|2026-05-09"
    assert fields[F.F_DUTY_DATE] == format_grist_date(date(2026, 5, 9))
    assert fields[F.F_DUTY_REPORT_TIME] == format_grist_datetime(duty.report_at)
    assert fields[F.F_DUTY_PLANNED_BLOCK] == 6.5
    # Actual mode: no planned writes.
    actual = map_duty_period_fields(duty, mode=ImportMode.ACTUAL)
    assert F.F_DUTY_PLANNED_BLOCK not in actual
    assert F.F_DUTY_ACTUAL_CREDIT not in actual   # no Day Total credit set


def test_map_duty_period_fields_actual_credit() -> None:
    duty = PlannedDutyPeriodRecord(
        duty_period_key="O1251|2026-07-22|2026-07-23",
        trip_key="O1251|2026-07-22",
        duty_date=date(2026, 7, 23),
        report_at=datetime(2026, 7, 23, 22, 40, tzinfo=timezone.utc),
        release_at=datetime(2026, 7, 24, 4, 25, tzinfo=timezone.utc),
        planned_block=4.0,
        planned_credit=4.2,
        planned_legs=2,
        status="Actual",
        actual_credit=4.2,
    )
    assert map_duty_period_fields(duty, mode=ImportMode.ACTUAL)[F.F_DUTY_ACTUAL_CREDIT] == 4.2
    assert F.F_DUTY_ACTUAL_CREDIT not in map_duty_period_fields(duty, mode=ImportMode.PLANNED)


# --- flights ---------------------------------------------------------------

def _flight(**overrides) -> PlannedFlightRecord:
    base = dict(
        import_flight_key="E3058E|2026-05-09|4283",
        trip_key="E3058E|2026-05-09",
        duty_period_key="E3058E|2026-05-09|2026-05-09",
        duty_date=date(2026, 5, 9),
        flight_number="4283",
        origin="BJI",
        destination="MSP",
        out_time=datetime(2026, 5, 9, 12, 0, tzinfo=timezone.utc),
        in_time=datetime(2026, 5, 9, 13, 10, tzinfo=timezone.utc),
        block_hours=1.2,
        credit_hours=1.2,
        pic_hours=0.0,
        sic_hours=1.2,
        flight_position="SIC",
        deadhead=False,
        aircraft_code="CR9",
        operation="Part 121",
        airline="SKW",
        tail_number="N932SW",
        passengers=50,
    )
    base.update(overrides)
    return PlannedFlightRecord(**base)


def test_map_flight_fields() -> None:
    fields = map_flight_fields(_flight())
    assert fields[F.F_IMPORT_FLIGHT_KEY] == "E3058E|2026-05-09|4283"
    assert fields[F.F_FLIGHT_DATE] == format_grist_date(date(2026, 5, 9))
    assert fields[F.F_FLIGHT_OUT_TIME] == format_grist_datetime(
        datetime(2026, 5, 9, 12, 0, tzinfo=timezone.utc)
    )
    assert fields[F.F_FLIGHT_XC_TIME] == 1.2   # non-deadhead: XC = block
    assert fields[F.F_FLIGHT_DEADHEAD] is False
    assert fields[F.F_FLIGHT_PASSENGERS] == 50


def test_map_flight_fields_deadhead_zero_xc() -> None:
    fields = map_flight_fields(_flight(deadhead=True))
    assert fields[F.F_FLIGHT_XC_TIME] == 0.0
    assert fields[F.F_FLIGHT_DEADHEAD] is True


def test_map_flight_fields_special_categories_choicelist() -> None:
    fields = map_flight_fields(_flight(special_categories=["SDuty", "Ferry"]))
    assert fields[F.F_FLIGHT_SPECIAL_CATEGORY] == ["L", "SDuty", "Ferry"]


def test_map_flight_fields_rejects_naive_datetimes() -> None:
    with pytest.raises(ValueError, match="UTC-aware"):
        map_flight_fields(_flight(out_time=datetime(2026, 5, 9, 12, 0)))


# --- import batch ----------------------------------------------------------

def test_map_import_batch_fields() -> None:
    batch = ImportBatchRecord(
        batch_name="E3058E|2026-05-09|Actual",
        import_type="Actual",
        source_folder="inbox",
        source_filename="121807_20260509_E3058E.txt",
        import_status="Imported",
    )
    imported_at = datetime(2026, 7, 21, 15, 0, tzinfo=timezone.utc)
    fields = map_import_batch_fields(batch, imported_at=imported_at)
    assert fields[F.F_BATCH_NAME] == "E3058E|2026-05-09|Actual"
    assert fields[F.F_BATCH_IMPORT_DATETIME] == format_grist_datetime(imported_at)
    assert fields[F.F_BATCH_IMPORT_STATUS] == "Imported"


def test_map_duty_period_fields_airports_both_modes() -> None:
    duty = PlannedDutyPeriodRecord(
        duty_period_key="O1251|2026-07-22|2026-07-24",
        trip_key="O1251|2026-07-22",
        duty_date=date(2026, 7, 24),
        report_at=datetime(2026, 7, 24, 18, 50, tzinfo=timezone.utc),
        release_at=datetime(2026, 7, 24, 23, 58, tzinfo=timezone.utc),
        planned_block=3.3,
        planned_credit=4.2,
        planned_legs=2,
        report_airport="EAU",
        release_airport="LNS",
    )
    for mode in (ImportMode.PLANNED, ImportMode.ACTUAL):
        fields = map_duty_period_fields(duty, mode=mode)
        assert fields[F.F_DUTY_REPORT_AIRPORT] == "EAU"
        assert fields[F.F_DUTY_RELEASE_AIRPORT] == "LNS"


def test_format_batch_notes() -> None:
    assert format_batch_notes([]) == ""
    assert format_batch_notes(["a", "b"], errors=["boom"]) == "ERROR: boom\nWARN: a\nWARN: b"
