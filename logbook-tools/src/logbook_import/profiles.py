"""Export profiles: what each target (FAA 8710 and the airlines) wants to see.

A ``Profile`` is a list of ``Section`` specs. The carriers differ structurally,
so each section names a layout ``kind``:

- ``metrics``            headline block of label/value pairs
- ``matrix``             rows x category columns (FAA 8710 Section III)
- ``by_type``            one table row per aircraft type, one column per Row
- ``per_aircraft_form``  a repeating form block per aircraft type

Every number is a ``Metric``: ``fn(legs, ctx) -> value``. For ``matrix`` the
legs are pre-filtered by the column; for the per-type kinds they are one
type's legs. ``profile_render`` turns the specs into HTML.

Pilot identity is not in Grist — it comes from a gitignored ``pilot.toml``.
"""

from __future__ import annotations

import math
import tomllib
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path

from logbook_import import profile_data as pd
from logbook_import.profile_data import Leg, Predicate

Value = float | int | str | date | None


@dataclass(frozen=True)
class Pilot:
    name: str = ""
    certificate: str = ""
    certificate_number: str = ""
    ratings: tuple[str, ...] = ()
    type_ratings: tuple[str, ...] = ()   # FAA_Type codes, e.g. "CL65"


@dataclass(frozen=True)
class Context:
    as_of: date
    pilot: Pilot


Metric = Callable[[Sequence[Leg], Context], Value]

# A note under a table is either fixed wording or one written from the legs on
# that sheet, so a figure quoted in prose is read from Grist like every other
# figure on the page. A computed note that comes back empty is left out.
Note = str | Callable[[Sequence[Leg], Context], str]


@dataclass(frozen=True)
class Row:
    label: str
    value: Metric
    group: str = ""          # by_type only: column-group heading
    in_totals: bool = True   # by_type: False leaves the totals-row cell blank


@dataclass(frozen=True)
class Column:
    label: str
    where: Predicate


@dataclass(frozen=True)
class Section:
    title: str
    kind: str                                   # metrics | matrix | by_type | per_aircraft_form
    rows: tuple[Row, ...] = ()                  # by_type: these are the table columns
    columns: tuple[Column, ...] = ()            # matrix only
    form: tuple[tuple[Row, ...], ...] = ()      # per_aircraft_form: rows of cells
    group: Callable[[Leg], str] = lambda leg: leg.aircraft   # per-type kinds
    totals: bool = False                        # by_type: append a totals row
    transpose: bool = False                     # matrix: classes down, metrics across
    notes: tuple[Note, ...] = ()


@dataclass(frozen=True)
class Profile:
    target: str
    title: str
    sections: tuple[Section, ...]
    # False drops the supervised-SIC rows from the shared reference block as
    # well: a carrier whose own form has no box for that time should not be
    # handed a column it cannot read.
    reports_supervised_sic: bool = True


def load_pilot(path: Path) -> Pilot:
    """Read pilot.toml. A missing file gives a blank Pilot (the caller warns)."""
    if not path.is_file():
        return Pilot()
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    return Pilot(
        name=str(data.get("name", "")),
        certificate=str(data.get("certificate", "")),
        certificate_number=str(data.get("certificate_number", "")),
        ratings=tuple(str(r) for r in data.get("ratings", [])),
        type_ratings=tuple(str(r) for r in data.get("type_ratings", [])),
    )


# -- metric builders ---------------------------------------------------------

def hours(field: str = "block", where: Predicate | None = None,
          share: str | None = None) -> Metric:
    return lambda legs, ctx: pd.total(legs, field, where, share)


def count(field: str, where: Predicate | None = None) -> Metric:
    return lambda legs, ctx: round(pd.total(legs, field, where))


def recent(months: int, field: str = "block") -> Metric:
    return lambda legs, ctx: pd.total(pd.within(legs, months, ctx.as_of), field)


def not_tracked(legs: Sequence[Leg], ctx: Context) -> None:
    return None


def zero(legs: Sequence[Leg], ctx: Context) -> float:
    return 0.0


def distinct(attr: Callable[[Leg], str]) -> Metric:
    """The distinct values of ``attr`` across the legs, in first-flown order."""
    def metric(legs: Sequence[Leg], ctx: Context) -> str:
        return " / ".join(dict.fromkeys(v for v in map(attr, legs) if v))
    return metric


def last_flown(fmt: str) -> Metric:
    def metric(legs: Sequence[Leg], ctx: Context) -> str:
        day = pd.last_flown(legs)
        return day.strftime(fmt) if day else ""
    return metric


# -- aircraft naming ---------------------------------------------------------
# The Aircraft table has no manufacturer / model columns (and adding Grist
# columns is a user decision), so display names live here. ``group`` is the
# aircraft "type" an airline application expects: the CRJ variants are one
# CL-65 type rating; everything else stands alone. Unknown codes fall back to
# the Aircraft code itself.

