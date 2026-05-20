from logbook_import.parsers.skedplus_csv import parse_skedplus_csv


def test_e3058e_csv_row_count(e3058e_csv) -> None:
    legs = parse_skedplus_csv(e3058e_csv)
    assert len(legs) == 10
    assert all(leg.aircraft_type == "CR5" for leg in legs)


def test_e7748_csv_row_count(e7748_csv) -> None:
    legs = parse_skedplus_csv(e7748_csv)
    assert len(legs) == 2
