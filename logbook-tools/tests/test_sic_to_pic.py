"""The SIC-to-PIC backfill: the rule, the join, and the gates that refuse."""

from __future__ import annotations

from datetime import date

import pytest

from logbook_import import sic_to_pic as stp
from logbook_import.sic_to_pic import BackfillError, GristRow, WorkbookRow

DAY = date(2019, 6, 1)


def wrow(code="UC12W", tail="TEST01", block=1.0, sic=0.0, pf=0.0, day=DAY):
    return WorkbookRow(date=day, code=stp.squash(code), tail=stp.squash(tail),
                       block=block, sic=sic, pf=pf)


def grow(rid=1, aircraft="UC-12W", tail="TEST01", block=1.0, pic=0.0, day=DAY):
    return GristRow(id=rid, date=day, aircraft=aircraft,
                    code=stp.squash(aircraft), tail=stp.squash(tail),
                    block=block, pic=pic)


# -- normalisation -----------------------------------------------------------

def test_squash_bridges_the_two_spellings() -> None:
    assert stp.squash("AH-1Z") == stp.squash("AH1Z") == "AH1Z"
    assert stp.squash("UC-12W") == stp.squash("UC12W") == "UC12W"
    assert stp.squash("T-6B") == stp.squash("T6B") == "T6B"
    assert stp.squash(900001) == "900001"      # numeric idents keep their digits


def test_osprey_suffix_is_aliased() -> None:
    """The workbook writes MV22B; the Aircraft table writes MV-22."""
    assert stp.squash("MV22B") == stp.squash("MV-22") == "MV22"


# -- the rule ----------------------------------------------------------------

def test_sic_to_pic_is_pf_on_sic_rows() -> None:
    assert wrow(sic=2.0, pf=2.0).sic_to_pic == 2.0


def test_pf_on_a_pic_row_is_not_sic_to_pic() -> None:
    """The 142.9 h of PF already logged as PIC would double-count."""
    assert wrow(sic=0.0, pf=3.0).sic_to_pic == 0.0


@pytest.mark.parametrize("code", ["T6B", "TH57B", "TH57C"])
def test_flight_school_is_excluded(code: str) -> None:
    row = wrow(code=code, sic=1.5, pf=1.5)
    assert row.is_school and row.sic_to_pic == 0.0


# -- the join ----------------------------------------------------------------

def test_duplicate_keys_are_assigned_in_order() -> None:
    """Two identical legs on one day map to the two Grist rows, lowest id first."""
    wb = [wrow(sic=1.0, pf=1.0), wrow(sic=1.0, pf=0.5)]
    plan = stp.build_plan(wb, [grow(rid=11), grow(rid=12)])
    assert plan.updates == [(11, 1.0), (12, 0.5)]
    assert plan.matched == 2 and not plan.leftover_grist


def test_unmatched_workbook_row_is_reported_and_gated() -> None:
    plan = stp.build_plan([wrow(day=date(2001, 1, 1), sic=1.0, pf=1.0)], [grow()])
    assert len(plan.unmatched_workbook) == 1
    assert plan.leftover_grist and plan.matched == 0
    with pytest.raises(BackfillError, match="did not match"):
        stp.check_gate(plan)


def test_block_time_is_part_of_the_key() -> None:
    plan = stp.build_plan([wrow(block=1.0, sic=1.0, pf=1.0)], [grow(block=2.0)])
    assert plan.matched == 0


# -- the overlap invariant ---------------------------------------------------

def test_sic_to_pic_never_overlaps_pic_on_the_same_row() -> None:
    """A row logging PIC cannot also log supervised SIC time."""
    with pytest.raises(BackfillError, match="cannot overlap PIC"):
        stp.build_plan([wrow(sic=1.0, pf=1.0)], [grow(pic=1.0)])


def test_a_pic_row_with_no_supervised_time_is_fine() -> None:
    plan = stp.build_plan([wrow(sic=0.0, pf=1.0)], [grow(pic=1.0)])
    assert plan.updates == [(1, 0.0)] and plan.total == 0.0


# -- the reconciliation gate -------------------------------------------------

def gate_fixture() -> tuple[list[WorkbookRow], list[GristRow]]:
    """A minimal pair of row sets that reproduces every expected figure."""
    wb: list[WorkbookRow] = []
    gr: list[GristRow] = []
    rid = 0
    for aircraft, hours in stp.EXPECTED_BY_AIRCRAFT.items():
        rid += 1
        day = date(2019, 1, 1 + rid)
        wb.append(wrow(code=aircraft, tail=f"T{rid}", block=hours, sic=hours,
                       pf=hours, day=day))
        gr.append(grow(rid=rid, aircraft=aircraft, tail=f"T{rid}", block=hours,
                       day=day))
    # PF already logged as PIC: counts toward the PF totals, never toward the gate.
    rid += 1
    pic_pf = round(stp.EXPECTED_PF_EXCL_SCHOOL - stp.EXPECTED_TOTAL, 1)
    wb.append(wrow(code="UC12W", tail="PIC", block=pic_pf, sic=0.0, pf=pic_pf))
    gr.append(grow(rid=rid, aircraft="UC-12W", tail="PIC", block=pic_pf, pic=pic_pf))
    # Flight school PF: excluded from the gate, included in PF all-types.
    rid += 1
    school = round(stp.EXPECTED_PF_ALL - stp.EXPECTED_PF_EXCL_SCHOOL, 1)
    wb.append(wrow(code="T6B", tail="SCH", block=school, sic=school, pf=school))
    gr.append(grow(rid=rid, aircraft="T-6B", tail="SCH", block=school))
    return wb, gr


