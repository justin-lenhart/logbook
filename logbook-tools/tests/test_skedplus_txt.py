from logbook_import.leg_classifier import is_duty_event
from logbook_import.parsers.skedplus_txt import parse_skedplus_txt


def test_e3058e_pairing_structure(e3058e_txt) -> None:
    pairing = parse_skedplus_txt(e3058e_txt)
    assert pairing.pairing_id == "E3058E"
    assert pairing.employee_id == "121807"
    assert pairing.base == "MSP"
    assert pairing.equipment_family == "CRJ"
    assert pairing.block_hours == 13.8  # 13:50
    assert pairing.credit_hours == 19.3  # 19:17
    assert len(pairing.duty_days) == 4

    total_legs = sum(len(d.legs) for d in pairing.duty_days)
    assert total_legs == 14

    duty_events = [
        leg for duty in pairing.duty_days for leg in duty.legs if is_duty_event(leg)
    ]
    assert len(duty_events) == 4  # 3 RDY + 1 NMD


def test_e7748_pairing_structure(e7748_txt) -> None:
    pairing = parse_skedplus_txt(e7748_txt)
    assert pairing.pairing_id == "E7748"
    assert len(pairing.duty_days) == 1
    assert len(pairing.duty_days[0].legs) == 3
    assert pairing.duty_days[0].legs[2].flight == "1303"
    assert pairing.duty_days[0].legs[2].deadhead_indicator == "F"
