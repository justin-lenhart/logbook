from __future__ import annotations

import re
from datetime import date, datetime, time

DURATION_RE = re.compile(r"^(\d+):(\d{2})$")
DATE_MDY_RE = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")
DATE_MDY_DASH_RE = re.compile(r"^(\d{2})-(\d{2})-(\d{4})$")


def parse_duration_hmm(value: str) -> float:
    """Convert H:MM or M:SS-style duration to decimal hours (1 decimal)."""
    value = value.strip()
    if not value or value in {"0:00", "00:00"}:
        return 0.0
    match = DURATION_RE.match(value)
    if not match:
        raise ValueError(f"Invalid duration: {value!r}")
    hours = int(match.group(1))
    minutes = int(match.group(2))
    return round(hours + minutes / 60.0, 1)


def parse_date_mdy(value: str) -> date:
    value = value.strip()
    for pattern in (DATE_MDY_RE, DATE_MDY_DASH_RE):
        match = pattern.match(value)
        if match:
            month, day, year = (int(match.group(i)) for i in range(1, 4))
            return date(year, month, day)
    raise ValueError(f"Invalid date: {value!r}")


def parse_time_hhmm(value: str) -> time:
    value = value.strip()
    if not value:
        raise ValueError("Empty time")
    parts = value.split(":")
    if len(parts) != 2:
        raise ValueError(f"Invalid time: {value!r}")
    hour, minute = int(parts[0]), int(parts[1])
    return time(hour, minute)


def departure_hhmm_key(departure: time) -> str:
    """Compact HHMM for Import Flight Key (no colon)."""
    return f"{departure.hour:02d}{departure.minute:02d}"


def combine_date_time(d: date, t: time) -> datetime:
    return datetime(d.year, d.month, d.day, t.hour, t.minute)


def iso_date(d: date) -> str:
    return d.isoformat()
