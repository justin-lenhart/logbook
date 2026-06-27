from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from logbook_import.config import INBOX_DIR
from logbook_import.keys import (
    duty_period_key,
    import_flight_key,
    normalize_flight_number,
    trip_key,
)
from logbook_import.leg_classifier import is_deadhead, is_loggable_flight
from logbook_import.models import (
    CrewRole,
    ImportBatchRecord,
    ImportMode,
    ImportPlan,
    Operator,
    PairingExport,
    PlannedDutyPeriodRecord,
    PlannedFlightRecord,
    PlannedTripRecord,
)
from logbook_import.time_utils import combine_date_time


def _to_utc(
    duty_date: date,
    dep_local: time,
    arr_local: time,
    origin_iata: str,
    dest_iata: str,
    airport_index: dict[str, dict] | None,
) -> tuple[datetime, datetime, list[str]]:
    """
    Convert SkedPlus local departure/arrival times to UTC using each airport's
    IANA timezone.  If the arrival local datetime is earlier than the departure
    local datetime (after attaching timezones and converting to UTC), bump the
    arrival forward one day — this is the "leg crosses midnight" case.

    Falls back to naive datetimes (existing behavior) with a warning when an
    airport or its timezone is missing from the index.
    """
    warnings: list[str] = []
    origin = (airport_index or {}).get(origin_iata.upper()) if airport_index else None
    dest = (airport_index or {}).get(dest_iata.upper()) if airport_index else None

    if not origin or not origin.get("tz"):
        warnings.append(f"No timezone for origin {origin_iata}; times left naive (incorrect)")
        return (
            combine_date_time(duty_date, dep_local),
            combine_date_time(duty_date, arr_local),
            warnings,
        )
    if not dest or not dest.get("tz"):
        warnings.append(f"No timezone for destination {dest_iata}; times left naive (incorrect)")
        return (
            combine_date_time(duty_date, dep_local),
            combine_date_time(duty_date, arr_local),
            warnings,
        )

    dep_aware = combine_date_time(duty_date, dep_local).replace(tzinfo=ZoneInfo(origin["tz"]))
    arr_aware = combine_date_time(duty_date, arr_local).replace(tzinfo=ZoneInfo(dest["tz"]))

    out_utc = dep_aware.astimezone(timezone.utc)
    in_utc = arr_aware.astimezone(timezone.utc)

    if in_utc < out_utc:
        in_utc = in_utc + timedelta(days=1)

    return out_utc, in_utc, warnings


def _operation_for_operator(operator: Operator | None) -> str | None:
    if operator == Operator.SKW:
        return "Part 121"
    return None


def _airline_for_operator(operator: Operator | None) -> str | None:
    if operator == Operator.SKW:
        return "SKW"
    return None


def _import_type_label(mode: ImportMode) -> str:
    return "Planned" if mode == ImportMode.PLANNED else "Actual"


def build_import_batch(
    pairing: PairingExport,
    mode: ImportMode,
) -> ImportBatchRecord:
    status_label = _import_type_label(mode)
    batch_name = f"{pairing.pairing_id}|{pairing.start_date.isoformat()}|{status_label}"
    source_filename = Path(pairing.source_txt).name if pairing.source_txt else ""
    return ImportBatchRecord(
        batch_name=batch_name,
        import_type=status_label,
        source_filename=source_filename,
        source_folder=INBOX_DIR.name,
    )


def _pic_sic_hours(
    block_hours: float,
    role: CrewRole | None,
    deadhead: bool,
) -> tuple[float, float]:
    if deadhead:
        return 0.0, 0.0
    if role == CrewRole.PIC:
        return block_hours, 0.0
    if role == CrewRole.SIC:
        return 0.0, block_hours
    return 0.0, 0.0


def _flight_position(role: CrewRole | None, deadhead: bool) -> str:
    # Deadhead legs are flown as a passenger — no logged position.
    if deadhead:
        return ""
    if role == CrewRole.PIC:
        return "PIC"
    if role == CrewRole.SIC:
        return "SIC"
    return ""


