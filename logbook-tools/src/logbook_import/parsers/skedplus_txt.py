from __future__ import annotations

import re
from pathlib import Path

from logbook_import.models import CrewAssignment, DutyDay, Leg, PairingExport
from logbook_import.time_utils import parse_date_mdy, parse_duration_hmm, parse_time_hhmm

HEADER_RE = re.compile(
    r"^(\d+)\s+(.+?)\s{2,}(\w{3})\s+(\w+)\s+(\w+)\s+([A-Z0-9]+)\s+(\d{2}/\d{2}/\d{4})$"
)
SUMMARY_RE = re.compile(
    r"^Block:\s+(\S+)\s+Credit:\s+(\S+)\s+TAFB:\s+(\S+)",
    re.IGNORECASE,
)
DUTY_HEADER_RE = re.compile(
    r"^\w+\s+(\d{2}-\d{2}-\d{4})\s+Report:\s+(\d{1,2}:\d{2})\s+Release:\s+(\d{1,2}:\d{2})",
    re.IGNORECASE,
)
DAY_TOTAL_RE = re.compile(
    r"Day Total:\s+(\S+)\s+(\S+)\s+Duty:\s+(\S+)",
    re.IGNORECASE,
)
HOTEL_RE = re.compile(r"^Hotel:\s*(.+?)\s+Layover:\s*(\S+)", re.IGNORECASE)
LEG_LINE_RE = re.compile(r"^\s*(\d+)\.\s+(.+?)\s*$")
# Matches a bare "Weekday MM-DD-YYYY" continuation line inside an SDuty FDP
# (no Report:/Release: means this is NOT a new duty period — it's the morning
# segment of the same FDP after the split-duty rest break).
CONTINUATION_DATE_RE = re.compile(r"^\w+\s+(\d{2}-\d{2}-\d{4})\s*$")
CREW_LINE_RE = re.compile(
    r"^\s*(\d+)\.\s+CA:\s*(.*?)\s+FO:\s*(.*?)\s+FA:\s*(.*?)\s*$"
)
AIRPORT_CODE_RE = re.compile(r"^[A-Z]{3}$")


def _is_airport_code(token: str) -> bool:
    return bool(AIRPORT_CODE_RE.match(token))


def _parse_leg_body(leg_number: int, body: str) -> Leg:
    tokens = body.split()
    if len(tokens) < 8:
        raise ValueError(f"Leg {leg_number}: not enough tokens in {body!r}")

    flight = tokens[0]
    idx = 1
    tail: str | None = None
    if idx < len(tokens) and not _is_airport_code(tokens[idx]):
        tail = tokens[idx] or None
        idx += 1

    origin = tokens[idx]
    destination = tokens[idx + 1]
    departure = parse_time_hhmm(tokens[idx + 2])
    arrival = parse_time_hhmm(tokens[idx + 3])
    pax = int(tokens[idx + 4])
    block = parse_duration_hmm(tokens[idx + 5])
    credit = parse_duration_hmm(tokens[idx + 6])

    deadhead_indicator = ""
    for token in tokens[idx + 7 :]:
        if token in {"F", "N"}:
            deadhead_indicator = token
            break

    return Leg(
        leg_number=leg_number,
        flight=flight,
        tail=tail,
        origin=origin,
        destination=destination,
        departure=departure,
        arrival=arrival,
        pax=pax,
        block_hours=block,
        credit_hours=credit,
        deadhead_indicator=deadhead_indicator,
    )


def _parse_crew_line(line: str) -> tuple[int, CrewAssignment] | None:
    match = CREW_LINE_RE.match(line)
    if not match:
        return None
    leg_number = int(match.group(1))

    def clean(value: str) -> str | None:
        value = value.strip()
        return value or None

    return leg_number, CrewAssignment(
        captain=clean(match.group(2)),
        first_officer=clean(match.group(3)),
        flight_attendant=clean(match.group(4)),
    )


def parse_skedplus_txt(path: Path | str) -> PairingExport:
    path = Path(path)
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()

    header: PairingExport | None = None
    current_duty: DutyDay | None = None
    continuation_date: date | None = None
    in_crew_section = False
    crew_by_leg: dict[int, CrewAssignment] = {}

    for raw_line in lines:
        line = raw_line.rstrip()
        if not line.strip():
            continue

        if line.startswith("____"):
            continue

        if header is None:
            match = HEADER_RE.match(line)
            if not match:
                raise ValueError(f"Missing pairing header in {path}")
            header = PairingExport(
                employee_id=match.group(1),
                employee_name=match.group(2).strip(),
                base=match.group(3),
                equipment_family=match.group(4),
                role=match.group(5),
                pairing_id=match.group(6),
                start_date=parse_date_mdy(match.group(7)),
                block_hours=0.0,
                credit_hours=0.0,
                tafb_hours=0.0,
                source_txt=path,
            )
            continue

        if header.block_hours == 0.0:
            summary = SUMMARY_RE.match(line)
            if summary:
                header.block_hours = parse_duration_hmm(summary.group(1))
                header.credit_hours = parse_duration_hmm(summary.group(2))
                header.tafb_hours = parse_duration_hmm(summary.group(3))
                continue

        if line.strip() == "Crew Members":
            in_crew_section = True
            continue

        if in_crew_section:
            parsed_crew = _parse_crew_line(line)
            if parsed_crew:
                crew_by_leg[parsed_crew[0]] = parsed_crew[1]
            continue

        duty_match = DUTY_HEADER_RE.match(line)
        if duty_match:
            continuation_date = None  # reset for every new full duty period
            current_duty = DutyDay(
                duty_date=parse_date_mdy(duty_match.group(1)),
                report_time=parse_time_hhmm(duty_match.group(2)),
                release_time=parse_time_hhmm(duty_match.group(3)),
            )
            header.duty_days.append(current_duty)
            continue

        if current_duty is not None:
            day_total = DAY_TOTAL_RE.search(line)
            if day_total:
                current_duty.day_block_hours = parse_duration_hmm(day_total.group(1))
                current_duty.day_credit_hours = parse_duration_hmm(day_total.group(2))
                current_duty.duty_hours = parse_duration_hmm(day_total.group(3))
                current_duty = None
                continuation_date = None
                continue

            hotel_match = HOTEL_RE.match(line)
            if hotel_match and header.duty_days:
                duty = header.duty_days[-1]
                duty.hotel = hotel_match.group(1).strip()
                duty.layover = hotel_match.group(2).strip()
                continue

            # SDuty continuation: bare "Weekday MM-DD-YYYY" with no Report/Release.
            # The morning segment belongs to the same FDP but on the next calendar day.
            cont_match = CONTINUATION_DATE_RE.match(line)
            if cont_match:
                continuation_date = parse_date_mdy(cont_match.group(1))
                current_duty.sduty = True
                continue

            leg_match = LEG_LINE_RE.match(line)
            if leg_match and "Flight" not in line:
                leg = _parse_leg_body(int(leg_match.group(1)), leg_match.group(2))
                leg.duty_date = continuation_date or header.duty_days[-1].duty_date
                header.duty_days[-1].legs.append(leg)
                continue

    if header is None:
        raise ValueError(f"Could not parse pairing header from {path}")

    for duty in header.duty_days:
        for leg in duty.legs:
            leg.crew = crew_by_leg.get(leg.leg_number)

    return header