AIRCRAFT_INFO: dict[str, tuple[str, str, str]] = {
    # code:   (group,    manufacturer,  model)
    "AH-1Z":  ("AH-1Z",  "Bell",        "AH-1Z Viper"),
    "AH-1W":  ("AH-1W",  "Bell",        "AH-1W Super Cobra"),
    "UH-1Y":  ("UH-1Y",  "Bell",        "UH-1Y Venom"),
    "TH-57B": ("TH-57B", "Bell",        "TH-57B Sea Ranger (206)"),
    "TH-57C": ("TH-57C", "Bell",        "TH-57C Sea Ranger (206)"),
    "MV-22":  ("MV-22B", "Bell Boeing", "MV-22B Osprey"),
    "UC-12W": ("UC-12W", "Beechcraft",  "UC-12W (King Air 350)"),
    "T-6B":   ("T-6B",   "Beechcraft",  "T-6B Texan II"),
    "C172":   ("C172",   "Cessna",      "172 Skyhawk"),
    "PA-44":  ("PA-44",  "Piper",       "PA-44 Seminole"),
    "CR2":    ("CL-65",  "Bombardier",  "CRJ-200"),
    "CR5":    ("CL-65",  "Bombardier",  "CRJ-550"),
    "CR7":    ("CL-65",  "Bombardier",  "CRJ-700"),
    "CR9":    ("CL-65",  "Bombardier",  "CRJ-900"),
    "E175":   ("E175",   "Embraer",     "E175"),
}


def _info(leg: Leg) -> tuple[str, str, str]:
    code = leg.aircraft or "(no aircraft)"
    return AIRCRAFT_INFO.get(leg.aircraft, (code, "", code))


def type_group(leg: Leg) -> str:
    return _info(leg)[0]


def manufacturer(leg: Leg) -> str:
    return _info(leg)[1]


def model(leg: Leg) -> str:
    return _info(leg)[2]


# -- summary (first in every export) ----------------------------------------

_FW_TURBINE = pd.all_of(pd.is_airplane, pd.is_turbine)

SYNTHETIC_NOTE = (
    "Pre-2026 night, instrument, cross-country and landing figures exist as "
    "verified category totals only; they are not recorded per flight."
)

# Same column groups as the certified log pages. This is a summary, so the
# aggregate-only columns (landings, night, instrument, XC) are allowed here.
BY_TYPE_COLUMNS: tuple[Row, ...] = (
    Row("TOTAL", hours(), "TOTAL"),
    Row("ASEL", hours(where=pd.is_single), "CAT / CLASS"),
    Row("AMEL", hours(where=pd.is_multi), "CAT / CLASS"),
    Row("HELO", hours(where=pd.is_rotorcraft), "CAT / CLASS"),
    Row("LIFT", hours(where=pd.is_powered_lift), "CAT / CLASS"),
    Row("DAY", count("day_landings"), "LANDINGS"),
    Row("NT", count("night_landings"), "LANDINGS"),
    Row("NT", hours("night"), "CONDITIONS"),
    Row("ACT IN", hours("instrument"), "CONDITIONS"),
    Row("XC", hours("xc"), "PILOTING TIME"),
    Row("PIC", hours("pic"), "PILOTING TIME"),
    Row("SIC", hours("sic"), "PILOTING TIME"),
    Row("DUAL", hours("dual_received"), "PILOTING TIME"),
    Row("IP/CFI", hours("dual_given"), "PILOTING TIME"),
    Row("SORTIE", count("mil_sortie"), "MILITARY"),
    Row("NVG", hours("nvg"), "MILITARY"),
    Row("COMBAT", hours("combat"), "MILITARY"),
)

SUMMARY_SECTIONS: tuple[Section, ...] = (
    Section(
        title="Flight Time",
        kind="metrics",
        rows=(
            Row("Total Time", hours()),
            Row("FW Multi-Eng", hours(where=pd.is_multi)),
            Row("FW Turbine", hours(where=_FW_TURBINE)),
            Row("FW PIC", hours("pic", pd.is_airplane)),
            Row("Hrs PIC", hours("pic")),
            Row("Military", hours(where=pd.is_military)),
        ),
        notes=("No military conversions applied.", "No simulator time included."),
    ),
    Section(
        title="1 / 2 / 3 Yr History",
        kind="metrics",
        rows=(
            Row("Last 12 months", recent(12)),
            Row("Last 24 months", recent(24)),
            Row("Last 36 months", recent(36)),
        ),
    ),
    Section(
        title="Summary by Aircraft Type",
        kind="by_type",
        rows=BY_TYPE_COLUMNS,
        totals=True,
        notes=(SYNTHETIC_NOTE,),
    ),
)


# -- FAA 8710 / IACRA Section III -------------------------------------------

_CATEGORY_COLUMNS = (
    Column("Airplane", pd.is_airplane),
    Column("Rotorcraft", pd.is_rotorcraft),
    Column("Powered Lift", pd.is_powered_lift),
)
_ALL = (Column("Hours", lambda leg: True),)

# -- application reference block (closes every export) ----------------------
# Three standing tables the airline applications all draw on. They go on every
# target, so a figure quoted on one application can be traced on any other.
#
# Grouping is always on ``Aircraft.FAA_Type``, never a display name: a typo fix
# in the Aircraft table must not be able to move a grouping. Night, instrument
# and cross-country are read as stored and never recomputed here, so a change
# to how the importer defines them flows straight through to these tables.

SIC_TO_PIC_LABEL = "SIC-to-PIC (\u00a761.51)"

SIC_TO_PIC_NOTE = (
    "SIC-to-PIC is second-in-command time flown as pilot flying under the "
    "supervision of a pilot in command, logged under 14 CFR 61.51. It is a "
    "subset of SIC time, not an addition to it, and never overlaps PIC on the "
    "same flight."
)

