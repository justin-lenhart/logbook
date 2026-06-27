from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from enum import Enum
from pathlib import Path


@dataclass
class CrewAssignment:
    captain: str | None = None
    first_officer: str | None = None
    flight_attendant: str | None = None


@dataclass
class Leg:
    leg_number: int
    flight: str
    tail: str | None
    origin: str
    destination: str
    departure: time
    arrival: time
    pax: int
    block_hours: float
    credit_hours: float
    deadhead_indicator: str = ""
    duty_date: date | None = None
    aircraft_type: str | None = None
    crew: CrewAssignment | None = None

    @property
    def flight_normalized(self) -> str:
        return self.flight.strip().lstrip("*").upper()


@dataclass
class DutyDay:
    duty_date: date
    report_time: time
    release_time: time
    legs: list[Leg] = field(default_factory=list)
    day_block_hours: float = 0.0
    day_credit_hours: float = 0.0
    duty_hours: float = 0.0
    hotel: str | None = None
    layover: str | None = None
    sduty: bool = False

    @property
    def planned_leg_count(self) -> int:
        return len(self.legs)


@dataclass
class PairingExport:
    employee_id: str
    employee_name: str
    base: str
    equipment_family: str
    role: str
    pairing_id: str
    start_date: date
    block_hours: float
    credit_hours: float
    tafb_hours: float
    duty_days: list[DutyDay] = field(default_factory=list)
    source_txt: Path | None = None
    source_csv: Path | None = None

    @property
    def end_date(self) -> date:
        return self.duty_days[-1].duty_date if self.duty_days else self.start_date


class ImportMode(str, Enum):
    PLANNED = "planned"
    ACTUAL = "actual"


class CrewRole(str, Enum):
    PIC = "pic"
    SIC = "sic"


class Operator(str, Enum):
    SKW = "skw"


@dataclass
class PlannedTripRecord:
    trip_key: str
    pairing_id: str
    start_date: date
    end_date: date
    base: str
    equipment_family: str
    planned_block: float
    planned_credit: float
    planned_duty_periods: int
    planned_legs: int
    tafb_hours: float = 0.0
    status: str = "Planned"


@dataclass
class PlannedDutyPeriodRecord:
    duty_period_key: str
    trip_key: str
    duty_date: date
    report_at: datetime
    release_at: datetime
    planned_block: float
    planned_credit: float
    planned_legs: int
    status: str = "Planned"


@dataclass
class ImportBatchRecord:
    batch_name: str
    import_type: str
    source_filename: str
    source_folder: str
    import_status: str = "Imported"


@dataclass
class PlannedFlightRecord:
    import_flight_key: str
    trip_key: str
    duty_period_key: str
    duty_date: date
    flight_number: str
    tail_number: str | None
    origin: str
    destination: str
    out_time: datetime
    in_time: datetime
    block_hours: float
    credit_hours: float
    pic_hours: float
    sic_hours: float
    flight_position: str
    deadhead: bool
    aircraft_code: str | None
    operation: str | None
    airline: str | None
    passengers: int = 0
    special_categories: list[str] = field(default_factory=list)


@dataclass
class ImportPlan:
    mode: ImportMode
    pairing_id: str
    source_txt: str
    source_csv: str | None
    trips: list[PlannedTripRecord]
    duty_periods: list[PlannedDutyPeriodRecord]
    flights: list[PlannedFlightRecord]
    import_batch: ImportBatchRecord
    warnings: list[str] = field(default_factory=list)
