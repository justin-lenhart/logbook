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
    JETBLUE,
    PROFILES,
    REFERENCE_SECTIONS,
    SWA,
    UAL,
    Context,
    Pilot,
    Section,
)
from test_profile_data import COBRA, CRJ, OSPREY, SKYHAWK, leg

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
    """Delta waits for its real field list."""
    assert profiles.PENDING_TARGETS == ("delta",)
    for target in profiles.PENDING_TARGETS:
        assert target not in PROFILES


# -- JetBlue -----------------------------------------------------------------
# The form reports flight time as a dropdown band, so these tests pin the
# band ladder, the Engine Type wording and the FAA_Type grouping against the
# application actually submitted. The seven aircraft rows below are that form's
# own entries: the profile must reproduce them, not approximate them.

TH57 = dict(aircraft="TH-57C", faa_type="H57", category="Helicopter",
            aircraft_class="Rotorcraft", engine_category="Turbine",
            engine_type="Turboshaft", operation="Military")
TEXAN = dict(aircraft="T-6B", faa_type="T6", category="Airplane",
             aircraft_class="Single-Engine Land", engine_category="Turbine",
             engine_type="Turboprop", operation="Military")
SEMINOLE = dict(aircraft="PA-44", faa_type="PA44", category="Airplane",
                aircraft_class="Multi-Engine Land",
                engine_category="Reciprocating",
                engine_type="Reciprocating", operation="Part 91")

# Engine Type exactly as it reads on the submitted application, per FAA type.
SUBMITTED_ENGINE_TYPES = {
    "CL65": "Multi engine - Turbojet",
    "B300": "Multi engine - Turboprop",
    "H1": "Multi engine - Helicopter",
    "H57": "Single engine - Helicopter",
    "T6": "Single engine - Turboprop",
    "C172": "Single engine - Piston",
    "PA44": "Multi engine - Piston",
}

SUBMITTED_KINDS = {"CL65": CRJ, "B300": KINGAIR, "H1": COBRA, "H57": TH57,
                   "T6": TEXAN, "C172": SKYHAWK, "PA44": SEMINOLE}


def jetblue_section(title: str) -> Section:
    return next(s for s in JETBLUE.sections if s.title.endswith(title))


def jetblue_rows(title: str, legs: list[Leg]) -> dict[str, object]:
    sec = jetblue_section(title)
    return {row.label: row.value(legs, CTX) for row in sec.rows}


def test_jetblue_is_registered_and_no_longer_pending() -> None:
    assert PROFILES["jetblue"] is JETBLUE
    assert "jetblue" not in profiles.PENDING_TARGETS


def test_jetblue_sections_follow_the_application_order() -> None:
    assert [s.title for s in JETBLUE.sections] == [
        "Pilots Only: Total Flight Time",
        "Pilots Only: Aircraft Type and Flight Time",
        "Pilots Only: Flight Experience",
        "Pilots Only: Additional Questions",
    ]


# -- band ladders ------------------------------------------------------------

def test_only_observed_band_labels_are_used() -> None:
    """A figure off the observed ladder defers to the dropdown, never invents."""
    assert profiles._band(profiles.JETBLUE_TYPE_BANDS, 0.6) == "Less than 100"
    assert profiles._band(profiles.JETBLUE_TYPE_BANDS, 99.9) == "Less than 100"
    assert profiles._band(profiles.JETBLUE_TYPE_BANDS, 100.0) == "100 - 499"
    assert profiles._band(profiles.JETBLUE_TYPE_BANDS, 499.9) == "100 - 499"
    assert profiles._band(profiles.JETBLUE_TYPE_BANDS, 500.0) == "500 - 999"
    assert profiles._band(profiles.JETBLUE_TYPE_BANDS, 1200.0) == profiles.OFF_LADDER
    assert profiles._band(profiles.JETBLUE_TOTAL_BANDS, 1845.4) == "1500 – 1999"
    assert profiles._band(profiles.JETBLUE_TOTAL_BANDS, 2001.0) == profiles.OFF_LADDER


def test_total_and_type_ladders_stay_separate() -> None:
    """The form prints one with an en dash and the other with a hyphen."""
    total = {label for _, _, label in profiles.JETBLUE_TOTAL_BANDS}
    types = {label for _, _, label in profiles.JETBLUE_TYPE_BANDS}
    assert total & types == set()
    assert all("–" in label for label in total)
    assert all("–" not in label for label in types)


