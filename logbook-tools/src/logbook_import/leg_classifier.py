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
        # Zero-time placeholders SkedPlus prints at a station (origin == dest):
        "CXL",  # cancelled leg
        "FDP",  # FDP end marker
        "REF",  # reference / report marker
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


def is_placeholder(leg: Leg) -> bool:
    """Non-numeric code with 0:00 block that starts and ends at the same station
    (CXL, FDP, REF, LCO, SHO, RSV...). Numeric flights are never placeholders —
    e.g. flight 5108 ORD-ORD 0:38 is a real air return."""
    if NUMERIC_FLIGHT_RE.match(leg.flight.strip()):
        return False
    return (
        leg.block_hours == 0.0
        and leg.origin.strip().upper() == leg.destination.strip().upper()
    )


def is_loggable_flight(leg: Leg) -> bool:
    """Legs that may become Flight rows on actual import (includes deadheads)."""
    return not is_duty_event(leg) and not is_placeholder(leg)


# Placeholder codes that never count as planned legs, whatever their times.
PLACEHOLDER_CODES = frozenset({"CXL", "FDP", "REF", "RSV", "LCO", "SHO"})


def counts_toward_planned_legs(leg: Leg) -> bool:
    """Schedule lines counted in Planned_Legs (flights and deadheads).

    Excluded: PLACEHOLDER_CODES, and every ``is_placeholder`` line. The
    ``is_placeholder`` rule also matches RDY/NMD lines (0:00 block, same
    station), so those are not counted either. Used by
    ``DutyDay.planned_leg_count``.
    """
    if normalize_flight_code(leg.flight) in PLACEHOLDER_CODES:
        return False
    return not is_placeholder(leg)
