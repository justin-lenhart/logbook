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


def milestone(target: int, field: str, where: Predicate) -> Metric:
    def metric(legs: Sequence[Leg], ctx: Context) -> str:
        have = pd.total(legs, field, where)
        if have >= target:
            return f"{have:.1f} of {target} — met"
        return f"{have:.1f} of {target} — {target - have:.1f} to go"
    return metric


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
    "AH1-W":  ("AH-1W",  "Bell",        "AH-1W Super Cobra"),
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
        title="Milestones",
        kind="metrics",
        rows=(
            Row("1000 FW Turbine PIC", milestone(1000, "pic", _FW_TURBINE)),
            Row("1500 Turbine", milestone(1500, "block", pd.is_turbine)),
            Row("1000 FW Turbine", milestone(1000, "block", _FW_TURBINE)),
        ),
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
            title="Class Hours",
            kind="matrix",
            columns=_ALL,
            rows=(
                Row("ASEL PIC", hours("pic", pd.is_single)),
                Row("ASES PIC", zero),
                Row("AMEL PIC", hours("pic", pd.is_multi)),
                Row("AMES PIC", zero),
                Row("ASEL SIC", hours("sic", pd.is_single)),
                Row("ASES SIC", zero),
                Row("AMEL SIC", hours("sic", pd.is_multi)),
                Row("AMES SIC", zero),
                Row("Helicopter", hours(where=pd.is_rotorcraft)),
                Row("Gyroplane", zero),
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


PROFILES: dict[str, Profile] = {p.target: p for p in (FAA, UAL, SWA)}
TARGETS: tuple[str, ...] = tuple(PROFILES)
