from datetime import date, datetime, time, timezone

from logbook_import.config import PairingFileSet
from logbook_import.import_planner import (
    build_import_plan,
    day_credit_check,
    duty_report_release_utc,
    normalize_aircraft_code,
)
from logbook_import.models import CrewRole, DutyDay, ImportMode, Leg, Operator, PairingExport
from logbook_import.parsers.merge import load_pairing_export
from logbook_import.parsers.skedplus_txt import parse_skedplus_txt

UTC = timezone.utc

# Synthetic airport index (no network): IATA -> tz, like grist_airports builds.
AIRPORTS = {
    code: {"record_id": i, "tz": tz, "lat": 0.0, "lon": 0.0}
    for i, (code, tz) in enumerate(
        {
            "ORD": "America/Chicago",
            "EAU": "America/Chicago",
            "EAR": "America/Chicago",
            "SUX": "America/Chicago",
            "DEN": "America/Denver",
            "LNS": "America/New_York",
            "GRB": "America/Chicago",
            "ATY": "America/Chicago",
            "MSP": "America/Chicago",
        }.items(),
        start=1,
    )
}


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
    # 14 schedule lines minus 3 RDY + 1 NMD (0:00 same-station placeholders).
    assert plan.trips[0].planned_legs == 10
    assert plan.trips[0].planned_duty_periods == 4
    assert plan.trips[0].actual_credit is None
    assert all(dp.actual_credit is None for dp in plan.duty_periods)


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
    assert plan.import_batch.batch_name == "E3058|2026-05-09|Actual"
    trip = plan.trips[0]
    assert trip.pairing_id == "E3058"     # suffix removed (R2)
    assert trip.trip_key == "E3058|2026-05-09"
    assert trip.base == pairing.duty_days[0].legs[0].origin
    assert trip.actual_credit == 19.3     # header Credit: 19:17 (R7)


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



# --- duty period report/release time zones --------------------------------

def _line(n, flight, org, dst, dep, arr, block=1.0, tail="N975SW", dhd=""):
    return Leg(
        leg_number=n, flight=flight, tail=tail, origin=org, destination=dst,
        departure=time(*dep), arrival=time(*arr), pax=0 if tail is None else 30,
        block_hours=block, credit_hours=block, deadhead_indicator=dhd,
    )


def test_duty_cross_zone_central_report_eastern_release() -> None:
    # O1251 day 3: Report EAU 13:50 (CDT), Release LNS 19:58 (EDT). SkedPlus Duty 5:08.
    duty = DutyDay(
        date(2026, 7, 24), time(13, 50), time(19, 58),
        legs=[
            _line(6, "5122", "EAU", "ORD", (14, 36), (16, 5)),
            _line(7, "6060", "ORD", "LNS", (16, 55), (19, 43)),
        ],
        duty_hours=5.1,
    )
    report, release, warns = duty_report_release_utc(duty, AIRPORTS)
    assert report == datetime(2026, 7, 24, 18, 50, tzinfo=UTC)
    assert release == datetime(2026, 7, 24, 23, 58, tzinfo=UTC)
    assert (release - report).total_seconds() == 5 * 3600 + 8 * 60
    assert warns == []


def test_duty_same_zone_utc_crosses_midnight_without_extra_day() -> None:
    # O1251 day 1: ORD 14:50 -> DLH 23:37, both Central. Release is 04:37Z the
    # next UTC day but the SAME local day; must not add an extra 24 h.
    duty = DutyDay(
        date(2026, 7, 22), time(14, 50), time(23, 37),
        legs=[
            _line(1, "5907", "ORD", "GRB", (15, 26), (16, 51)),
            _line(2, "4681", "GRB", "ORD", (18, 50), (20, 15)),
        ],
        duty_hours=8.8,
    )
    report, release, warns = duty_report_release_utc(duty, AIRPORTS)
    assert report == datetime(2026, 7, 22, 19, 50, tzinfo=UTC)
    assert release == datetime(2026, 7, 23, 4, 37, tzinfo=UTC)
    assert warns == []


def test_duty_after_midnight_release_rolls_after_utc_conversion() -> None:
    # O1262A day 1: Report ORD 15:14 CDT, Release EAR "00:02/03" CDT. Duty 8:48.
    duty = DutyDay(
        date(2026, 7, 2), time(15, 14), time(0, 2),
        legs=[
            _line(1, "5021", "ORD", "SUX", (16, 19), (18, 10)),
            _line(2, "5021", "SUX", "DEN", (18, 39), (20, 21)),
            _line(3, "5059", "DEN", "EAR", (20, 56), (23, 47)),
        ],
        duty_hours=8.8,
    )
    report, release, warns = duty_report_release_utc(duty, AIRPORTS)
    assert report == datetime(2026, 7, 2, 20, 14, tzinfo=UTC)
    assert release == datetime(2026, 7, 3, 5, 2, tzinfo=UTC)
    assert warns == []