def test_gate_passes_on_the_expected_figures() -> None:
    plan = stp.build_plan(*gate_fixture())
    stp.check_gate(plan)                                  # must not raise
    assert plan.by_aircraft == stp.EXPECTED_BY_AIRCRAFT
    assert plan.total == pytest.approx(stp.EXPECTED_TOTAL)
    assert plan.pf_all == pytest.approx(stp.EXPECTED_PF_ALL)
    assert plan.pf_excl_school == pytest.approx(stp.EXPECTED_PF_EXCL_SCHOOL)


def test_gate_refuses_a_short_aircraft_total() -> None:
    wb, gr = gate_fixture()
    wb[0] = wrow(code="UC-12W", tail="T1", block=wb[0].block, sic=wb[0].sic,
                 pf=wb[0].pf - 0.1, day=wb[0].date)
    with pytest.raises(BackfillError, match="reconciliation failed"):
        stp.check_gate(stp.build_plan(wb, gr))


def test_gate_refuses_when_the_pf_column_is_wrong() -> None:
    """Proof the right workbook column was read at all.

    Losing the flight-school rows takes PF all-types down to the non-school
    figure, so the all-types check is the one that fires.
    """
    wb, gr = gate_fixture()
    wb = [r for r in wb if not r.is_school]               # drops 138.7 h of PF
    with pytest.raises(BackfillError, match="PF total"):
        stp.check_gate(stp.build_plan(wb, gr))


def test_gate_refuses_when_flight_school_leaks_into_the_total() -> None:
    """The non-school PF check catches school time counted as supervised SIC."""
    wb, gr = gate_fixture()
    extra = wrow(code="UC12W", tail="LEAK", block=5.0, sic=0.0, pf=5.0,
                 day=date(2019, 12, 25))
    gr = gr + [grow(rid=99, aircraft="UC-12W", tail="LEAK", block=5.0, pic=5.0,
                    day=date(2019, 12, 25))]
    with pytest.raises(BackfillError, match="PF"):
        stp.check_gate(stp.build_plan(wb + [extra], gr))


def test_expected_rotorcraft_total_is_212_6() -> None:
    rotor = sum(stp.EXPECTED_BY_AIRCRAFT[a] for a in ("AH-1Z", "AH-1W", "UH-1Y"))
    assert rotor == pytest.approx(212.6)
    assert sum(stp.EXPECTED_BY_AIRCRAFT.values()) == pytest.approx(stp.EXPECTED_TOTAL)


# -- the wrong file ----------------------------------------------------------

def test_the_atp_workbook_is_refused() -> None:
    """556 rows / 1500.5 h is the '_ATP' file, which the pilot confirmed wrong."""
    rows = [wrow(block=1500.5 / 556, sic=0.0, pf=0.0) for _ in range(556)]
    with pytest.raises(BackfillError, match="_ATP"):
        stp.check_workbook(rows)


def test_the_right_workbook_passes_the_shape_check() -> None:
    rows = [wrow(block=1506.3, sic=0.0, pf=stp.EXPECTED_PF_EXCL_SCHOOL)]
    rows += [wrow(code="T6B", block=0.0, sic=0.0,
                  pf=stp.EXPECTED_PF_ALL - stp.EXPECTED_PF_EXCL_SCHOOL)]
    rows += [wrow(block=0.0) for _ in range(stp.EXPECTED_ROWS - 2)]
    stp.check_workbook(rows)                              # must not raise


# -- writing -----------------------------------------------------------------

def test_apply_plan_writes_only_rows_that_carry_time() -> None:
    """Explicit zeros would fire the Edited trigger formula for no gain."""
    sent: list = []

    class Fake(stp.GristClient):
        def __init__(self) -> None:
            pass

        def update_records(self, table, updates):        # type: ignore[override]
            sent.append((table, updates))

    plan = stp.build_plan(
        [wrow(sic=1.0, pf=1.0), wrow(tail="other", sic=0.0, pf=0.0)],
        [grow(rid=1), grow(rid=2, tail="other")],
    )
    assert len(plan.updates) == 2 and len(plan.nonzero) == 1
    assert stp.apply_plan(Fake(), plan) == 1
    table, updates = sent[0]
    assert table == "Flights"
    assert updates == [(1, {"SIC_to_PIC": 1.0})]
    assert {frozenset(f) for _, f in updates} == {frozenset({"SIC_to_PIC"})}
