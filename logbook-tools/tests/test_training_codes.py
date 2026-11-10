"""Training event codes parsed back out of the historical logbook remarks."""

from __future__ import annotations

import pytest

from logbook_import import training_codes as tc


def codes(remark: str | None) -> str:
    return tc.parse_codes(remark).joined


# -- exactly stored remarks --------------------------------------------------

@pytest.mark.parametrize("remark,expected", [
    ("2800", "2800"),
    ("28004300", "2800, 4300"),
    ("280043002300", "2800, 4300, 2300"),
    ("6300610219016100", "6300, 6102, 1901, 6100"),
])
def test_exact_remarks_split_cleanly(remark: str, expected: str) -> None:
    parsed = tc.parse_codes(remark)
    assert parsed.kind == tc.EXACT
    assert parsed.joined == expected
    assert parsed.dropped == 0


def test_sixteen_digit_trailing_zeros_are_real_code_endings() -> None:
    """2^53 covers every 16-digit integer, so these are not corrupt."""
    assert codes("2800460061002800") == "2800, 4600, 6100, 2800"
    assert codes("2902280029002800") == "2902, 2800, 2900, 2800"


# -- float-damaged remarks ---------------------------------------------------

def test_scientific_notation_keeps_the_recoverable_codes() -> None:
    """The brief's worked example: a 20-digit value, four solid codes."""
    parsed = tc.parse_codes("2.8002100230029001E+19")
    assert parsed.kind == tc.RECONSTRUCTED
    assert parsed.codes == ("2800", "2100", "2300", "2900")
    assert parsed.dropped == 1


def test_rounding_repairs_a_rounded_down_float() -> None:
    """``...0022999`` is really ``...0023000``: round, never truncate.

    Truncating would yield a bogus 2299; every such row in the real data
    rounds back to a code that occurs elsewhere in the logbook.
    """
    parsed = tc.parse_codes("2.8002801210022999E+23")
    assert parsed.codes == ("2800", "2801", "2100", "2300")
    assert "2299" not in parsed.codes


def test_rounding_repairs_a_rounded_up_float() -> None:
    assert tc.parse_codes("2.8002900350060999E+19").codes == (
        "2800", "2900", "3500", "6100")


def test_longer_values_drop_more_codes() -> None:
    """Only the first four codes are ever recoverable; the tail is padding."""
    for remark, dropped in [
        ("2.3022801280046E+23", 2),        # 24 digits -> 6 groups
        ("2.1012302280029E+27", 3),        # 28 digits -> 7 groups
        ("3.3022601260226002E+51", 9),     # 52 digits -> 13 groups
    ]:
        parsed = tc.parse_codes(remark)
        assert len(parsed.codes) == 4, remark
        assert parsed.dropped == dropped, remark


def test_no_padding_zeros_are_emitted_as_codes() -> None:
    for remark in ("2.8002100230029001E+19", "3.3022601260226002E+51"):
        assert "0000" not in tc.parse_codes(remark).codes


# -- left alone --------------------------------------------------------------

@pytest.mark.parametrize("remark", ["IFS, 5R4", "C4101, A L BOS", "5R4"])
def test_flight_school_text_is_left_alone(remark: str) -> None:
    parsed = tc.parse_codes(remark)
    assert parsed.kind == tc.TEXT
    assert parsed.codes == () and parsed.dropped == 0


@pytest.mark.parametrize("remark", ["", "   ", None])
def test_missing_remark(remark: str | None) -> None:
    assert tc.parse_codes(remark).kind == tc.EMPTY


def test_no_description_lookup_is_applied() -> None:
    """Codes stay as codes: the mapping file is the pilot's to maintain."""
    assert codes("2800") == "2800"
    assert not hasattr(tc, "DESCRIPTIONS")


# -- Notes plumbing and the plan --------------------------------------------

def test_parses_the_logbook_remark_line_out_of_notes() -> None:
    """A prefixed line still wins, for any row not yet migrated."""
    notes = "Imported from SkedPlus 2026-01-01\nLogbook remark: 28004300"
    assert tc.parse_notes(notes).joined == "2800, 4300"