def test_duty_missing_zone_falls_back_naive_with_warning() -> None:
    duty = DutyDay(
        date(2026, 7, 2), time(15, 14), time(0, 2),
        legs=[_line(1, "5021", "ORD", "XXX", (16, 19), (18, 10))],
        duty_hours=8.8,
    )
    report, release, warns = duty_report_release_utc(duty, AIRPORTS)
    assert report == datetime(2026, 7, 2, 15, 14)
    assert release == datetime(2026, 7, 3, 0, 2)
    assert report.tzinfo is None and release.tzinfo is None
    assert len(warns) == 1 and "XXX" in warns[0] and "times left naive" in warns[0]

    # No airport index at all (dry-run without creds) -> same fallback.
    _, _, warns = duty_report_release_utc(duty, None)
    assert "times left naive" in warns[0]


def test_duty_hours_mismatch_warns() -> None:
    # Same O1251 day 3 but the sheet says 6:08 -> computed 5:08 is off by 1 h.
    duty = DutyDay(
        date(2026, 7, 24), time(13, 50), time(19, 58),
        legs=[_line(7, "6060", "EAU", "LNS", (16, 55), (19, 43))],
        duty_hours=6.1,
    )
    _, _, warns = duty_report_release_utc(duty, AIRPORTS)
    assert len(warns) == 1 and "differs from SkedPlus Duty" in warns[0]


def test_build_plan_duty_periods_are_utc_and_warnings_prefixed() -> None:
    pairing = PairingExport(
        employee_id="1", employee_name="Test Pilot", base="ORD",
        equipment_family="CRJ", role="FO", pairing_id="O1251",
        start_date=date(2026, 7, 24), block_hours=3.3, credit_hours=4.2, tafb_hours=0.0,
        duty_days=[
            DutyDay(
                date(2026, 7, 24), time(13, 50), time(19, 58),
                legs=[_line(7, "6060", "EAU", "XXX", (16, 55), (19, 43))],
                duty_hours=5.1,
            )
        ],
    )
    plan = build_import_plan(pairing, ImportMode.PLANNED, airport_index=AIRPORTS)
    assert plan.warnings[0].startswith("O1251|2026-07-24|2026-07-24: No timezone")


# --- placeholder schedule lines (CXL / FDP / REF) --------------------------

SANITIZED_O1262A = """000000 Test Pilot   ORD CRJ FO   O1262A 07/02/2026
Block: 9:42   Credit: 9:42   TAFB: 32:38
________________________________________________________________________________
Thursday 07-02-2026    Report: 15:14    Release: 00:02/03
    Flight  Tail    Org  Dest Dep    Arr    Pax Block  Credit D/PU Dhd Turn 
 1. 5021    N918SW  ORD  SUX  16:19  18:10  48  1:51   1:51            0:29 
 2. 5021    N918SW  SUX  DEN  18:39  20:21  43  2:42   2:42            0:35 
 3. 5059    N961SW  DEN  EAR  20:56  23:47  44  1:51   1:51                 
                                     Day Total: 6:24   6:24   Duty: 8:48   
Hotel: Crowne Plaza Kearney   Layover: 12:40
________________________________________________________________________________
Friday 07-03-2026    Report: 12:42    Release: 23:52
    Flight  Tail    Org  Dest Dep    Arr    Pax Block  Credit D/PU Dhd Turn 
 4. CXL             EAR  EAR  12:42  12:42  0   0:00   0:00        N        
Hotel: TBD   Layover: 7:08
 5. 6075    N218PS  EAR  ORD  19:50  23:08  34  3:18   3:18            0:44 
 6. FDP             ORD  ORD  23:52  23:52  0   0:00   0:00        N        
                                     Day Total: 3:18   3:18   Duty: 11:10  
________________________________________________________________________________
"""

SANITIZED_REF_DAY = """000000 Test Pilot   MSP CR7 FO   E3436D 06/14/2026
Block: 5:20   Credit: 5:39   TAFB: 7:41
________________________________________________________________________________
Sunday 06-14-2026    Report: 06:00    Release: 13:41
    Flight  Tail    Org  Dest Dep    Arr    Pax Block  Credit D/PU Dhd Turn 
10. REF             ATY  ATY  06:00  06:00  0   0:00   0:00        N   0:32 
11. *4298    N656CA  ATY  MSP  06:32  07:49  15  1:17   1:18            0:43 
                                     Day Total: 1:17   1:18   Duty: 7:41   
________________________________________________________________________________
"""