# Table 1 -- totals by FAA type. CL65 collapses the CRJ variants; H1 the
# AH-1Z / AH-1W / UH-1Y; H57 the TH-57B / TH-57C.
FAA_TYPE_COLUMNS: tuple[Row, ...] = (
    # Listing every aircraft again on the TOTAL row would just be noise.
    Row("TYPES INCLUDED", distinct(lambda leg: leg.aircraft), in_totals=False),
    Row("Total", hours(), "HOURS"),
    Row("PIC", hours("pic"), "HOURS"),
    Row("SIC", hours("sic"), "HOURS"),
    Row("SIC->PIC", hours("sic_to_pic"), "HOURS"),
    Row("Dual Recv", hours("dual_received"), "HOURS"),
    Row("Instructor", hours("dual_given"), "HOURS"),
    Row("Night", hours("night"), "CONDITIONS"),
    Row("Instrument", hours("instrument"), "CONDITIONS"),
    Row("XC", hours("xc"), "CONDITIONS"),
    Row("Day", count("day_landings"), "LANDINGS"),
    Row("Night", count("night_landings"), "LANDINGS"),
    Row("Last flown", last_flown("%Y-%m-%d")),
)

# Table 3 -- class hours. Columns are the classes, rows the roles; PIC + SIC +
# Instruction Received = Total for each class, and the Total row adds up to the
# matching category column in table 2 (Powered Lift has no FAA class, so it
# appears in table 2 only).
_CLASS_COLUMNS = (
    Column("ASEL", pd.is_single),
    Column("ASES", pd.never),
    Column("AMEL", pd.is_multi),
    Column("AMES", pd.never),
    Column("Helicopter", pd.is_rotorcraft),
    Column("Gyroplane", pd.never),
)

REFERENCE_SECTIONS: tuple[Section, ...] = (
    Section(
        title="Totals by FAA Type",
        kind="by_type",
        rows=FAA_TYPE_COLUMNS,
        group=lambda leg: leg.faa_type or "(no type)",
        totals=True,
        notes=(SIC_TO_PIC_NOTE, SYNTHETIC_NOTE),
    ),
    Section(
        title="Hours by Category",
        kind="matrix",
        columns=_CATEGORY_COLUMNS,
        rows=(
            Row("Total Hours", hours()),
            Row("Pilot in Command (PIC)", hours("pic")),
            Row("Second in Command (SIC)", hours("sic")),
            Row(SIC_TO_PIC_LABEL, hours("sic_to_pic")),
            Row("Instruction Received", hours("dual_received")),
            Row("Instructor Given", hours("dual_given")),
            Row("Night", hours("night")),
            Row("Instrument", hours("instrument")),
            Row("Cross Country", hours("xc")),
            Row("Day Landings", count("day_landings")),
            Row("Night Landings", count("night_landings")),
        ),
        notes=(SYNTHETIC_NOTE,),
    ),
    Section(
        title="Class Hours",
        kind="matrix",
        columns=_CLASS_COLUMNS,
        transpose=True,
        rows=(
            Row("PIC", hours("pic")),
            Row("SIC", hours("sic")),
            Row("Instruction Received", hours("dual_received")),
            Row("Total", hours()),
        ),
        notes=(
            "PIC + SIC + Instruction Received = Total for each class. The Total "
            "column reconciles against Hours by Category: ASEL + AMEL equals the "
            "Airplane column, Helicopter equals the Rotorcraft column.",
            "Powered Lift (MV-22) has no FAA airplane class and appears in Hours "
            "by Category only.",
            "ASES, AMES and Gyroplane are 0.0: none flown.",
        ),
    ),
)

# The supervised-SIC rows, by label, and the note that explains them.
_SUPERVISED_ROWS: frozenset[str] = frozenset({"SIC->PIC", SIC_TO_PIC_LABEL})


def reference_sections(profile: Profile) -> tuple[Section, ...]:
    """The standing reference block as one target should see it.

    Every other figure in the block is the same on every export, so a number
    quoted on one application can still be traced from any other.
    """
    if profile.reports_supervised_sic:
        return REFERENCE_SECTIONS
    return tuple(
        replace(
            section,
            rows=tuple(r for r in section.rows
                       if r.label not in _SUPERVISED_ROWS),
            notes=tuple(n for n in section.notes if n != SIC_TO_PIC_NOTE),
        )
        for section in REFERENCE_SECTIONS
    )


FAA = Profile(
    target="faa",
    title="FAA Form 8710-1 / IACRA — Section III Record of Pilot Time",
    sections=(
        Section(
            title="Section III — Record of Pilot Time",
            kind="matrix",
            columns=_CATEGORY_COLUMNS,
            rows=(
                Row("Total Hours", hours()),
                Row("Instruction Received", hours("dual_received")),
                Row("Solo", not_tracked),
                Row("Pilot in Command (PIC)", hours("pic")),
                Row("Second in Command (SIC)", hours("sic")),
                Row("Cross Country Instruction", hours("xc", share="dual_received")),
                Row("Cross Country Solo", not_tracked),
                Row("Cross Country PIC", hours("xc", share="pic")),
                Row("Cross Country SIC", hours("xc", share="sic")),
                Row("Instrument", hours("instrument")),
                Row("Night Instruction", hours("night", share="dual_received")),
                Row("Night Takeoff Landings", count("night_landings")),
                Row("Night PIC", hours("night", share="pic")),
                Row("Night SIC", hours("night", share="sic")),
                Row("Night Takeoff Landing PIC", count("night_landings", pd.is_pic)),
                Row("Night Takeoff Landing SIC", count("night_landings", pd.is_sic)),
            ),
            notes=(
                "— : not tracked in this logbook (solo time).",
                SYNTHETIC_NOTE + " The PIC / SIC / instruction splits of night and "
                "cross-country time before 2026 are therefore proportional estimates; "
                "the totals they add up to are exact.",
            ),
        ),
        Section(
            title="Glider / Lighter Than Air",
            kind="matrix",
            columns=_ALL,
            rows=(Row("Glider", zero), Row("Lighter Than Air", zero)),
            notes=("No glider or lighter-than-air time.",),
        ),
    ),
)


