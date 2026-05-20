from __future__ import annotations

from datetime import date, time

from logbook_import.time_utils import departure_hhmm_key, iso_date


def trip_key(pairing_id: str, start_date: date) -> str:
    return f"{pairing_id}|{iso_date(start_date)}"


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
        f"{pairing_id}|{iso_date(duty_date)}|{flight_number}|"
        f"{origin.upper()}|{destination.upper()}|{departure_hhmm_key(departure)}"
    )


def normalize_flight_number(flight_number: str) -> str:
    return flight_number.strip().lstrip("*").upper()
