from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from logbook_import.config import INBOX_DIR
from logbook_import.keys import (
    duty_period_key,
    import_flight_key,
    normalize_flight_number,
    normalize_pairing_id,
    trip_key,
)
from logbook_import.leg_classifier import is_deadhead, is_loggable_flight
from logbook_import.models import (
    CrewRole,
    DutyDay,
    ImportBatchRecord,
    ImportMode,
    ImportPlan,
    Operator,
    PairingExport,
    PlannedDutyPeriodRecord,
    PlannedFlightRecord,
    PlannedTripRecord,
)
from logbook_import.time_utils import combine_date_time, combine_report_release


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


# SkyWest labels the CRJ-200 "CRJ" in the CSV A/C Type. The Grist Aircraft
# table keys it as "CR2".
AIRCRAFT_CODE_ALIASES = {"CRJ": "CR2"}


def normalize_aircraft_code(code: str | None) -> str | None:
    if not code:
        return code
    code = code.strip().upper()
    return AIRCRAFT_CODE_ALIASES.get(code, code)


def duty_airports(duty: DutyDay) -> tuple[str, str]:
    """(report, release) IATA codes as the schedule lines print them.

    Report = first schedule line's origin; release = last schedule line's
    destination. Placeholder lines (CXL/FDP/REF/RDY...) are included on purpose:
    they sit at the crew's station and often carry the exact report/release
    clock. Returns ("", "") for a duty day with no schedule lines.
    """
    if not duty.legs:
        return "", ""
    return duty.legs[0].origin.strip().upper(), duty.legs[-1].destination.strip().upper()


# Allowed gap between the duty length computed from report/release and the
# "Duty: H:MM" SkedPlus prints on the Day Total line (parser rounds to 0.1 h).
DUTY_HOURS_TOLERANCE = 0.1


def duty_report_release_utc(
    duty: DutyDay,
    airport_index: dict[str, dict] | None,
) -> tuple[datetime, datetime, list[str]]:
    """
    Report/release datetimes for one duty period, as UTC-aware datetimes.

    SkedPlus prints the report clock in the report airport's local time and the
    release clock in the release airport's local time.  The airports come from
    ``duty_airports`` (first line origin / last line destination).

    The after-midnight rollover is applied AFTER converting to UTC: if release
    UTC <= report UTC, release is the next day (a duty period is < 24 h).

    Falls back to naive ``combine_report_release`` (the pre-timezone behavior)
    with a warning when a zone is missing.  Also warns when the computed duty
    length disagrees with the parser's ``DutyDay.duty_hours`` by more than
    ``DUTY_HOURS_TOLERANCE``.
    """
    warnings: list[str] = []
    if not duty.legs:
        warnings.append(
            "No schedule lines in duty day; report/release zones unknown, "
            "times left naive (incorrect)"
        )
        report_at, release_at = combine_report_release(
            duty.duty_date, duty.report_time, duty.release_time
        )
        return report_at, release_at, warnings

    report_iata, release_iata = duty_airports(duty)
    report_ap = (airport_index or {}).get(report_iata)
    release_ap = (airport_index or {}).get(release_iata)

    missing = None
    if not report_ap or not report_ap.get("tz"):
        missing = f"No timezone for report airport {report_iata}; times left naive (incorrect)"
    elif not release_ap or not release_ap.get("tz"):
        missing = f"No timezone for release airport {release_iata}; times left naive (incorrect)"
    if missing:
        warnings.append(missing)
        report_at, release_at = combine_report_release(
            duty.duty_date, duty.report_time, duty.release_time
        )
        return report_at, release_at, warnings

    report_utc = (
        combine_date_time(duty.duty_date, duty.report_time)
        .replace(tzinfo=ZoneInfo(report_ap["tz"]))
        .astimezone(timezone.utc)
    )
    release_utc = (
        combine_date_time(duty.duty_date, duty.release_time)
        .replace(tzinfo=ZoneInfo(release_ap["tz"]))
        .astimezone(timezone.utc)
    )
    if release_utc <= report_utc:
        release_utc += timedelta(days=1)

    if duty.duty_hours:
        computed = (release_utc - report_utc).total_seconds() / 3600.0
        if abs(computed - duty.duty_hours) > DUTY_HOURS_TOLERANCE:
            note = (
                " (SDuty: the sheet's Duty likely excludes the split-duty rest)"
                if duty.sduty
                else ""
            )
            warnings.append(
                f"Computed duty {computed:.2f} h ({report_iata} report -> "
                f"{release_iata} release) differs from SkedPlus Duty "
                f"{duty.duty_hours} h{note}"
            )

    return report_utc, release_utc, warnings


def day_actual_credit(duty: DutyDay) -> float:
    """Duty_Periods.Actual_Credit: the day's Day Total credit from exact minutes,
    rounded to 0.01 h (so a trip's duty values add up to its Actual_Credit)."""
    return round(duty.day_credit_minutes / 60.0, 2)


