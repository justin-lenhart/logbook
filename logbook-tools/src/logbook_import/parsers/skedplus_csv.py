from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from logbook_import.keys import normalize_flight_number
from logbook_import.models import CrewAssignment, Leg
from logbook_import.time_utils import parse_date_mdy, parse_time_hhmm


@dataclass(frozen=True)
class CsvLegKey:
    flight_number: str
    leg_date: str
    origin: str
    destination: str
    departure_hhmm: str

    @classmethod
    def from_leg(cls, leg: Leg) -> CsvLegKey:
        assert leg.duty_date is not None
        return cls(
            flight_number=normalize_flight_number(leg.flight),
            leg_date=leg.duty_date.isoformat(),
            origin=leg.origin.upper(),
            destination=leg.destination.upper(),
            departure_hhmm=f"{leg.departure.hour:02d}{leg.departure.minute:02d}",
        )


def _csv_row_key(row: dict[str, str]) -> CsvLegKey:
    dep = parse_time_hhmm(row["Depart"])
    return CsvLegKey(
        flight_number=normalize_flight_number(row["Flight"]),
        leg_date=parse_date_mdy(row["Date"]).isoformat(),
        origin=row["Origin"].strip().upper(),
        destination=row["Dest"].strip().upper(),
        departure_hhmm=f"{dep.hour:02d}{dep.minute:02d}",
    )


def parse_skedplus_csv(path: Path | str) -> list[Leg]:
    path = Path(path)
    legs: list[Leg] = []

    with path.open(encoding="utf-8", errors="replace", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            duty_date = parse_date_mdy(row["Date"])
            departure = parse_time_hhmm(row["Depart"])
            arrival = parse_time_hhmm(row["Arrive"])
            legs.append(
                Leg(
                    leg_number=0,
                    flight=row["Flight"].strip(),
                    tail=row.get("Tail") or None,
                    origin=row["Origin"].strip(),
                    destination=row["Dest"].strip(),
                    departure=departure,
                    arrival=arrival,
                    pax=0,
                    block_hours=round(float(row["Block"]), 1),
                    credit_hours=round(float(row["Credit"]), 1),
                    duty_date=duty_date,
                    aircraft_type=(row.get("A/C Type") or row.get("AC Type") or "").strip() or None,
                    crew=CrewAssignment(
                        captain=(row.get("Captain") or "").strip() or None,
                        first_officer=(row.get("First Officer") or "").strip() or None,
                        flight_attendant=(row.get("Flight Attendant") or "").strip() or None,
                    ),
                )
            )

    return legs


def index_csv_legs(legs: list[Leg]) -> dict[CsvLegKey, Leg]:
    return {CsvLegKey.from_leg(leg): leg for leg in legs if leg.duty_date}
