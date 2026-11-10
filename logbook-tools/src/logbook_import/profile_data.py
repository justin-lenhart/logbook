"""Read-only flight data for the logbook export profiles.

One SQL read of Flights (joined to Aircraft and twice to Airports) becomes a
list of ``Leg`` rows. Everything else here is pure: predicates over a leg and
aggregators over a sequence of legs. Nothing in this module writes to Grist.

The Aircraft table is the source of truth for category / class / engine
grouping. Deadheads carry no flight time and are excluded in the query.

Historical rows (``Legacy_Summary``, the pre-2026 logbook): Night / Instrument /
Cross-Country time and the landing counts were distributed proportionally at
import. They are correct in aggregate and wrong per row, so they must never be
printed per flight (see ``docs/historical-logbook-import.md``).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone

from logbook_import.grist_client import GristClient

REMARK_PREFIX = "Logbook remark:"
# Pre-cleanup provenance preamble; still recognised so an un-migrated
# row never reports its import note as the pilot's remark.
PROVENANCE_PREFIX = "Historical line-item import"

LEGS_SQL = """
SELECT f.id                 AS id,
       f."Flight_Date"      AS flight_date,
       f."Out_Time"         AS out_time,
       f."Airline"          AS airline,
       f."Flight_Number"    AS flight_number,
       f."Tail_Number"      AS tail,
       f."Operation"        AS operation,
       f."Legacy_Summary"   AS historical,
       f."Notes"            AS notes,
       f."Block_Time"       AS block,
       f."PIC_Time"         AS pic,
       f."SIC_Time"         AS sic,
       f."SIC_to_PIC"       AS sic_to_pic,
       f."Dual_Received"    AS dual_received,
       f."Dual_Given"       AS dual_given,
       f."Night_Time"       AS night,
       f."Instrument_Time"  AS instrument,
       f."Cross_Country_Time" AS xc,
       f."Day_Landing"      AS day_landings,
       f."Night_Landing"    AS night_landings,
       f."Mil_Sortie"       AS mil_sortie,
       f."NVG_Time"         AS nvg,
       f."Combat_Time"      AS combat,
       a."Aircraft"         AS aircraft,
       a."FAA_Type"         AS faa_type,
       a."Category"         AS category,
       a."Class"            AS aircraft_class,
       a."Engine_Category"  AS engine_category,
       a."Engine_Type"      AS engine_type,
       COALESCE(NULLIF(TRIM(dep."ICAO"), ''), dep."IATA") AS origin,
       COALESCE(NULLIF(TRIM(arr."ICAO"), ''), arr."IATA") AS dest
