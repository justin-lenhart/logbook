"""The standing reference block, the Allegiant profile, and the rules that
must not leak between targets.

Southwest converts military sorties; Allegiant forbids conversions entirely.
Both live in ``profiles.py``, so the conversion guard here is load-bearing.
"""

from __future__ import annotations

import dataclasses
from datetime import date

import pytest

from logbook_import import profiles
from logbook_import import profile_render as render
from logbook_import.profile_data import Leg
from logbook_import.profiles import (
    ALLEGIANT,
    FAA,
    PROFILES,
    REFERENCE_SECTIONS,
    SWA,
    UAL,
    Context,
    Pilot,
    Section,
)
from test_profile_data import CRJ, OSPREY, SKYHAWK, leg

CTX = Context(as_of=date(2026, 11, 10), pilot=Pilot(name="Pat Pilot"))

# UC-12W: the only aircraft that satisfies Allegiant field 17 today.
KINGAIR = dict(aircraft="UC-12W", faa_type="B300", category="Airplane",
               aircraft_class="Multi-Engine Land", engine_category="Turbine",
               engine_type="Turboprop", operation="Military")


@pytest.fixture
def legs() -> list[Leg]:
    return [
        # supervised SIC: all of its SIC time was flown as pilot flying
        leg(1, "2019-06-01", KINGAIR, block=2.0, sic=2.0, sic_to_pic=2.0,
            xc=2.0, night=1.0),
        # PIC with sorties: the conversion guard hangs off this row
        leg(2, "2020-06-01", KINGAIR, block=3.0, pic=3.0, mil_sortie=2),
        leg(3, "2026-05-10", CRJ, block=2.0, sic=2.0, xc=2.0),
        leg(4, "2015-03-01", SKYHAWK, block=1.0, pic=1.0, xc=1.0, night=0.5),
    ]


def ref(title: str) -> Section:
    return next(s for s in REFERENCE_SECTIONS if s.title == title)


def matrix(sec: Section, legs: list[Leg]) -> dict[str, list]:
    """{row label: [value per column]} -- orientation-independent."""
    return {
        row.label: [row.value([l for l in legs if col.where(l)], CTX)
                    for col in sec.columns]
        for row in sec.rows
    }


def allegiant_fields(legs: list[Leg]) -> dict[str, float]:
    sec = ALLEGIANT.sections[0]
    return {row.label: row.value(legs, CTX) for row in sec.rows}


# -- the reference block ships on every target ------------------------------

def test_every_target_closes_with_the_reference_block(legs: list[Leg]) -> None:
    for target, profile in PROFILES.items():
        html = render.render_profile(profile, legs, CTX, include_log=False)
        assert "Application Reference" in html, target
        for title in ("Totals by FAA Type", "Hours by Category", "Class Hours"):
            assert title in html, f"{target} missing {title}"


def test_reference_block_is_three_tables() -> None:
    assert [s.title for s in REFERENCE_SECTIONS] == [
        "Totals by FAA Type", "Hours by Category", "Class Hours",
    ]


def test_summary_by_aircraft_type_is_kept_alongside_faa_type() -> None:
    """They answer different questions, so both stay (per-aircraft and per-type)."""
    assert ref("Totals by FAA Type").group(
        leg(1, "2026-01-01", CRJ, block=1.0)) == "CL65"
    by_aircraft = next(s for s in profiles.SUMMARY_SECTIONS
                       if s.title == "Summary by Aircraft Type")
    assert by_aircraft.group(leg(1, "2026-01-01", CRJ, block=1.0)) == "CR7"


# -- table 1: totals by FAA type --------------------------------------------

def test_faa_type_collapses_variants_and_lists_them() -> None:
    """CR2 + CR7 are one CL65 type rating; the row names both aircraft."""
    crjs = [leg(1, "2026-01-01", {**CRJ, "aircraft": "CR2"}, block=2.0, sic=2.0),
            leg(2, "2026-02-01", CRJ, block=1.0, sic=1.0)]
    sec = ref("Totals by FAA Type")
    groups = {g.key: g for g in render.pd.by_type(crjs, sec.group)}
    assert list(groups) == ["CL65"]
    cells = {row.label: row.value(groups["CL65"].legs, CTX) for row in sec.rows}
    assert cells["TYPES INCLUDED"] == "CR2 / CR7"
    assert cells["Total"] == pytest.approx(3.0)


