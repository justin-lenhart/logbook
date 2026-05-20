from __future__ import annotations

from pathlib import Path

from logbook_import.config import PairingFileSet
from logbook_import.models import PairingExport
from logbook_import.parsers.skedplus_csv import CsvLegKey, index_csv_legs, parse_skedplus_csv
from logbook_import.parsers.skedplus_txt import parse_skedplus_txt


def merge_csv_into_pairing(pairing: PairingExport, csv_legs: list) -> list[str]:
    """Enrich txt legs with csv aircraft type and optional times. Returns warnings."""
    warnings: list[str] = []
    csv_index = index_csv_legs(csv_legs)

    for duty in pairing.duty_days:
        for leg in duty.legs:
            key = CsvLegKey.from_leg(leg)
            csv_leg = csv_index.get(key)
            if csv_leg is None:
                continue
            if csv_leg.aircraft_type:
                leg.aircraft_type = csv_leg.aircraft_type
            if csv_leg.tail and not leg.tail:
                leg.tail = csv_leg.tail
            if csv_leg.crew and not leg.crew:
                leg.crew = csv_leg.crew

    txt_keys = {
        CsvLegKey.from_leg(leg)
        for duty in pairing.duty_days
        for leg in duty.legs
    }
    for key, csv_leg in csv_index.items():
        if key not in txt_keys:
            warnings.append(
                "CSV row not matched in txt export: "
                f"{key.flight_number} {key.leg_date} {key.origin}-{key.destination} "
                f"dep {key.departure_hhmm}"
            )
    return warnings


def load_pairing_export(file_set: PairingFileSet) -> tuple[PairingExport, list[str]]:
    assert file_set.txt_path is not None
    pairing = parse_skedplus_txt(file_set.txt_path)
    pairing.source_txt = file_set.txt_path
    warnings: list[str] = []

    if file_set.csv_path:
        csv_legs = parse_skedplus_csv(file_set.csv_path)
        pairing.source_csv = file_set.csv_path
        warnings.extend(merge_csv_into_pairing(pairing, csv_legs))

    if pairing.pairing_id.upper() != file_set.pairing_id.upper():
        warnings.append(
            f"Filename pairing {file_set.pairing_id} does not match export "
            f"{pairing.pairing_id}"
        )

    return pairing, warnings