# -- United (pilothiring.united.com) ----------------------------------------

def _ual_class(leg: Leg) -> str:
    if pd.is_airplane(leg):
        return leg.aircraft_class.replace("-", " ")      # "Multi Engine Land"
    return {"Helicopter": "Rotorcraft Helicopter"}.get(leg.category, leg.category)


def _ual_powerplant(leg: Leg) -> str:
    # United's form offers "Propeller" or "Jet". Helicopters fit neither, so the
    # engine type is printed and the pilot picks the closest option on the form.
    return {"Turbofan": "Jet", "Turboprop": "Propeller",
            "Reciprocating": "Propeller"}.get(leg.engine_type, leg.engine_type)


def _operation(leg: Leg) -> str:
    return leg.operation if leg.operation == "Military" else f"FAR {leg.operation}"


def _type_rated(legs: Sequence[Leg], ctx: Context) -> str:
    rated = {leg.faa_type for leg in legs} & set(ctx.pilot.type_ratings)
    return "Yes" if rated else "No"


UAL = Profile(
    target="ual",
    title="United Airlines — Aircraft Experience",
    sections=(
        Section(
            title="Aircraft Flown",
            kind="per_aircraft_form",
            group=type_group,
            form=(
                (Row("Aircraft manufacturer", distinct(manufacturer)),
                 Row("Model", distinct(model))),
                (Row("Aircraft class", distinct(_ual_class)),
                 Row("Powerplant", distinct(_ual_powerplant))),
                (Row("Type of operation", distinct(_operation)),
                 Row("Type rated", _type_rated)),
                (Row("Last flown month", last_flown("%B")),
                 Row("Last flown year", last_flown("%Y"))),
                (Row("Total PIC (including time as an instructor)", hours("pic")),),
            ),
            notes=("No military conversions applied.",),
        ),
    ),
)


# -- Southwest ---------------------------------------------------------------

SORTIE_FACTOR = 0.3


def _converted(role: str) -> Metric:
    """Sorties flown in ``role`` x the sortie factor."""
    return lambda legs, ctx: SORTIE_FACTOR * pd.total(
        legs, "mil_sortie", lambda leg: getattr(leg, role) > 0)


def _with_conversion(role: str) -> Metric:
    return lambda legs, ctx: pd.total(legs, role) + _converted(role)(legs, ctx)


def _label_only(legs: Sequence[Leg], ctx: Context) -> str:
    return ""


SWA = Profile(
    target="swa",
    title="Southwest Airlines — Flight Time by Aircraft",
    sections=(
        Section(
            title="Aircraft Flown",
            kind="per_aircraft_form",
            group=type_group,
            form=(
                (Row("Aircraft", distinct(type_group)),
                 Row("PIC", hours("pic")),
                 Row("SIC", hours("sic")),
                 Row("Instructor", hours("dual_given")),
                 Row("Last 24 mo", recent(24))),
                (Row("Operating Rule", distinct(_operation)),
                 Row("PIC Sorties", count("mil_sortie", pd.is_pic)),
                 Row("SIC Sorties", count("mil_sortie", pd.is_sic)),
                 Row("Last Flown Date", last_flown("%Y-%m-%d"))),
                (Row(f"Sortie factor {SORTIE_FACTOR}", _label_only),
                 Row("PIC conversion", _converted("pic")),
                 Row("SIC conversion", _converted("sic"))),
                (Row("Total w/ conversion", _label_only),
                 Row("PIC", _with_conversion("pic")),
                 Row("SIC", _with_conversion("sic"))),
            ),
            notes=(
                f"Military sortie conversion: each sortie adds {SORTIE_FACTOR} h to the "
                "role it was flown in (PIC or SIC). Sorties flown as a student "
                "(dual received) are not converted.",
            ),
        ),
    ),
)


# -- Allegiant ---------------------------------------------------------------
# Allegiant's own instruction, verbatim: "Enter exact flight times as of the
# application date; do not round. Allegiant does not accept conversions,
# substitutions, landing credits, simulator time, or any UAS/drone time."
#
# So this profile prints raw logged hours to one decimal and must NEVER apply
# the Southwest sortie conversion (SORTIE_FACTOR), which lives in this same
# module. test_profiles.py guards that: same codebase, opposite rules.

# Field 17 wants PIC in a multi-engine turbine fixed-wing or powered-lift
# aircraft flown in a multi-pilot operation. "Requiring more than one pilot" is
# not recorded in Grist, so the qualifying aircraft are listed explicitly rather
# than inferred from Class + Engine + Category -- that filter only happens to
# give the right answer today (MV-22 PIC is 0, so no powered lift slips in).
def _is_part135(leg: Leg) -> bool:
    return leg.operation == "Part 135"


MIL_MULTI_PILOT_TYPES: tuple[str, ...] = ("UC-12W", "MV-22")


def _is_mil_multi_pilot(leg: Leg) -> bool:
    return leg.aircraft in MIL_MULTI_PILOT_TYPES


def _mil_qualifying(legs: Sequence[Leg], ctx: Context) -> float:
    """Raw logged PIC on the qualifying aircraft -- not converted sorties."""
    return pd.total(legs, "pic", pd.all_of(_is_mil_multi_pilot, pd.is_military))