def test_placeholders_first_and_last_line_do_not_become_flights(tmp_path) -> None:
    txt = tmp_path / "000000_20260702_O1262A.txt"
    txt.write_text(SANITIZED_O1262A)
    pairing = parse_skedplus_txt(txt)
    day2 = pairing.duty_days[1]
    # Parser keeps every schedule line; placeholders do not count as planned legs.
    assert [leg.flight for leg in day2.legs] == ["CXL", "6075", "FDP"]
    assert day2.planned_leg_count == 1

    plan = build_import_plan(
        pairing, ImportMode.ACTUAL, role=CrewRole.SIC,
        operator=Operator.SKW, airport_index=AIRPORTS,
    )
    assert [f.flight_number for f in plan.flights] == ["5021", "5021", "5059", "6075"]

    dp2 = plan.duty_periods[1]
    # CXL at EAR carries the report; FDP at ORD carries the release. Both Central.
    assert dp2.report_at == datetime(2026, 7, 3, 17, 42, tzinfo=UTC)
    assert dp2.release_at == datetime(2026, 7, 4, 4, 52, tzinfo=UTC)
    assert not [w for w in plan.warnings if "Duty" in w or "naive" in w]


def test_ref_placeholder_first_line_keeps_report(tmp_path) -> None:
    txt = tmp_path / "000000_20260614_E3436D.txt"
    txt.write_text(SANITIZED_REF_DAY)
    pairing = parse_skedplus_txt(txt)
    plan = build_import_plan(
        pairing, ImportMode.ACTUAL, role=CrewRole.SIC,
        operator=Operator.SKW, airport_index=AIRPORTS,
    )
    assert [f.flight_number for f in plan.flights] == ["4298"]
    dp = plan.duty_periods[0]
    assert dp.report_at == datetime(2026, 6, 14, 11, 0, tzinfo=UTC)
    assert dp.release_at == datetime(2026, 6, 14, 18, 41, tzinfo=UTC)


# --- aircraft code CRJ -> CR2 ----------------------------------------------

def test_normalize_aircraft_code() -> None:
    assert normalize_aircraft_code("CRJ") == "CR2"
    assert normalize_aircraft_code(" crj ") == "CR2"
    for code in ("CR5", "CR7", "CR9", "E175"):
        assert normalize_aircraft_code(code) == code
    assert normalize_aircraft_code(None) is None


def test_crj_csv_maps_to_cr2_and_no_header_fallback(tmp_path) -> None:
    txt = tmp_path / "000000_20260702_O1262A.txt"
    txt.write_text(SANITIZED_O1262A)
    csv = tmp_path / "000000_20260702_O1262A.csv"
    csv.write_text(
        "Flight,Date,A/C Type,Tail,Origin,Dest,Depart,Arrive,Block,Credit,"
        "Captain,First Officer,Flight Attendant\n"
        "5021,07/02/2026,CRJ,N918SW,ORD,SUX,16:19,18:10,1.85,1.85,,,\n"
        "5021,07/02/2026,CR5,N918SW,SUX,DEN,18:39,20:21,2.7,2.7,,,\n"
    )
    pairing, _ = load_pairing_export(PairingFileSet("O1262A", txt_path=txt, csv_path=csv))
    plan = build_import_plan(
        pairing, ImportMode.ACTUAL, role=CrewRole.SIC,
        operator=Operator.SKW, airport_index=AIRPORTS,
    )
    codes = {f.flight_number + f.origin: f.aircraft_code for f in plan.flights}
    assert codes["5021ORD"] == "CR2"   # CSV CRJ
    assert codes["5021SUX"] == "CR5"   # CSV subtype untouched
    assert codes["5059DEN"] is None    # no CSV row -> link left blank (R5)
    assert codes["6075EAR"] is None
    blank_warns = [w for w in plan.warnings if "no aircraft type on this flight line" in w]
    assert len(blank_warns) == 2       # 5059 and 6075
    # Header "ORD CRJ FO" is not trip data: base = first line origin (R3/R4).
    assert plan.trips[0].base == "ORD"
    assert plan.trips[0].pairing_id == "O1262"


# --- base from first schedule line (R3/R4) ----------------------------------

def test_base_is_first_line_origin_not_header(tmp_path) -> None:
    # Header says MSP; the first line departs ATY.
    txt = tmp_path / "000000_20260614_E3436D.txt"
    txt.write_text(SANITIZED_REF_DAY)
    plan = build_import_plan(parse_skedplus_txt(txt), ImportMode.PLANNED, airport_index=AIRPORTS)
    assert plan.trips[0].base == "ATY"
    assert plan.trips[0].pairing_id == "E3436"
    assert plan.trips[0].trip_key == "E3436|2026-06-14"
    assert plan.duty_periods[0].duty_period_key == "E3436|2026-06-14|2026-06-14"


# --- flown credit (R7) and credit check (R8) -------------------------------