def trip_actual_credit(pairing: PairingExport) -> float:
    """Trips.Actual_Credit: sum of the trip's Day Total credits, in hours.

    Summed in exact minutes, then rounded to 0.01 h. Not the header "Credit:"
    (stale on reassigned trips) and no per-day minimum: the Day Totals match
    the pay report's Processed Credit.
    """
    return round(sum(duty.day_credit_minutes for duty in pairing.duty_days) / 60.0, 2)


def _hmm(minutes: int) -> str:
    return f"{minutes // 60}:{minutes % 60:02d}"


def trip_credit_check(pairing: PairingExport) -> str | None:
    """Warn when the header "Credit:" differs from the sum of the Day Totals.

    Exact minutes. A difference usually means the trip was reassigned (the
    header is stale). The leg credit sum is printed for context only. Returns
    the warning text, or None when they match.
    """
    day_sum = sum(duty.day_credit_minutes for duty in pairing.duty_days)
    if pairing.credit_minutes == day_sum:
        return None
    leg_sum = sum(leg.credit_minutes for duty in pairing.duty_days for leg in duty.legs)
    return (
        f"Trip credit check {pairing.pairing_id} {pairing.start_date.isoformat()}: "
        f"header Credit {_hmm(pairing.credit_minutes)} != sum of Day Totals "
        f"{_hmm(day_sum)} (sum of leg credit {_hmm(leg_sum)})"
    )


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
    batch_name = (
        f"{normalize_pairing_id(pairing.pairing_id)}|"
        f"{pairing.start_date.isoformat()}|{status_label}"
    )
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
        pairing_id=normalize_pairing_id(pairing.pairing_id),
        start_date=pairing.start_date,
        end_date=pairing.end_date,
        # Base = origin of the first schedule line, never the txt header (R3/R4).
        base=pairing.first_origin,
        equipment_family=pairing.equipment_family,
        planned_block=pairing.block_hours,
        planned_credit=pairing.credit_hours,
        planned_duty_periods=len(pairing.duty_days),
        planned_legs=planned_legs_total,
        tafb_hours=pairing.tafb_hours,
        status="Planned" if mode == ImportMode.PLANNED else "Actual",
        actual_credit=trip_actual_credit(pairing) if mode == ImportMode.ACTUAL else None,
    )

    duty_records: list[PlannedDutyPeriodRecord] = []
    flight_records: list[PlannedFlightRecord] = []
    tz_warnings: list[str] = []

    operation = _operation_for_operator(operator)
    airline = _airline_for_operator(operator)

    if mode == ImportMode.ACTUAL:
        trip_credit_warn = trip_credit_check(pairing)
        if trip_credit_warn:
            tz_warnings.append(f"{t_key}: {trip_credit_warn}")

    for duty in pairing.duty_days:
        dp_key = duty_period_key(pairing.pairing_id, pairing.start_date, duty.duty_date)
        is_future_duty = (mode == ImportMode.ACTUAL and duty.duty_date > today)
        report_at, release_at, duty_warns = duty_report_release_utc(duty, airport_index)
        report_airport, release_airport = duty_airports(duty)
        for w in duty_warns:
            tz_warnings.append(f"{dp_key}: {w}")

        flown = mode == ImportMode.ACTUAL and not is_future_duty
        if not flown:
            duty_status = "Planned"  # planned import, or a future day on an actual import
        elif any(is_loggable_flight(leg) for leg in duty.legs):
            duty_status = "Actual"
        else:
            duty_status = "Cancelled"  # flown trip, no flight lines this day (R9)
        duty_records.append(
            PlannedDutyPeriodRecord(
                duty_period_key=dp_key,
                trip_key=t_key,
                duty_date=duty.duty_date,
                report_at=report_at,
                release_at=release_at,
                planned_block=duty.day_block_hours,
                planned_credit=duty.day_credit_hours,
                planned_legs=duty.planned_leg_count,
                status=duty_status,
                actual_credit=day_actual_credit(duty) if flown else None,
                report_airport=report_airport,
                release_airport=release_airport,
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

            # Aircraft comes only from the flight line (CSV A/C Type). The txt
            # header is not trip data (R5): no fallback, leave the link blank.
            aircraft_code = normalize_aircraft_code(leg.aircraft_type)
            if not aircraft_code and not deadhead:  # deadhead lines carry no A/C Type
                tz_warnings.append(
                    f"{if_key}: no aircraft type on this flight line (CSV A/C Type); "
                    f"Aircraft link left blank"
                )

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
                    aircraft_code=aircraft_code,
                    operation=operation,
                    airline=airline,
                    # Passenger totals count only flights the user operated.
                    passengers=0 if deadhead else leg.pax,
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
