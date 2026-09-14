from datetime import date, datetime, time

from logbook_import.time_utils import combine_report_release, parse_duration_hmm


def test_parse_duration_hmm() -> None:
    assert parse_duration_hmm("1:16") == 1.3
    assert parse_duration_hmm("0:00") == 0.0
    assert parse_duration_hmm("10:10") == 10.2


def test_combine_report_release_same_day() -> None:
    # Report 06:00 / Release 14:20 — an ordinary daytime duty period.
    report_at, release_at = combine_report_release(
        date(2026, 6, 3), time(6, 0), time(14, 20)
    )
    assert report_at == datetime(2026, 6, 3, 6, 0)
    assert release_at == datetime(2026, 6, 3, 14, 20)


def test_combine_report_release_rolls_past_midnight() -> None:
    # Report 15:14 / Release 00:02 (SkedPlus "00:02/03") — release is next day.
    report_at, release_at = combine_report_release(
        date(2026, 7, 2), time(15, 14), time(0, 2)
    )
    assert report_at == datetime(2026, 7, 2, 15, 14)
    assert release_at == datetime(2026, 7, 3, 0, 2)
    assert release_at > report_at