FROM "Flights" f
LEFT JOIN "Aircraft" a   ON a.id = f."Aircraft"
LEFT JOIN "Airports" dep ON dep.id = f."Departure_Airport"
LEFT JOIN "Airports" arr ON arr.id = f."Arrival_Airport"
WHERE COALESCE(f."Deadhead", 0) = 0
ORDER BY f."Flight_Date", f."Out_Time", f.id
"""


@dataclass(frozen=True)
class Leg:
    """One loggable flight. Hours are decimal hours; missing values are 0."""

    id: int
    date: date
    aircraft: str = ""          # Aircraft table key, e.g. "AH-1Z", "CR7"
    faa_type: str = ""          # e.g. "CL65"
    category: str = ""          # Airplane / Helicopter / Powered Lift
    aircraft_class: str = ""    # Single-Engine Land / Multi-Engine Land / Rotorcraft
    engine_category: str = ""   # Turbine / Reciprocating
    engine_type: str = ""       # Turbofan / Turboprop / Turboshaft / Reciprocating
    tail: str = ""
    operation: str = ""         # Military / Part 91 / Part 121
    airline: str = ""
    flight_number: str = ""
    origin: str = ""
    dest: str = ""
    historical: bool = False    # pre-2026 logbook row: secondary hours are synthetic
    remark: str = ""           # Notes: training codes, or the pilot's own words
    # Genuine per flight
    block: float = 0.0
    pic: float = 0.0
    sic: float = 0.0
    # SIC time flown as pilot flying under a supervising PIC (14 CFR 61.51).
    # A subset of ``sic``, never overlapping ``pic`` on the same row.
    sic_to_pic: float = 0.0
    dual_received: float = 0.0
    dual_given: float = 0.0
    mil_sortie: float = 0.0
    nvg: float = 0.0
    combat: float = 0.0
    # Synthetic per flight on historical rows; aggregate use only
    night: float = 0.0
    instrument: float = 0.0
    xc: float = 0.0
    day_landings: float = 0.0
    night_landings: float = 0.0


Predicate = Callable[[Leg], bool]


# -- loading ---------------------------------------------------------------

def parse_remark(notes: str | None) -> str:
    """Pull the pilot's remark back out of Flights.Notes.

    Historical rows were imported with a ``Logbook remark: <text>`` line after
    an import-provenance preamble; that preamble has since been stripped, so
    Notes now holds the remark on its own. Both shapes are read here: a
    prefixed line wins where one exists, otherwise the whole field is the
    remark. Rows the importer writes leave Notes empty, so nothing else can be
    mistaken for a remark.
    """
    text = notes or ""
    remarks = [
        line.strip()[len(REMARK_PREFIX):].strip()
        for line in text.splitlines()
        if line.strip().startswith(REMARK_PREFIX)
    ]
    if remarks:
        return "; ".join(r for r in remarks if r)
    if PROVENANCE_PREFIX and text.lstrip().startswith(PROVENANCE_PREFIX):
        return ""                      # provenance only, no remark
    return " ".join(text.split())


def _num(value: object) -> float:
    return float(value) if isinstance(value, (int, float)) else 0.0


def _text(value: object) -> str:
    return str(value).strip() if value is not None else ""


def _date(value: object) -> date:
    """Grist stores Date columns as epoch seconds at UTC midnight."""
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc).date()
    return date.fromisoformat(str(value)[:10])


def leg_from_row(row: dict) -> Leg:
    return Leg(
        id=int(row["id"]),
        date=_date(row["flight_date"]),
        aircraft=_text(row.get("aircraft")),
        faa_type=_text(row.get("faa_type")),
        category=_text(row.get("category")),
        aircraft_class=_text(row.get("aircraft_class")),
        engine_category=_text(row.get("engine_category")),
        engine_type=_text(row.get("engine_type")),
        tail=_text(row.get("tail")),
        operation=_text(row.get("operation")),
        airline=_text(row.get("airline")),
        flight_number=_text(row.get("flight_number")),
        origin=_text(row.get("origin")),
        dest=_text(row.get("dest")),
        historical=bool(row.get("historical")),
        remark=parse_remark(row.get("notes")),
        block=_num(row.get("block")),
        pic=_num(row.get("pic")),
        sic=_num(row.get("sic")),
        sic_to_pic=_num(row.get("sic_to_pic")),
        dual_received=_num(row.get("dual_received")),
        dual_given=_num(row.get("dual_given")),
        mil_sortie=_num(row.get("mil_sortie")),
        nvg=_num(row.get("nvg")),
        combat=_num(row.get("combat")),
        night=_num(row.get("night")),
        instrument=_num(row.get("instrument")),
        xc=_num(row.get("xc")),
        day_landings=_num(row.get("day_landings")),
        night_landings=_num(row.get("night_landings")),
    )


def load_legs(client: GristClient) -> list[Leg]:
    """All non-deadhead flights, oldest first. Read-only (one SQL SELECT)."""
    rows = [r for r in client.sql(LEGS_SQL) if r.get("flight_date") is not None]
    return [leg_from_row(r) for r in rows]


# -- predicates ------------------------------------------------------------

def is_airplane(leg: Leg) -> bool:
    return leg.category == "Airplane"


def is_rotorcraft(leg: Leg) -> bool:
    return leg.category == "Helicopter"


def is_powered_lift(leg: Leg) -> bool:
    return leg.category == "Powered Lift"


def is_turbine(leg: Leg) -> bool:
    return leg.engine_category == "Turbine"


def is_jet(leg: Leg) -> bool:
    return leg.engine_type == "Turbofan"


def is_multi(leg: Leg) -> bool:
    """Multi-engine airplane (AMEL). Powered lift is its own category."""
    return is_airplane(leg) and leg.aircraft_class == "Multi-Engine Land"


def is_single(leg: Leg) -> bool:
    """Single-engine airplane (ASEL)."""
    return is_airplane(leg) and leg.aircraft_class == "Single-Engine Land"


def is_part121(leg: Leg) -> bool:
    return leg.operation == "Part 121"


def is_military(leg: Leg) -> bool:
    return leg.operation == "Military"


def is_pic(leg: Leg) -> bool:
    return leg.pic > 0


def is_sic(leg: Leg) -> bool:
    return leg.sic > 0


def never(leg: Leg) -> bool:
    """A column that is structurally empty (ASES / AMES / Gyroplane: none flown).

    Printing a real 0.0 is the honest answer on an application; it is not the
    same as "not tracked", which renders as an em dash.
    """
    return False


def all_of(*preds: Predicate) -> Predicate:
    return lambda leg: all(p(leg) for p in preds)


# -- aggregators -----------------------------------------------------------

def total(
    legs: Iterable[Leg],
    field: str = "block",
    where: Predicate | None = None,
    share: str | None = None,
) -> float:
    """Sum ``field`` over the legs matching ``where``.

    ``share`` ("pic" / "sic" / "dual_received") scales each leg's value by that
    role's fraction of the leg's block time — e.g. ``total(legs, "night",
    share="pic")`` is night PIC. Every leg is logged as exactly one role today
    (PIC + SIC + dual == block), so this is just "night on PIC legs", but the
    proportional form stays right if a leg is ever split.
    """
    values = []
    for leg in legs:
        if where is not None and not where(leg):
            continue
        value = getattr(leg, field)
        if share is not None:
            value = value * getattr(leg, share) / leg.block if leg.block else 0.0
        values.append(value)
    return math.fsum(values)


def months_before(day: date, months: int) -> date:
    """The same day-of-month ``months`` earlier (clamped to month length)."""
    index = day.year * 12 + (day.month - 1) - months
    year, month = divmod(index, 12)
    month += 1
    leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
    last = [31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1]
    return date(year, month, min(day.day, last))


def within(legs: Iterable[Leg], months: int, as_of: date) -> list[Leg]:
    """Legs flown in the ``months`` up to and including ``as_of``."""
    start = months_before(as_of, months)
    return [leg for leg in legs if start < leg.date <= as_of]


def last_flown(legs: Iterable[Leg]) -> date | None:
    return max((leg.date for leg in legs), default=None)


@dataclass(frozen=True)
class TypeAgg:
    """The legs of one aircraft grouping (key is whatever by_type grouped on)."""

    key: str
    legs: tuple[Leg, ...]

    def total(self, field: str = "block", where: Predicate | None = None,
              share: str | None = None) -> float:
        return total(self.legs, field, where, share)

    @property
    def last_flown(self) -> date | None:
        return last_flown(self.legs)


def by_type(
    legs: Sequence[Leg], key: Callable[[Leg], str] = lambda leg: leg.aircraft
) -> list[TypeAgg]:
    """Group legs by ``key`` (default: Aircraft code), most block time first."""
    groups: dict[str, list[Leg]] = {}
    for leg in legs:
        groups.setdefault(key(leg), []).append(leg)
    aggs = [TypeAgg(k, tuple(v)) for k, v in groups.items()]
    return sorted(aggs, key=lambda agg: (-agg.total(), agg.key))
