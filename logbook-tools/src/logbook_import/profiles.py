"""Export profiles: what each target (FAA 8710, United, Southwest) wants to see.

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

import tomllib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
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
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class Profile:
    target: str
    title: str
    sections: tuple[Section, ...]


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


# -- pending targets ---------------------------------------------------------
# JetBlue (the pilot's first priority) and Delta: both need their real field
# lists from the published applications before anything is built. JetBlue will
# use the SIC-to-PIC column. Nothing is guessed here on purpose -- add a
# Profile for each once the form is in hand and register it below.
PENDING_TARGETS: tuple[str, ...] = ("jetblue", "delta")


PROFILES: dict[str, Profile] = {p.target: p for p in (FAA, UAL, SWA, ALLEGIANT)}
TARGETS: tuple[str, ...] = tuple(PROFILES)