SANITIZED_O1251_DAYS = """000000 Test Pilot   ORD CRJ FO   O1251 07/22/2026
Block: 7:15   Credit: 8:58   TAFB: 30:35
________________________________________________________________________________
Thursday 07-23-2026    Report: 17:40    Release: 23:25
    Flight  Tail    Org  Dest Dep    Arr    Pax Block  Credit D/PU Dhd Turn 
 4. 6013    N957SW  GRB  ORD  18:14  20:47  32  2:33   2:33            0:58 
 5. 5124    N975SW  ORD  EAU  21:45  23:10  46  1:25   1:25                 
                                     Day Total: 3:58   4:12   Duty: 5:45   
Hotel: The Lismore Hotel Eau Cla   Layover: 14:25
________________________________________________________________________________
Friday 07-24-2026    Report: 13:50    Release: 19:58
    Flight  Tail    Org  Dest Dep    Arr    Pax Block  Credit D/PU Dhd Turn 
 6. 5122    N983SW  EAU  ORD  14:36  16:05  35  1:29   1:29            0:50 
 7. 6060    N983SW  ORD  LNS  16:55  19:43  17  1:48   2:00                 
                                     Day Total: 3:17   4:00   Duty: 5:08   
________________________________________________________________________________
"""


def test_actual_credit_from_day_total_and_header(tmp_path) -> None:
    txt = tmp_path / "000000_20260722_O1251.txt"
    txt.write_text(SANITIZED_O1251_DAYS)
    pairing = parse_skedplus_txt(txt)
    plan = build_import_plan(
        pairing, ImportMode.ACTUAL, role=CrewRole.SIC,
        operator=Operator.SKW, airport_index=AIRPORTS,
    )
    assert plan.trips[0].actual_credit == 9.0          # header Credit: 8:58
    assert [dp.actual_credit for dp in plan.duty_periods] == [4.2, 4.0]
    # Day 1: legs 3:58 < 4:12 minimum, Day Total 4:12 -> no warning.
    # Day 2: legs 3:29, expected 4:12, Day Total 4:00 -> warning, value still imported.
    credit_warns = [w for w in plan.warnings if "credit check" in w]
    assert len(credit_warns) == 1
    assert credit_warns[0].startswith("O1251|2026-07-22|2026-07-24: credit check O1251 2026-07-24")
    assert "Day Total credit 4:00" in credit_warns[0]
    assert "leg credit sum 3:29" in credit_warns[0]

    planned = build_import_plan(pairing, ImportMode.PLANNED, airport_index=AIRPORTS)
    assert not [w for w in planned.warnings if "credit check" in w]


def test_day_credit_check_uses_exact_minutes() -> None:
    legs = [
        Leg(1, "1", "N1", "ORD", "GRB", time(8), time(9), 1, 1.7, 1.7, credit_minutes=100),
        Leg(2, "2", "N1", "GRB", "ORD", time(10), time(12), 1, 2.6, 2.6, credit_minutes=155),
    ]
    duty = DutyDay(date(2026, 7, 1), time(7), time(13), legs=legs)
    duty.day_credit_minutes = 255          # 4:15 == leg sum -> OK
    assert day_credit_check(duty) is None
    duty.day_credit_minutes = 254          # one minute short
    assert "4:14" in day_credit_check(duty) and "leg credit sum 4:15" in day_credit_check(duty)


# --- cancelled duty periods (R9) -------------------------------------------

def test_actual_duty_without_flight_lines_is_cancelled(tmp_path) -> None:
    txt = tmp_path / "000000_20260702_O1262A.txt"
    txt.write_text(SANITIZED_O1262A.replace(
        " 5. 6075    N218PS  EAR  ORD  19:50  23:08  34  3:18   3:18            0:44 \n", ""
    ))
    pairing = parse_skedplus_txt(txt)
    actual = build_import_plan(
        pairing, ImportMode.ACTUAL, role=CrewRole.SIC,
        operator=Operator.SKW, airport_index=AIRPORTS,
    )
    assert [dp.status for dp in actual.duty_periods] == ["Actual", "Cancelled"]
    planned = build_import_plan(pairing, ImportMode.PLANNED, airport_index=AIRPORTS)
    assert [dp.status for dp in planned.duty_periods] == ["Planned", "Planned"]


def test_future_duty_on_actual_import_stays_planned() -> None:
    future = date.today().replace(year=date.today().year + 1)
    pairing = PairingExport(
        employee_id="1", employee_name="Test Pilot", base="ORD",
        equipment_family="CRJ", role="FO", pairing_id="O1999",
        start_date=future, block_hours=0.0, credit_hours=4.2, tafb_hours=0.0,
        duty_days=[DutyDay(future, time(8), time(14), day_credit_hours=4.2)],
    )
    plan = build_import_plan(pairing, ImportMode.ACTUAL)
    assert plan.duty_periods[0].status == "Planned"
    assert plan.duty_periods[0].actual_credit is None
    assert not [w for w in plan.warnings if "credit check" in w]
