from logbook_import.config import PairingFileSet
from logbook_import.parsers.merge import load_pairing_export


def test_merge_attaches_aircraft_type(e3058e_txt, e3058e_csv) -> None:
    pairing, _ = load_pairing_export(
        PairingFileSet("E3058E", txt_path=e3058e_txt, csv_path=e3058e_csv)
    )
    aircraft_types = {
        leg.aircraft_type
        for duty in pairing.duty_days
        for leg in duty.legs
        if leg.aircraft_type
    }
    assert aircraft_types == {"CR5"}
