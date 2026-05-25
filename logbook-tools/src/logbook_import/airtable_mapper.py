from __future__ import annotations

from datetime import date, datetime
from typing import Any

from logbook_import import airtable_fields as F
from logbook_import.models import (
    ImportBatchRecord,
    ImportMode,
    PlannedDutyPeriodRecord,
    PlannedFlightRecord,
    PlannedTripRecord,
)


def format_airtable_date(value: date) -> str:
    return value.isoformat()


def format_airtable_datetime(value: datetime) -> str:
    return value.isoformat()


def map_trip_fields(
    trip: PlannedTripRecord,
    *,
    mode: ImportMode = ImportMode.PLANNED,
    include_equipment_family: bool = False,
) -> dict[str, Any]:
    fields: dict[str, Any] = {
        F.F_TRIP_KEY: trip.trip_key,
        F.F_TRIP_PAIRING_ID: trip.pairing_id,
        F.F_TRIP_STATUS: trip.status,
        F.F_TRIP_START_DATE: format_airtable_date(trip.start_date),
        F.F_TRIP_END_DATE: format_airtable_date(trip.end_date),
        F.F_TRIP_BASE: trip.base,
    }
    # Only write planned fields on planned import — preserves the original scheduled
    # values when the same trip is later imported as actual (upsert won't clear them).
    if mode == ImportMode.PLANNED:
        fields[F.F_TRIP_PLANNED_BLOCK] = trip.planned_block
        fields[F.F_TRIP_PLANNED_CREDIT] = trip.planned_credit
        fields[F.F_TRIP_PLANNED_LEGS] = trip.planned_legs
        fields[F.F_TRIP_PLANNED_DUTY_PERIODS] = trip.planned_duty_periods
    if include_equipment_family:
        fields[F.F_TRIP_EQUIPMENT_FAMILY] = trip.equipment_family
    return fields


def map_duty_period_fields(
    duty: PlannedDutyPeriodRecord,
    *,
    mode: ImportMode = ImportMode.PLANNED,
) -> dict[str, Any]:
    fields: dict[str, Any] = {
        F.F_DUTY_PERIOD_KEY: duty.duty_period_key,
        F.F_DUTY_STATUS: duty.status,
        F.F_DUTY_DATE: format_airtable_date(duty.duty_date),
        F.F_DUTY_REPORT_TIME: format_airtable_datetime(duty.report_at),
        F.F_DUTY_RELEASE_TIME: format_airtable_datetime(duty.release_at),
    }
    if mode == ImportMode.PLANNED:
        fields[F.F_DUTY_PLANNED_BLOCK] = duty.planned_block
        fields[F.F_DUTY_PLANNED_CREDIT] = duty.planned_credit
        fields[F.F_DUTY_PLANNED_LEGS] = duty.planned_legs
    return fields


def map_flight_fields(flight: PlannedFlightRecord) -> dict[str, Any]:
    fields: dict[str, Any] = {
        F.F_IMPORT_FLIGHT_KEY: flight.import_flight_key,
        F.F_FLIGHT_DATE: format_airtable_date(flight.duty_date),
        F.F_FLIGHT_NUMBER: flight.flight_number,
        F.F_FLIGHT_OUT_TIME: format_airtable_datetime(flight.out_time),
        F.F_FLIGHT_IN_TIME: format_airtable_datetime(flight.in_time),
        F.F_FLIGHT_BLOCK_TIME: flight.block_hours,
        F.F_FLIGHT_CREDIT_TIME: flight.credit_hours,
        F.F_FLIGHT_PIC_TIME: flight.pic_hours,
        F.F_FLIGHT_SIC_TIME: flight.sic_hours,
        F.F_FLIGHT_XC_TIME: 0.0 if flight.deadhead else flight.block_hours,
        F.F_FLIGHT_DEADHEAD: flight.deadhead,
    }
    if flight.airline:
        fields[F.F_FLIGHT_AIRLINE] = flight.airline
    if flight.tail_number:
        fields[F.F_FLIGHT_TAIL] = flight.tail_number
    if flight.operation:
        fields[F.F_FLIGHT_OPERATION] = flight.operation
    if flight.special_categories:
        fields[F.F_FLIGHT_SPECIAL_CATEGORY] = flight.special_categories
    return fields


def map_import_batch_fields(
    batch: ImportBatchRecord,
    *,
    imported_at: datetime,
) -> dict[str, Any]:
    return {
        F.F_BATCH_NAME: batch.batch_name,
        F.F_BATCH_IMPORT_TYPE: batch.import_type,
        F.F_BATCH_IMPORT_DATETIME: format_airtable_datetime(imported_at),
        F.F_BATCH_SOURCE_FOLDER: batch.source_folder,
        F.F_BATCH_SOURCE_FILENAME: batch.source_filename,
        F.F_BATCH_IMPORT_STATUS: batch.import_status,
    }
