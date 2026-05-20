from __future__ import annotations

import re

from logbook_import.models import Leg

# Non-flight schedule lines that never become Flight rows.
DUTY_EVENT_CODES = frozenset(
    {
        "RDY",
        "NMD",
        "GRD",
        "STB",
        "SIM",
        "TRN",
        "VAC",
        "SICK",
    }
)

NUMERIC_FLIGHT_RE = re.compile(r"^\*?\d+$")


def normalize_flight_code(flight: str) -> str:
    return flight.strip().lstrip("*").upper()


def is_duty_event(leg: Leg) -> bool:
    code = normalize_flight_code(leg.flight)
    return code in DUTY_EVENT_CODES


def is_deadhead(leg: Leg) -> bool:
    if leg.deadhead_indicator.upper() == "F":
        return True
    if leg.deadhead_indicator.upper() == "N":
        return False
    # Numeric flight without tail on a passenger DH pattern (e.g. 1303 DH leg)
    if NUMERIC_FLIGHT_RE.match(leg.flight.strip()) and not leg.tail:
        return leg.block_hours == 0.0 and leg.pax == 0
    return False


def is_loggable_flight(leg: Leg) -> bool:
    """Legs that may become Flight rows on actual import (includes deadheads)."""
    return not is_duty_event(leg)


def counts_toward_planned_legs(leg: Leg) -> bool:
    """All schedule lines from txt export, including RDY/NMD/deadhead."""
    return True