def test_band_prints_the_hours_it_was_read_from(legs: list[Leg]) -> None:
    rows = jetblue_rows("Total Flight Time", legs)
    assert rows["Total Number of Flight Hours"] == f"{profiles.OFF_LADDER}  [8.0 h]"


# -- recency questions -------------------------------------------------------

def test_recency_questions_count_fixed_wing_from_the_as_of_date() -> None:
    recent = [leg(1, "2026-06-01", CRJ, block=200.0, sic=200.0),
              leg(2, "2026-06-02", COBRA, block=500.0, pic=500.0)]
    rows = jetblue_rows("Total Flight Time", recent)
    # The 500 helicopter hours are not fixed wing and answer neither question.
    assert rows["125+ fixed-wing hours in the last 12 months?"] == "Yes  [200.0 h]"
    assert rows["250+ fixed-wing hours in the last 24 months?"] == "No  [200.0 h]"


def test_recency_questions_ignore_time_outside_the_window() -> None:
    old = [leg(1, "2020-01-01", CRJ, block=900.0, sic=900.0)]
    rows = jetblue_rows("Total Flight Time", old)
    assert rows["125+ fixed-wing hours in the last 12 months?"] == "No  [0.0 h]"


# -- aircraft rows -----------------------------------------------------------

def test_engine_type_reproduces_every_submitted_row() -> None:
    for faa_type, expected in SUBMITTED_ENGINE_TYPES.items():
        one = leg(1, "2020-01-01", SUBMITTED_KINDS[faa_type], block=1.0)
        assert profiles._jetblue_engine(one) == expected, faa_type


def test_twin_engine_helicopters_are_named_not_inferred() -> None:
    """Grist records no engine count, so H-1 is multi only via the allowlist."""
    assert profiles.JETBLUE_MULTI_ENGINE_TYPES == ("H1",)
    cobra = leg(1, "2020-01-01", COBRA, block=1.0)
    assert cobra.aircraft_class == "Rotorcraft"      # not Multi-Engine Land
    assert profiles._jetblue_engine(cobra) == "Multi engine - Helicopter"
    assert profiles._jetblue_engine(
        leg(2, "2020-01-01", TH57, block=1.0)) == "Single engine - Helicopter"


def test_powered_lift_falls_back_to_the_nearest_dropdown_option() -> None:
    """The Engine Type list has no tiltrotor; a turboshaft reads as helicopter."""
    osprey = leg(1, "2021-01-01", OSPREY, block=0.6, sic=0.6)
    assert profiles._jetblue_engine(osprey) == "Multi engine - Helicopter"
    assert profiles._jetblue_name(osprey) == "Bell Boeing MV-22B Osprey"


def test_an_unlisted_aircraft_still_gets_a_name() -> None:
    """A new type must show up on the form, not vanish from the table."""
    unknown = leg(1, "2026-01-01", {**CRJ, "faa_type": "E170"}, block=1.0)
    assert profiles._jetblue_name(unknown) == profiles.model(unknown)


def test_aircraft_rows_group_on_faa_type(legs: list[Leg]) -> None:
    sec = jetblue_section("Aircraft Type and Flight Time")
    crjs = [leg(1, "2026-01-01", {**CRJ, "aircraft": "CR2"}, block=400.0, sic=400.0),
            leg(2, "2026-02-01", CRJ, block=200.0, sic=200.0)]
    groups = {g.key: g for g in render.pd.by_type(crjs, sec.group)}
    assert list(groups) == ["CL65"]
    cells = {row.label: row.value(groups["CL65"].legs, CTX) for row in sec.rows}
    assert cells["AIRCRAFT TYPE (FILL IN)"] == "Bombardier CRJ-200/550/700/900 (CL-65)"
    assert cells["FLIGHT TIME"] == "500 - 999  [600.0 h]"
    assert cells["HOURS"] == pytest.approx(600.0)


def test_aircraft_totals_row_totals_only_the_hours(legs: list[Leg]) -> None:
    """A band is not summable, and the names would just be noise."""
    html = render.render_section(jetblue_section("Aircraft Type and Flight Time"),
                                 legs, CTX)
    foot = html.split("<tfoot>")[1]
    assert "<th>TOTAL</th><td></td><td></td><td></td>" in foot
    assert ">8.0<" in foot


# -- flight experience -------------------------------------------------------

def test_supervised_sic_counts_as_command_time() -> None:
    """A King Air leg flown as pilot flying under a supervising PIC."""
    supervised = [leg(1, "2019-06-01", KINGAIR, block=2.0, sic=2.0, sic_to_pic=2.0)]
    plain = [leg(1, "2026-05-10", CRJ, block=2.0, sic=2.0)]
    assert profiles._jetblue_position(supervised, CTX) == "Commander"
    assert profiles._jetblue_position(plain, CTX) == "Second in Command"