_APL = pd.is_airplane


def _supervised(field: str, where: Predicate | None = None) -> Metric:
    """PIC plus supervised-SIC (SIC-to-PIC) share of ``field``.

    Allegiant's fields 7-9 accept time as PIC *or* as an SIC performing PIC
    duties under supervision. For ``block`` that is a plain sum of the two
    columns; for night / cross-country it is each role's proportional share of
    the leg, the same basis the FAA 8710 sheet uses.
    """
    def metric(legs: Sequence[Leg], ctx: Context) -> float:
        if field == "block":
            return pd.total(legs, "pic", where) + pd.total(legs, "sic_to_pic", where)
        return (pd.total(legs, field, where, share="pic")
                + pd.total(legs, field, where, share="sic_to_pic"))
    return metric


ALLEGIANT = Profile(
    target="allegiant",
    title="Allegiant Air — Flight Time (application field order)",
    sections=(
        Section(
            title="Flight Time",
            kind="matrix",
            columns=_ALL,
            rows=(
                Row("1. Total flight time", hours()),
                Row("2. Total fixed-wing", hours(where=_APL)),
                Row("3. Cross-country", hours("xc")),
                Row("4. Night", hours("night")),
                Row("5. Multi-Engine Land", hours(where=pd.is_multi)),
                Row("6. Instrument", hours("instrument")),
                Row("7. PIC airplane or supervised SIC airplane",
                    _supervised("block", _APL)),
                Row("8. Cross-country as PIC or supervised SIC",
                    _supervised("xc", _APL)),
                Row("9. Night as PIC or supervised SIC",
                    _supervised("night", _APL)),
                Row("10. Turbine fixed-wing", hours(where=_FW_TURBINE)),
                Row("11. Turbine fixed-wing PIC", hours("pic", _FW_TURBINE)),
                Row("12. Turbine fixed-wing SIC", hours("sic", _FW_TURBINE)),
                Row("13. Part 121 PIC", hours("pic", pd.is_part121)),
                Row("14. Part 121 SIC", hours("sic", pd.is_part121)),
                Row("15. Part 135 PIC", hours("pic", _is_part135)),
                Row("16. Part 135 SIC", hours("sic", _is_part135)),
                Row("17. Military qualifying time", _mil_qualifying),
            ),
            notes=(
                "Exact logged times, not rounded. No military sortie conversion, "
                "no substitutions, no landing credits, no simulator time and no "
                "UAS time are applied anywhere on this form.",
                "Fields 7-9 combine PIC with SIC-to-PIC (14 CFR 61.51) in "
                "airplanes; fields 8 and 9 use each role's proportional share of "
                "the leg.",
                "Field 17 is raw logged PIC in "
                + " / ".join(MIL_MULTI_PILOT_TYPES)
                + " on military operations: multi-engine turbine fixed-wing or "
                "powered lift, flown multi-pilot.",
                SYNTHETIC_NOTE,
            ),
        ),
    ),
)


# -- JetBlue -----------------------------------------------------------------
# JetBlue's application (SuccessFactors) almost never asks for an exact figure.
# Flight time is picked from a dropdown of *bands* -- once for total time and
# again on every aircraft row -- and the recency questions are plain yes/no. So
# this profile prints the band or the answer the logbook supports with, in
# brackets, the hours it was read from, so every entry traces to the certified
# log pages.
#
# Only band labels actually seen on the application are encoded here. A figure
# outside them prints the hours and defers to the dropdown rather than inventing
# a label that may not be on the list. Add the next label to the ladder when the
# hours grow past it.

Band = tuple[float, float, str]      # low (inclusive), high (exclusive), label

OFF_LADDER = "(select the matching range)"

# "Total Number of Flight Hours". The form prints these with an en dash.
JETBLUE_TOTAL_BANDS: tuple[Band, ...] = (
    (1500.0, 2000.0, "1500 – 1999"),
)

# "Flight Time" on each aircraft row. The form prints these with a hyphen.
JETBLUE_TYPE_BANDS: tuple[Band, ...] = (
    (0.0, 100.0, "Less than 100"),
    (100.0, 500.0, "100 - 499"),
    (500.0, 1000.0, "500 - 999"),
)

# "Timeframe" on each flight-experience row. The gap is real: nothing between
# one and two years was offered, so a span in it defers to the dropdown.
JETBLUE_TIMEFRAMES: tuple[Band, ...] = (
    (0.0, 1.0, "0-1 Year"),
    (2.0, 200.0, "2 Years or More"),
)

# JetBlue's own fleet, for "a type rating in a fixed-wing aircraft other than
# an A320 / E190 / A220".
JETBLUE_FLEET_TYPES: tuple[str, ...] = ("A320", "E190", "A220")

# These sections answer questions and pick bands, so the single column is not
# headed "Hours" the way ``_ALL`` is.
_ANSWER = (Column("Answer", lambda leg: True),)


def _band(bands: Sequence[Band], value: float) -> str:
    for low, high, label in bands:
        if low <= value < high:
            return label
    return OFF_LADDER


def _banded(bands: Sequence[Band], field: str = "block",
            where: Predicate | None = None) -> Metric:
    """The dropdown band for a total, with the hours behind it."""
    def metric(legs: Sequence[Leg], ctx: Context) -> str:
        value = pd.total(legs, field, where)
        return f"{_band(bands, value)}  [{value:.1f} h]"
    return metric