def test_faa_type_grouping_survives_a_display_name_change() -> None:
    """Grouping keys on FAA_Type, so renaming the Aircraft code cannot move it."""
    sec = ref("Totals by FAA Type")
    renamed = leg(1, "2026-01-01", {**CRJ, "aircraft": "CRJ-700 (renamed)"}, block=1.0)
    assert sec.group(renamed) == "CL65"


def test_faa_type_table_reports_sic_to_pic(legs: list[Leg]) -> None:
    sec = ref("Totals by FAA Type")
    groups = {g.key: g for g in render.pd.by_type(legs, sec.group)}
    row = next(r for r in sec.rows if r.label == "SIC->PIC")
    assert row.value(groups["B300"].legs, CTX) == pytest.approx(2.0)
    assert row.value(groups["CL65"].legs, CTX) == pytest.approx(0.0)


def test_totals_row_leaves_types_included_blank(legs: list[Leg]) -> None:
    """Re-listing every aircraft on the TOTAL row would just be noise."""
    html = render.render_section(ref("Totals by FAA Type"), legs, CTX)
    foot = html.split("<tfoot>")[1]
    assert "<th>TOTAL</th><td></td>" in foot
    assert "UC-12W" not in foot


# -- table 2 / table 3: categories and classes reconcile --------------------

def test_class_hours_reconcile_against_hours_by_category(legs: list[Leg]) -> None:
    cat = matrix(ref("Hours by Category"), legs)
    cls = matrix(ref("Class Hours"), legs)
    labels = [c.label for c in ref("Class Hours").columns]
    total = dict(zip(labels, cls["Total"]))
    airplane, rotor, lift = cat["Total Hours"]

    assert total["ASEL"] + total["AMEL"] == pytest.approx(airplane)
    assert total["Helicopter"] == pytest.approx(rotor)
    assert total["ASES"] == total["AMES"] == total["Gyroplane"] == 0.0
    assert lift == pytest.approx(0.0)        # no powered lift in this fixture


def test_class_hours_rows_sum_to_their_total(legs: list[Leg]) -> None:
    """PIC + SIC + Instruction Received = Total -- the 105.6 h gap closer."""
    cls = matrix(ref("Class Hours"), legs)
    for i, label in enumerate(c.label for c in ref("Class Hours").columns):
        parts = cls["PIC"][i] + cls["SIC"][i] + cls["Instruction Received"][i]
        assert parts == pytest.approx(cls["Total"][i]), label


def test_class_hours_renders_classes_down_the_page(legs: list[Leg]) -> None:
    html = render.render_section(ref("Class Hours"), legs, CTX)
    assert "<th>ASEL</th>" in html and "<th>Instruction Received</th>" in html


def test_powered_lift_has_no_airplane_class() -> None:
    """MV-22 is Multi-Engine Land but Powered Lift: it must not land in AMEL."""
    osprey = [leg(1, "2021-01-01", OSPREY, block=0.6, sic=0.6)]
    cls = matrix(ref("Class Hours"), osprey)
    assert all(v == 0.0 for v in cls["Total"])
    assert matrix(ref("Hours by Category"), osprey)["Total Hours"][2] == pytest.approx(0.6)


def test_category_table_reads_stored_night_xc_instrument() -> None:
    """Stored values are printed as-is, so an importer redefinition flows through."""
    sec = ref("Hours by Category")
    one = [leg(1, "2026-01-01", CRJ, block=5.0, sic=5.0, night=9.9, xc=8.8,
               instrument=7.7)]
    m = matrix(sec, one)
    assert m["Night"][0] == pytest.approx(9.9)
    assert m["Cross Country"][0] == pytest.approx(8.8)
    assert m["Instrument"][0] == pytest.approx(7.7)


# -- Allegiant ---------------------------------------------------------------

