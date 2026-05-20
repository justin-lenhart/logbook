from datetime import time

from logbook_import.leg_classifier import is_deadhead, is_duty_event, is_loggable_flight
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


def test_flown_leg_is_loggable() -> None:
    leg = _leg("4266", tail="N713EV")
    assert is_loggable_flight(leg)
    assert not is_deadhead(leg)
