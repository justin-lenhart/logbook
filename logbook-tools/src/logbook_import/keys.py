from __future__ import annotations

from datetime import date, time

from logbook_import.time_utils import departure_hhmm_key, iso_date


def normalize_pairing_id(pairing_id: str) -> str:
    """Collapse a SkyWest pairing revision suffix to its base pairing number.

    SkyWest pairing numbers are a 1-char prefix + 4-char body (e.g. ``E3405``,
    ``O1414``, ``E3A08`` — always 5 chars).  When a trip is revised or reflown
    the scheduling system appends a revision letter (``E3405A``, ``E3436D``,
    ``O1414J``, ``E3058E``).  A planned export and the later actual export of the
    same trip can therefore differ only by this trailing letter, which would
    otherwise produce two distinct keys and a duplicate Trip on import.

    Strip a single trailing ``A-Z`` only when the id is longer than the 5-char
    base, so genuine 5-char bodies (including any that end in a letter) are left
    intact.  The full, un-normalized pairing id is still stored in the Trip's
    display field and the import batch name.

    NOTE: this heuristic is specific to the SkyWest pairing format; revisit it
    when generalizing the importer for other operators.
    """
    pid = pairing_id.strip().upper()
    if len(pid) > 5 and pid[-1].isalpha():
        return pid[:-1]
    return pid


def trip_key(pairing_id: str, start_date: date) -> str:
    return f"{normalize_pairing_id(pairing_id)}|{iso_date(start_date)}"


def duty_period_key(pairing_id: str, trip_start_date: date, duty_date: date) -> str:
    return f"{trip_key(pairing_id, trip_start_date)}|{iso_date(duty_date)}"


def import_flight_key(
    pairing_id: str,
    duty_date: date,
    flight_number: str,
    origin: str,
    destination: str,
    departure: time,
) -> str:
    """Stable flight idempotency key matching Airtable Import Flight Key."""
    flight_number = normalize_flight_number(flight_number)
    return (
        f"{normalize_pairing_id(pairing_id)}|{iso_date(duty_date)}|{flight_number}|"
        f"{origin.upper()}|{destination.upper()}|{departure_hhmm_key(departure)}"
    )


def normalize_flight_number(flight_number: str) -> str:
    return flight_number.strip().lstrip("*").upper()