def _threshold(needed: float, months: int,
               where: Predicate | None = None) -> Metric:
    """A yes/no recency question, with the hours that answer it."""
    def metric(legs: Sequence[Leg], ctx: Context) -> str:
        flown = pd.total(pd.within(legs, months, ctx.as_of), "block", where)
        return f"{'Yes' if flown >= needed else 'No'}  [{flown:.1f} h]"
    return metric


def _at_least(needed: float, field: str) -> Metric:
    """A yes/no question about a lifetime total."""
    def metric(legs: Sequence[Leg], ctx: Context) -> str:
        value = pd.total(legs, field)
        return f"{'Yes' if value >= needed else 'No'}  [{value:.1f} h]"
    return metric


def _any_time(where: Predicate) -> Metric:
    def metric(legs: Sequence[Leg], ctx: Context) -> str:
        value = pd.total(legs, "block", where)
        return f"{'Yes' if value > 0 else 'No'}  [{value:.1f} h]"
    return metric


# The aircraft rows are keyed on FAA_Type -- one row per type rating, which is
# how the form is meant to be filled. The names are the ones already on file
# with JetBlue, so a resubmission matches; an aircraft with no entry here falls
# back to its model name rather than disappearing from the table.
JETBLUE_TYPE_NAMES: dict[str, str] = {
    "CL65": "Bombardier CRJ-200/550/700/900 (CL-65)",
    "B300": "Beechcraft King Air 350ER / UC-12W (BE-300)",
    "H1":   "Bell AH-1Z Viper (H-1 series: AH-1Z, AH-1W, UH-1Y)",
    "H57":  "Bell TH-57B/C Sea Ranger",
    "T6":   "Beechcraft T-6B Texan II",
    "C172": "Cessna 172",
    "PA44": "Piper PA-44 Seminole",
    "V22":  "Bell Boeing MV-22B Osprey",
}

# The Engine Type dropdown reads "<Single|Multi> engine - <word>". Grist records
# no engine count, so a multi-engine type outside the Multi-Engine Land class is
# named here: the H-1s are twin-engine helicopters of class Rotorcraft.
JETBLUE_MULTI_ENGINE_TYPES: tuple[str, ...] = ("H1",)

JETBLUE_ENGINE_WORDS: dict[str, str] = {
    "Turbofan": "Turbojet",
    "Turboprop": "Turboprop",
    "Turboshaft": "Helicopter",      # the only turboshaft option on the list
    "Reciprocating": "Piston",
}


def _jetblue_name(leg: Leg) -> str:
    return JETBLUE_TYPE_NAMES.get(leg.faa_type) or model(leg)


def _jetblue_engine(leg: Leg) -> str:
    multi = (leg.aircraft_class == "Multi-Engine Land"
             or leg.faa_type in JETBLUE_MULTI_ENGINE_TYPES)
    word = JETBLUE_ENGINE_WORDS.get(leg.engine_type, leg.engine_type)
    return f"{'Multi' if multi else 'Single'} engine - {word}"


def _jetblue_rule(leg: Leg) -> str:
    """Grouping key for the flight-experience rows."""
    return "Military" if pd.is_military(leg) else leg.operation or "(no rule)"


def _jetblue_status(leg: Leg) -> str:
    return "Military" if pd.is_military(leg) else "Civilian"


def _jetblue_flying(leg: Leg) -> str:
    if pd.is_military(leg):
        return "United States Military"
    return f"United States based {leg.operation}"


def _jetblue_position(legs: Sequence[Leg], ctx: Context) -> str:
    """The highest seat held on that equipment.

    The form asks which position was flown, not which one holds the most
    hours, so any logged PIC time makes the row a command row. JetBlue asks
    nothing about SIC time flown under supervision, so this target reads
    neither ``sic_to_pic`` nor anything derived from it.
    """
    return "Commander" if pd.total(legs, "pic") > 0 else "Second in Command"


def _jetblue_fleet(legs: Sequence[Leg], ctx: Context) -> str:
    """JetBlue's "Aircraft Type" on an experience row: a jet, or not."""
    return "EFIS and Jet" if any(pd.is_jet(leg) for leg in legs) else "Non Fighter"


def _jetblue_timeframe(legs: Sequence[Leg], ctx: Context) -> str:
    days = (max(leg.date for leg in legs) - min(leg.date for leg in legs)).days
    years = days / 365.25
    return f"{_band(JETBLUE_TIMEFRAMES, years)}  [{years:.1f} yr]"


def _jetblue_other_type_rating(legs: Sequence[Leg], ctx: Context) -> str:
    """Type ratings held that are not on JetBlue's own fleet.

    Read from pilot.toml, not from the flights: a rating is held whether or not
    it has been flown recently.
    """
    other = [t for t in ctx.pilot.type_ratings if t not in JETBLUE_FLEET_TYPES]
    return f"Yes  [{', '.join(other)}]" if other else "No"


