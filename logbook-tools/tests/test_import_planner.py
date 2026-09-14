from datetime import date, time

from logbook_import.config import PairingFileSet
from logbook_import.import_planner import build_import_plan
from logbook_import.models import CrewRole, DutyDay, ImportMode, Operator, PairingExport
from logbook_import.parsers.merge import load_pairing_export


def _load(txt, csv):
    pairing, _ = load_pairing_export(PairingFileSet("X", txt_path=txt, csv_path=csv))
    return pairing


def test_overnight_release_rolls_to_next_day() -> None:
    # Modeled on the O1262A sheet: Report 15:14 / Release 00:02 the next morning.
    pairing = PairingExport(
        employee_id="121807",
        employee_name="Test Pilot",
        base="MSP",
        equipment_family="CR7",
        role="FO",
        pairing_id="O1262A",
        start_date=date(2026, 7, 2),
        block_hours=0.0,
        credit_hours=0.0,
        tafb_hours=0.0,
        duty_days=[DutyDay(date(2026, 7, 2), time(15, 14), time(0, 2))],
    )
    plan = build_import_plan(pairing, ImportMode.PLANNED)
    dp = plan.duty_periods[0]
    assert dp.report_at.date() == date(2026, 7, 2)
    assert dp.release_at.date() == date(2026, 7, 3)
    assert dp.release_at > dp.report_at


def test_planned_import_has_no_flights(e3058e_txt, e3058e_csv) -> None:
    pairing = _load(e3058e_txt, e3058e_csv)
    plan = build_import_plan(pairing, ImportMode.PLANNED)
    assert len(plan.trips) == 1
    assert len(plan.duty_periods) == 4
    assert len(plan.flights) == 0
    assert plan.trips[0].planned_legs == 14
    assert plan.trips[0].planned_duty_periods == 4


def test_actual_import_e3058e(e3058e_txt, e3058e_csv) -> None:
    pairing = _load(e3058e_txt, e3058e_csv)
    plan = build_import_plan(
        pairing,
        ImportMode.ACTUAL,
        role=CrewRole.SIC,
        operator=Operator.SKW,
    )
    assert len(plan.flights) == 10
    first = plan.flights[0]
    # Import Flight Key collapses the E3058E revision suffix to its base (E3058).
    assert first.import_flight_key == "E3058|2026-05-09|4266|MSP|INL|1252"
    assert first.sic_hours == first.block_hours
    assert first.pic_hours == 0.0
    assert first.flight_position == "SIC"
    assert first.operation == "Part 121"
    assert first.airline == "SKW"
    assert first.aircraft_code == "CR5"
    assert plan.import_batch.import_type == "Actual"
    assert plan.import_batch.batch_name == "E3058E|2026-05-09|Actual"


def test_actual_import_e7748_includes_deadhead(e7748_txt, e7748_csv) -> None:
    pairing = _load(e7748_txt, e7748_csv)
    plan = build_import_plan(
        pairing,
        ImportMode.ACTUAL,
        role=CrewRole.SIC,
        operator=Operator.SKW,
    )
    assert len(plan.flights) == 3
    deadheads = [f for f in plan.flights if f.deadhead]
    assert len(deadheads) == 1
    assert deadheads[0].flight_number == "1303"
    assert deadheads[0].pic_hours == 0.0
    assert deadheads[0].sic_hours == 0.0
    assert deadheads[0].flight_position == ""


def test_planned_import_e7748(e7748_txt, e7748_csv) -> None:
    pairing = _load(e7748_txt, e7748_csv)
    plan = build_import_plan(pairing, ImportMode.PLANNED)
    assert plan.trips[0].planned_legs == 3
    assert len(plan.flights) == 0