def test_experience_rows_split_military_from_each_operating_rule(
        legs: list[Leg]) -> None:
    sec = jetblue_section("Flight Experience")
    groups = {g.key: g for g in render.pd.by_type(legs, sec.group)}
    assert set(groups) == {"Military", "Part 121", "Part 91"}
    cells = {row.label: row.value(groups["Part 121"].legs, CTX)
             for row in sec.rows}
    assert cells["FLYING STATUS"] == "Civilian"
    assert cells["TYPE OF FLYING"] == "United States based Part 121"
    assert cells["POSITION"] == "Second in Command"
    assert cells["AIRCRAFT TYPE"] == "EFIS and Jet"


def test_helicopter_experience_is_not_a_jet(legs: list[Leg]) -> None:
    cobra = [leg(1, "2019-06-01", COBRA, block=2.0, pic=2.0)]
    assert profiles._jetblue_fleet(cobra, CTX) == "Non Fighter"


def test_timeframe_defers_when_the_span_is_not_an_offered_option() -> None:
    """Only "0-1 Year" and "2 Years or More" were on the submitted form."""
    short = [leg(1, "2026-04-08", CRJ, block=1.0), leg(2, "2026-11-08", CRJ, block=1.0)]
    mid = [leg(1, "2025-01-01", CRJ, block=1.0), leg(2, "2026-07-01", CRJ, block=1.0)]
    long = [leg(1, "2015-07-14", COBRA, block=1.0), leg(2, "2024-02-12", COBRA, block=1.0)]
    assert profiles._jetblue_timeframe(short, CTX).startswith("0-1 Year")
    assert profiles._jetblue_timeframe(mid, CTX).startswith(profiles.OFF_LADDER)
    assert profiles._jetblue_timeframe(long, CTX).startswith("2 Years or More")


# -- additional questions ----------------------------------------------------

def test_instructor_hours_are_logged_dual_given(legs: list[Leg]) -> None:
    instructing = legs + [leg(9, "2020-06-02", COBRA, block=3.0, pic=3.0,
                              dual_given=3.0)]
    rows = jetblue_rows("Additional Questions", instructing)
    assert rows["Instructor hours"] == pytest.approx(3.0)
    assert rows["250 hours dual given or more as a flight instructor?"] == "No  [3.0 h]"
    assert rows["Check airman hours"] == 0.0


def test_military_experience_reads_the_operating_rule(legs: list[Leg]) -> None:
    rows = jetblue_rows("Additional Questions", legs)
    assert rows["Military experience as a pilot?"].startswith("Yes")
    civil = [leg(1, "2026-05-10", CRJ, block=2.0, sic=2.0)]
    assert jetblue_rows("Additional Questions", civil)[
        "Military experience as a pilot?"] == "No  [0.0 h]"


def test_other_type_ratings_come_from_pilot_toml_not_the_flights() -> None:
    """A rating is held whether or not it has been flown lately."""
    label = ("Type rating in a fixed-wing aircraft other than an "
             "A320 / E190 / A220?")
    rated = dataclasses.replace(CTX, pilot=Pilot(type_ratings=("CL65", "BE300")))
    jb_only = dataclasses.replace(CTX, pilot=Pilot(type_ratings=("A320",)))
    row = next(r for r in jetblue_section("Additional Questions").rows
               if r.label == label)
    assert row.value([], rated) == "Yes  [CL65, BE300]"
    assert row.value([], jb_only) == "No"


# -- the conversion guard reaches JetBlue too --------------------------------

def test_jetblue_never_applies_the_sortie_conversion() -> None:
    """Southwest's conversion lives in this module; a band must not absorb it."""
    sortied = [leg(1, "2020-06-01", KINGAIR, block=499.0, pic=499.0, mil_sortie=20)]
    rows = jetblue_rows("Total Flight Time", sortied)
    # 499.0 + 0.3 * 20 = 505.0 would cross into the next band.
    assert "[499.0 h]" in rows["Total Number of Flight Hours"]
    sec = jetblue_section("Aircraft Type and Flight Time")
    cells = {row.label: row.value(sortied, CTX) for row in sec.rows}
    assert cells["FLIGHT TIME"] == "100 - 499  [499.0 h]"
    assert cells["HOURS"] == pytest.approx(499.0)