def test_an_empty_notes_field_yields_nothing() -> None:
    """The importer leaves Notes empty on the rows it writes."""
    for notes in ("", "   ", None):
        assert tc.parse_notes(notes).kind == tc.EMPTY


def test_a_provenance_only_row_is_not_mistaken_for_a_remark() -> None:
    assert tc.parse_notes(PREAMBLE).kind == tc.EMPTY


PREAMBLE = ("Historical line-item import from LEN2J-x.xlsx (Master row 9). "
            "Secondary hours (night/instr/XC/landings) distributed "
            "proportionally to preserve per-aircraft totals.")


def test_build_plan_writes_codes_and_strips_the_preamble() -> None:
    rows = [
        {"id": 1, "notes": f"{PREAMBLE}\nLogbook remark: 28004300"},
        {"id": 2, "notes": f"{PREAMBLE}\nLogbook remark: 2.8002100230029001E+19"},
        {"id": 3, "notes": f"{PREAMBLE}\nLogbook remark: IFS, 5R4"},
        {"id": 4, "notes": PREAMBLE},
    ]
    plan = tc.build_plan(rows)
    assert plan.counts == {tc.EXACT: 1, tc.RECONSTRUCTED: 1, tc.TEXT: 1, tc.EMPTY: 1}
    fields = dict(plan.updates)
    # codes only where there are codes
    assert fields[1] == {"Training_Codes": "2800, 4300", "Notes": "2800, 4300"}
    assert fields[2] == {"Training_Codes": "2800, 2100, 2300, 2900",
                         "Notes": "2800, 2100, 2300, 2900"}
    # the pilot's own words survive; the preamble does not
    assert fields[3] == {"Notes": "IFS, 5R4"}
    assert "Training_Codes" not in fields[3]
    # provenance-only rows end up empty
    assert fields[4] == {"Notes": ""}
    assert plan.codes_written == 6 and plan.dropped == 1
    assert plan.notes_cleaned == 4 and plan.code_rows == 2


def test_a_single_code_is_kept_verbatim() -> None:
    """"just keep the number 4603"."""
    plan = tc.build_plan([{"id": 1, "notes": f"{PREAMBLE}\nLogbook remark: 4603"}])
    assert dict(plan.updates)[1]["Notes"] == "4603"


def test_no_preamble_survives_anywhere() -> None:
    rows = [{"id": i, "notes": f"{PREAMBLE}\nLogbook remark: {r}"}
            for i, r in enumerate(["4603", "IFS, 5R4", "2.1012302280029E+27"], 1)]
    for _, fields in tc.build_plan(rows).updates:
        assert "Historical line-item import" not in fields.get("Notes", "")


def test_rerunning_the_plan_is_a_no_op() -> None:
    """Already-cleaned rows must not be rewritten on a second run."""
    cleaned = [
        {"id": 1, "notes": "2800, 4300", "existing": "2800, 4300"},
        {"id": 2, "notes": "IFS, 5R4"},
        {"id": 3, "notes": ""},
    ]
    plan = tc.build_plan(cleaned)
    assert plan.updates == [] and plan.notes_cleaned == 0


def test_cleaned_notes_still_read_back_as_the_same_codes() -> None:
    assert tc.parse_codes("2800, 4300").codes == ("2800", "4300")
    assert tc.parse_codes("4603").codes == ("4603",)


def test_apply_plan_sends_a_uniform_field_set() -> None:
    sent: list = []

    class Fake(tc.GristClient):
        def __init__(self) -> None:
            pass

        def update_records(self, table, updates):        # type: ignore[override]
            sent.append((table, updates))

    plan = tc.build_plan([{"id": 7, "notes": f"{PREAMBLE}\nLogbook remark: 2800"},
                          {"id": 8, "notes": f"{PREAMBLE}\nLogbook remark: IFS"}])
    assert tc.apply_plan(Fake(), plan) == 2
    table, updates = sent[0]
    assert table == "Flights"
    # Grist needs a uniform field set per PATCH; update_records groups these.
    assert {frozenset(f) for _, f in updates} == {
        frozenset({"Training_Codes", "Notes"}), frozenset({"Notes"})}