def test_allegiant_is_registered_and_fields_are_in_form_order() -> None:
    assert PROFILES["allegiant"] is ALLEGIANT
    labels = [r.label for r in ALLEGIANT.sections[0].rows]
    assert len(labels) == 17
    assert [l.split(".")[0] for l in labels] == [str(i) for i in range(1, 18)]


def test_allegiant_field_values(legs: list[Leg]) -> None:
    f = allegiant_fields(legs)
    assert f["1. Total flight time"] == pytest.approx(8.0)
    assert f["2. Total fixed-wing"] == pytest.approx(8.0)
    assert f["3. Cross-country"] == pytest.approx(5.0)
    assert f["4. Night"] == pytest.approx(1.5)
    assert f["5. Multi-Engine Land"] == pytest.approx(7.0)
    assert f["10. Turbine fixed-wing"] == pytest.approx(7.0)
    assert f["11. Turbine fixed-wing PIC"] == pytest.approx(3.0)
    assert f["12. Turbine fixed-wing SIC"] == pytest.approx(4.0)
    assert f["13. Part 121 PIC"] == pytest.approx(0.0)
    assert f["14. Part 121 SIC"] == pytest.approx(2.0)
    assert f["15. Part 135 PIC"] == pytest.approx(0.0)
    assert f["16. Part 135 SIC"] == pytest.approx(0.0)


def test_allegiant_supervised_sic_fields(legs: list[Leg]) -> None:
    """Fields 7-9: PIC plus SIC-to-PIC, the figures he had to leave blank."""
    f = allegiant_fields(legs)
    assert f["7. PIC airplane or supervised SIC airplane"] == pytest.approx(6.0)
    assert f["8. Cross-country as PIC or supervised SIC"] == pytest.approx(3.0)
    assert f["9. Night as PIC or supervised SIC"] == pytest.approx(1.5)


def test_allegiant_field_17_is_raw_pic_not_converted_sorties(legs: list[Leg]) -> None:
    f = allegiant_fields(legs)
    assert f["17. Military qualifying time"] == pytest.approx(3.0)
    # 3.0 + 0.3 * 2 sorties = 3.6 would be the Southwest answer. Not here.
    assert f["17. Military qualifying time"] != pytest.approx(3.6)


def test_allegiant_field_17_excludes_non_qualifying_aircraft() -> None:
    """Single-pilot and non-allowlisted aircraft contribute nothing."""
    other = [leg(1, "2019-01-01", {**SKYHAWK, "operation": "Military"},
                 block=4.0, pic=4.0)]
    assert allegiant_fields(other)["17. Military qualifying time"] == pytest.approx(0.0)


def test_allegiant_never_applies_the_sortie_conversion(legs: list[Leg]) -> None:
    """THE GUARD: Southwest's x0.3 conversion must not reach Allegiant.

    Allegiant: "does not accept conversions, substitutions, landing credits,
    simulator time, or any UAS/drone time." Rendering with the sortie counts
    multiplied must therefore produce a byte-identical Allegiant sheet.
    """
    more_sorties = [dataclasses.replace(l, mil_sortie=l.mil_sortie * 10) for l in legs]
    plain = render.render_section(ALLEGIANT.sections[0], legs, CTX)
    inflated = render.render_section(ALLEGIANT.sections[0], more_sorties, CTX)
    assert plain == inflated

    # ... while Southwest, in the same module, genuinely does convert.
    swa_plain = render.render_section(SWA.sections[0], legs, CTX)
    swa_inflated = render.render_section(SWA.sections[0], more_sorties, CTX)
    assert swa_plain != swa_inflated


def test_allegiant_prints_one_unrounded_decimal(legs: list[Leg]) -> None:
    """"Enter exact flight times ...; do not round." -- tenths, never integers."""
    html = render.render_section(ALLEGIANT.sections[0], legs, CTX)
    assert ">8.0<" in html and ">1.5<" in html
    assert ">8<" not in html


# -- pending targets ---------------------------------------------------------

def test_pending_targets_are_not_guessed() -> None:
    """JetBlue and Delta wait for their real field lists."""
    assert profiles.PENDING_TARGETS == ("jetblue", "delta")
    for target in profiles.PENDING_TARGETS:
        assert target not in PROFILES
