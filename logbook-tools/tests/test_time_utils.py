from logbook_import.time_utils import parse_duration_hmm


def test_parse_duration_hmm() -> None:
    assert parse_duration_hmm("1:16") == 1.3
    assert parse_duration_hmm("0:00") == 0.0
    assert parse_duration_hmm("10:10") == 10.2