JETBLUE = Profile(
    target="jetblue",
    title="JetBlue Airways — Pilot Application (flight time sections)",
    # The application asks nothing about SIC time flown under supervision, so
    # the reference block drops those rows on this target too.
    reports_supervised_sic=False,
    sections=(
        Section(
            title="Pilots Only: Total Flight Time",
            kind="matrix",
            columns=_ANSWER,
            rows=(
                Row("125+ fixed-wing hours in the last 12 months?",
                    _threshold(125.0, 12, _APL)),
                Row("250+ fixed-wing hours in the last 24 months?",
                    _threshold(250.0, 24, _APL)),
                Row("Total Number of Flight Hours",
                    _banded(JETBLUE_TOTAL_BANDS)),
            ),
            notes=(
                "Recency counts fixed-wing time only, over the 12 and 24 months "
                "ending on the as-of date above.",
                "Each answer shows the application's own range followed by the "
                "exact logged hours behind it, in brackets.",
            ),
        ),
        Section(
            title="Pilots Only: Aircraft Type and Flight Time",
            kind="by_type",
            group=lambda leg: leg.faa_type or "(no type)",
            rows=(
                Row("AIRCRAFT TYPE (FILL IN)", distinct(_jetblue_name),
                    in_totals=False),
                Row("ENGINE TYPE", distinct(_jetblue_engine), in_totals=False),
                Row("FLIGHT TIME (SELECTED)", _banded(JETBLUE_TYPE_BANDS),
                    in_totals=False),
                Row("EXACT HOURS", hours()),
            ),
            totals=True,
            notes=(
                "One row per type rating: the CRJ-200 / 550 / 700 / 900 are a "
                "single CL-65 rating, and the AH-1Z / AH-1W / UH-1Y a single "
                "H-1 series rating.",
                "The MV-22B is a tiltrotor. The Engine Type list offers no "
                "powered-lift option, so it is entered as multi-engine "
                "helicopter.",
            ),
        ),
        Section(
            title="Pilots Only: Flight Experience",
            kind="by_type",
            group=_jetblue_rule,
            rows=(
                Row("FLYING STATUS", distinct(_jetblue_status), in_totals=False),
                Row("TYPE OF FLYING", distinct(_jetblue_flying), in_totals=False),
                Row("POSITION", _jetblue_position, in_totals=False),
                Row("AIRCRAFT TYPE", _jetblue_fleet, in_totals=False),
                Row("TIMEFRAME", _jetblue_timeframe, in_totals=False),
                Row("HOURS", hours()),
            ),
            totals=True,
            notes=(
                "One row per flying status and operating rule.",
                "POSITION is the highest seat held on that equipment; TIMEFRAME "
                "is the span from the first to the last flight flown on it.",
            ),
        ),
        Section(
            title="Pilots Only: Additional Questions",
            kind="matrix",
            columns=_ANSWER,
            rows=(
                Row("Instructor hours", hours("dual_given")),
                Row("250 hours dual given or more as a flight instructor?",
                    _at_least(250.0, "dual_given")),
                Row("Check airman hours", zero),
                Row("Military experience as a pilot?", _any_time(pd.is_military)),
                Row("Type rating in a fixed-wing aircraft other than an "
                    "A320 / E190 / A220?", _jetblue_other_type_rating),
            ),
            notes=(
                "Instructor hours is instruction given as a logged flight "
                "instructor. No check airman time has been flown.",
                "Type ratings held are listed in full on the first sheet.",
            ),
        ),
    ),
)


# -- American (aa.com pilot application) -------------------------------------
# One block of American's application: a repeating per-aircraft entry, headed
# "Aircraft 1", "Aircraft 2" and so on. Only that block is built here. The rest
# of the form has not been transcribed, so nothing else about it is guessed --
# see PENDING_TARGETS for how an unseen form is handled.
#
# Two of American's own instructions shape the whole sheet:
#
#   "For aircraft operated under multiple operating rules (e.g., Part 121,
#   Part 135, etc), please create separate entries for each."
#
# so an entry is one aircraft type under ONE operating rule, which is what the
# section groups on; and
#
#   "If you have no hours for any field, enter 0. Round hours to the nearest
#   whole number."
#
# so every hours figure on this sheet is a whole number -- rounded, never
# truncated. The exact tenths are not repeated here: the standing Totals by
# FAA Type table at the back of every export already carries them, grouped the
# same way, so nothing is lost and no figure on this sheet can disagree with
# the number typed into the form.

# The H-1 series: AH-1Z, AH-1W and UH-1Y are one FAA type (H1) and one
# designation on the form, so they are reported as a single AH-1Z entry and
# ``_aal_variant_note`` accounts for the other two underneath the table.
AAL_COLLAPSED: dict[str, str] = {"H1": "AH-1Z"}

# Role wording for that note, in the order it reads best.
_AAL_ROLE_WORDS: tuple[tuple[str, str], ...] = (
    ("pic", "pilot in command"),
    ("sic", "second in command"),
    ("dual_received", "a student under instruction"),
    ("dual_given", "a flight instructor"),
)


def _half_up(value: float) -> int:
    """Round to the nearest whole number, halves away from zero.

    ``round()`` breaks a tie to the even number, so it reports 41.5 h as 42
    and 42.5 h as 42. A form that says "nearest whole number" means half up,
    and either way the figure is rounded, never truncated: 41.8 h is 42.
    """
    return math.floor(value + 0.5) if value >= 0 else math.ceil(value - 0.5)


def whole(field: str = "block", where: Predicate | None = None) -> Metric:
    """``field`` summed over the legs, as a whole number of hours."""
    return lambda legs, ctx: _half_up(pd.total(legs, field, where))


def whole_recent(months: int) -> Metric:
    """Hours flown in the ``months`` ending on the as-of date, whole."""
    return lambda legs, ctx: _half_up(
        pd.total(pd.within(legs, months, ctx.as_of)))


def _aal_landings(legs: Sequence[Leg], ctx: Context) -> int:
    """One Landings field on the form; Grist counts day and night apart."""
    return _half_up(pd.total(legs, "day_landings")
                    + pd.total(legs, "night_landings"))


