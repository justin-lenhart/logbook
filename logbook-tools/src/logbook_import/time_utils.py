from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta

DURATION_RE = re.compile(r"^(\d+):(\d{2})$")
DATE_MDY_RE = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")
DATE_MDY_DASH_RE = re.compile(r"^(\d{2})-(\d{2})-(\d{4})$")


def parse_duration_hmm(value: str) -> float:
    """Convert H:MM or M:SS-style duration to decimal hours (1 decimal)."""
    minutes = parse_duration_minutes(value)
    return round(minutes // 60 + (minutes % 60) / 60.0, 1)


def parse_duration_minutes(value: str) -> int:
    """Convert an H:MM duration to whole minutes (exact, no rounding)."""
    value = value.strip()
    if not value or value in {"0:00", "00:00"}:
        return 0
    match = DURATION_RE.match(value)
    if not match:
        raise ValueError(f"Invalid duration: {value!r}")
    return int(match.group(1)) * 60 + int(match.group(2))


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


def combine_report_release(
    duty_date: date, report_time: time, release_time: time
) -> tuple[datetime, datetime]:
    """Report and release datetimes for one duty period.

    SkedPlus prints a single duty date with two clock times, so a release after
    local midnight (e.g. Report 15:14 / Release 00:02) would otherwise land on
    the same day and read earlier than report. A duty period is never longer
    than 24h, so when the release clock is at or before report, it belongs to
    the next calendar day — roll it forward one day.
    """
    report_at = combine_date_time(duty_date, report_time)
    release_at = combine_date_time(duty_date, release_time)
    if release_at <= report_at:
        release_at += timedelta(days=1)
    return report_at, release_at


def iso_date(d: date) -> str:
    return d.isoformat()
