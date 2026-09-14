from datetime import time

from logbook_import.leg_classifier import (
    is_deadhead,
    is_duty_event,
    is_loggable_flight,
    is_placeholder,
)
from logbook_import.models import Leg


def _leg(flight: str, tail: str | None = None, dhd: str = "", block: float = 1.0, pax: int = 1) -> Leg:
    return Leg(
        leg_number=1,
        flight=flight,
        tail=tail,
        origin="MSP",
        destination="INL",
        departure=time(12, 0),
        arrival=time(13, 0),
        pax=pax,
        block_hours=block,
        credit_hours=block,
        deadhead_indicator=dhd,
    )


def test_rdy_is_duty_event_not_loggable() -> None:
    leg = _leg("RDY", tail=None, block=0.0, pax=0)
    assert is_duty_event(leg)
    assert not is_loggable_flight(leg)


def test_deadhead_flag() -> None:
    leg = _leg("1303", tail=None, dhd="F", block=0.0, pax=0)
    assert is_deadhead(leg)
    assert is_loggable_flight(leg)


def _station_leg(flight: str, station: str, block: float = 0.0, dhd: str = "N", tail=None) -> Leg:
    return Leg(
        leg_number=1,
        flight=flight,
        tail=tail,
        origin=station,
        destination=station,
        departure=time(12, 42),
        arrival=time(12, 42),
        pax=0,
        block_hours=block,
        credit_hours=0.0,
        deadhead_indicator=dhd,
    )


def test_cxl_fdp_ref_are_not_loggable() -> None:
    for code, station in (("CXL", "EAR"), ("FDP", "ORD"), ("REF", "ATY")):
        leg = _station_leg(code, station)
        assert is_duty_event(leg), code
        assert not is_loggable_flight(leg), code


def test_unknown_non_numeric_zero_block_same_station_is_placeholder() -> None:
    for code in ("LCO", "SHO", "RSV", "XYZ"):
        leg = _station_leg(code, "DFW")
        assert is_placeholder(leg), code
        assert not is_loggable_flight(leg), code


def test_non_numeric_with_block_or_different_stations_stays_loggable() -> None:
    # Only the combination (non-numeric, 0:00, origin == destination) is excluded.
    assert is_loggable_flight(_station_leg("ABC", "ORD", block=1.0))
    moving = _leg("ABC", block=0.0, pax=0)  # MSP -> INL
    assert not is_placeholder(moving)
    assert is_loggable_flight(moving)


def test_numeric_same_station_air_return_is_loggable() -> None:
    # O1314: flight 5108 ORD-ORD 0:38 was a real air return.
    leg = _station_leg("5108", "ORD", block=0.6, dhd="", tail="N916EV")
    assert not is_placeholder(leg)
    assert is_loggable_flight(leg)
    # Even a numeric 0:00 same-station line is never treated as a placeholder.
    assert is_loggable_flight(_station_leg("*5108", "ORD", block=0.0, dhd=""))


def test_flown_leg_is_loggable() -> None:
    leg = _leg("4266", tail="N713EV")
    assert is_loggable_flight(leg)
    assert not is_deadhead(leg)