def _aal_entry(leg: Leg) -> str:
    """One application entry: an FAA type under one operating rule.

    Grouping is on ``Aircraft.FAA_Type``, never a display name, so a spelling
    fix in the Aircraft table cannot move a row; the operating rule is part of
    the key because American wants a separate entry for each one.
    """
    return f"{leg.faa_type or '(no type)'} · {_operation(leg)}"


def _aal_type(legs: Sequence[Leg], ctx: Context) -> str:
    """The aircraft designation this entry is filed under."""
    named = next((AAL_COLLAPSED[leg.faa_type] for leg in legs
                  if leg.faa_type in AAL_COLLAPSED), None)
    return named or distinct(type_group)(legs, ctx)


def _join(parts: Sequence[str]) -> str:
    if len(parts) < 2:
        return "".join(parts)
    return ", ".join(parts[:-1]) + (" and " if len(parts) == 2 else ", and ") + parts[-1]


def _role_phrase(legs: Sequence[Leg]) -> str:
    """How the time in ``legs`` was flown, checked against the logbook.

    The claim is written from the hours, not assumed: time that is not all one
    role is reported as the split it actually is.
    """
    parts = [(word, pd.total(legs, field)) for field, word in _AAL_ROLE_WORDS
             if pd.total(legs, field) > 0]
    if not parts:
        return ""
    if len(parts) == 1:
        return f"all flown as {parts[0][0]}"
    return _join([f"{h:.1f} hours as {word}" for word, h in parts])


def _aal_variant_note(legs: Sequence[Leg], ctx: Context) -> str:
    """What a collapsed entry covers, in hours read from the logbook."""
    sentences = []
    for faa_type, primary in AAL_COLLAPSED.items():
        others = [leg for leg in legs
                  if leg.faa_type == faa_type and leg.aircraft != primary]
        if not others:
            continue
        flown = _join([f"{agg.total():.1f} hours in the {agg.key}"
                       for agg in pd.by_type(others, lambda leg: leg.aircraft)])
        role = _role_phrase(others)
        sentences.append(f"The {primary} entry includes {flown}, {role}."
                         if role else f"The {primary} entry includes {flown}.")
    return " ".join(sentences)


def _aal_dual_note(legs: Sequence[Leg], ctx: Context) -> str:
    """Time the form has no field for, named so a 0 is never read as a gap.

    PIC, SIC and instructor are the only hour fields on the entry, so hours
    flown as a student under instruction land in none of them -- a trainer
    would otherwise show 0 in every hours column with no explanation.
    """
    flown = [(agg, agg.total("dual_received"))
             for agg in pd.by_type(legs, _aal_entry)
             if agg.total("dual_received") > 0]
    if not flown:
        return ""
    listed = _join([f"{h:.1f} hours in the {_aal_type(agg.legs, ctx)}"
                    for agg, h in flown])
    return ("Time flown as a student under instruction is not one of the "
            "form's hour fields, so it is in none of the columns above: "
            f"{listed}. It is reported in full on the Application Reference "
            "sheet.")


AAL = Profile(
    target="aal",
    title="American Airlines — Aircraft Experience",
    sections=(
        Section(
            title="Aircraft (one entry per type and operating rule)",
            kind="by_type",
            group=_aal_entry,
            rows=(
                Row("AIRCRAFT TYPE", _aal_type, in_totals=False),
                Row("OPERATING RULE", distinct(_operation), in_totals=False),
                Row("PIC", whole("pic")),
                Row("SIC", whole("sic")),
                Row("INSTRUCTOR", whole("dual_given")),
                Row("LANDINGS", _aal_landings),
                Row("LAST FLOWN", last_flown("%m/%d/%Y"), in_totals=False),
                Row("NIGHT", whole("night")),
                Row("LAST 12 MO", whole_recent(12)),
                Row("LAST 24 MO", whole_recent(24)),
                Row("TYPE RATED", _type_rated, in_totals=False),
                Row("SORTIES", whole("mil_sortie")),
            ),
            notes=(
                "One entry per aircraft type and operating rule: a type flown "
                "under more than one rule is listed once for each.",
                "Hours are rounded to the nearest whole number, as the form "
                "instructs. Landings are day and night landings added together, "
                "and the sortie box is checked wherever the sortie count is not "
                "zero.",
                _aal_variant_note,
                _aal_dual_note,
                "The type-rating answer is the ratings held, which are listed in "
                "full on the first sheet; it does not depend on recent flying.",
                "Exact figures to the tenth of an hour, for every type listed "
                "here, are on the Application Reference sheet at the back.",
                SYNTHETIC_NOTE,
            ),
        ),
    ),
)


# -- generic (no carrier) ----------------------------------------------------
# The pilot's own logbook: everything every export already carries -- the
# Flight Time Summary, the three Application Reference tables and the
# certified log pages -- and no target sheet at all. A target sheet is
# shaped by one organisation's form, so a generic export has none; with no
# sections `render_profile` leaves that sheet out rather than printing an
# empty one. `title` is only the document title here.
GENERIC = Profile(
    target="generic",
    title="Pilot Logbook",
    sections=(),
)


# -- pending targets ---------------------------------------------------------
# Delta still needs its real field list from the published application before
# anything is built. Nothing is guessed here on purpose -- add a Profile once
# the form is in hand and register it below.
PENDING_TARGETS: tuple[str, ...] = ("delta",)


PROFILES: dict[str, Profile] = {
    p.target: p for p in (GENERIC, FAA, UAL, SWA, ALLEGIANT, JETBLUE, AAL)
}
TARGETS: tuple[str, ...] = tuple(PROFILES)