def build_import_plan(
    pairing: PairingExport,
    mode: ImportMode,
    role: CrewRole | None = None,
    operator: Operator | None = None,
    airport_index: dict[str, dict] | None = None,
) -> ImportPlan:
    today = date.today()
    t_key = trip_key(pairing.pairing_id, pairing.start_date)
    planned_legs_total = sum(duty.planned_leg_count for duty in pairing.duty_days)

    trip = PlannedTripRecord(
        trip_key=t_key,
        pairing_id=pairing.pairing_id,
        start_date=pairing.start_date,
        end_date=pairing.end_date,
        base=pairing.base,
        equipment_family=pairing.equipment_family,
        planned_block=pairing.block_hours,
        planned_credit=pairing.credit_hours,
        planned_duty_periods=len(pairing.duty_days),
        planned_legs=planned_legs_total,
        tafb_hours=pairing.tafb_hours,
        status="Planned" if mode == ImportMode.PLANNED else "Actual",
    )

    duty_records: list[PlannedDutyPeriodRecord] = []
    flight_records: list[PlannedFlightRecord] = []
    tz_warnings: list[str] = []

    operation = _operation_for_operator(operator)
    airline = _airline_for_operator(operator)

    for duty in pairing.duty_days:
        dp_key = duty_period_key(pairing.pairing_id, pairing.start_date, duty.duty_date)
        is_future_duty = (mode == ImportMode.ACTUAL and duty.duty_date > today)
        duty_records.append(
            PlannedDutyPeriodRecord(
                duty_period_key=dp_key,
                trip_key=t_key,
                duty_date=duty.duty_date,
                report_at=combine_date_time(duty.duty_date, duty.report_time),
                release_at=combine_date_time(duty.duty_date, duty.release_time),
                planned_block=duty.day_block_hours,
                planned_credit=duty.day_credit_hours,
                planned_legs=duty.planned_leg_count,
                status="Planned" if (mode == ImportMode.PLANNED or is_future_duty) else "Actual",
            )
        )

        if mode != ImportMode.ACTUAL:
            continue

        special_categories = ["SDuty"] if duty.sduty else []

        for leg in duty.legs:
            if not is_loggable_flight(leg):
                continue

            # Use the per-leg calendar date when available (SDuty continuation
            # legs get the next-day date from the parser even though they share
            # a DutyDay with the evening legs).
            leg_date = leg.duty_date if leg.duty_date is not None else duty.duty_date

            if leg_date > today:
                continue  # flight hasn't happened yet; leave for post-trip import

            deadhead = is_deadhead(leg)
            pic_hours, sic_hours = _pic_sic_hours(leg.block_hours, role, deadhead)
            flight_position = _flight_position(role, deadhead)
            flight_num = normalize_flight_number(leg.flight)
            if_key = import_flight_key(
                pairing.pairing_id,
                leg_date,
                flight_num,
                leg.origin,
                leg.destination,
                leg.departure,
            )

            out_utc, in_utc, warns = _to_utc(
                leg_date,
                leg.departure,
                leg.arrival,
                leg.origin,
                leg.destination,
                airport_index,
            )
            for w in warns:
                tz_warnings.append(f"{if_key}: {w}")

            flight_records.append(
                PlannedFlightRecord(
                    import_flight_key=if_key,
                    trip_key=t_key,
                    duty_period_key=dp_key,
                    duty_date=leg_date,
                    flight_number=flight_num,
                    tail_number=leg.tail,
                    origin=leg.origin.upper(),
                    destination=leg.destination.upper(),
                    out_time=out_utc,
                    in_time=in_utc,
                    block_hours=leg.block_hours,
                    credit_hours=leg.credit_hours,
                    pic_hours=pic_hours,
                    sic_hours=sic_hours,
                    flight_position=flight_position,
                    deadhead=deadhead,
                    aircraft_code=leg.aircraft_type or pairing.equipment_family,
                    operation=operation,
                    airline=airline,
                    passengers=leg.pax,
                    special_categories=special_categories,
                )
            )

    return ImportPlan(
        mode=mode,
        pairing_id=pairing.pairing_id,
        source_txt=str(pairing.source_txt) if pairing.source_txt else "",
        source_csv=str(pairing.source_csv) if pairing.source_csv else None,
        trips=[trip],
        duty_periods=duty_records,
        flights=flight_records,
        import_batch=build_import_batch(pairing, mode),
        warnings=tz_warnings,
    )


def build_plans_for_exports(
    pairings: list[PairingExport],
    mode: ImportMode,
    role: CrewRole | None = None,
    operator: Operator | None = None,
    airport_index: dict[str, dict] | None = None,
) -> list[ImportPlan]:
    return [
        build_import_plan(p, mode, role=role, operator=operator, airport_index=airport_index)
        for p in pairings
    ]
