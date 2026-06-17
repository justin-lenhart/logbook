"""
Airline / FAA application reference pages.

Reads the live logbook (Flights + Aircraft), groups by application family
(see :mod:`logbook_import.app_families`), applies the SWA "x 0.3 per military
sortie" conversion, and produces structured data + HTML pages that mirror the
worksheets of the legacy AnytimeLogbook workbook closely enough to copy-paste
into the Southwest, United, and FAA/IACRA applications.

Aggregation is pure (operates on a list of normalized rows) so it can be
validated against the legacy-subset oracles without touching Airtable.
"""

from __future__ import annotations

import datetime
import html
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterable

from logbook_import import app_families as AF
from logbook_import.app_families import SORTIE_FACTOR, Family

# ── Normalization ─────────────────────────────────────────────────────────────


@dataclass
class Row:
    """A single normalized flight (legacy aggregate or live leg)."""

    family: str
    date: datetime.date | None
    is_military: bool
    is_legacy: bool
    block: float = 0.0
    pic: float = 0.0
    sic: float = 0.0
    ip: float = 0.0            # dual given (instructor)
    dual_recv: float = 0.0
    night: float = 0.0
    instrument: float = 0.0
    xc: float = 0.0
    day_ldg: int = 0
    night_ldg: int = 0


def _num(v: object) -> float:
    return float(v) if isinstance(v, (int, float)) else 0.0


def _parse_date(v: object) -> datetime.date | None:
    if isinstance(v, str) and v:
        try:
            return datetime.date.fromisoformat(v[:10])
        except ValueError:
            return None
    return None


def normalize(
    flight_records: Iterable[dict], aircraft_by_id: dict[str, str]
) -> list[Row]:
    """Turn raw Airtable Flights records into normalized rows with families.

    ``aircraft_by_id`` maps Aircraft record id -> Aircraft name.
    Simulator operations are dropped. Rows whose aircraft has no known family
    are returned with ``family=""`` so the caller can warn.
    """
    rows: list[Row] = []
    for rec in flight_records:
        f = rec.get("fields", rec)
        op = f.get("Operation")
        op_name = op.get("name") if isinstance(op, dict) else op
        if op_name == "Simulator":
            continue
        link = f.get("Aircraft") or []
        ac_id = link[0] if link else None
        ac_name = aircraft_by_id.get(ac_id) if ac_id else None
        fam = AF.family_for_aircraft(ac_name) or ""
        rows.append(
            Row(
                family=fam,
                date=_parse_date(f.get("Flight Date")),
                is_military=(op_name == "Military"),
                is_legacy=bool(f.get("Legacy Summary")),
                block=_num(f.get("Block Time")),
                pic=_num(f.get("PIC Time")),
                sic=_num(f.get("SIC Time")),
                ip=_num(f.get("Dual Given")),
                dual_recv=_num(f.get("Dual Received")),
                night=_num(f.get("Night Time")),
                instrument=_num(f.get("Instrument Time")),
                xc=_num(f.get("Cross Country Time")),
                day_ldg=int(_num(f.get("Day Landing"))),
                night_ldg=int(_num(f.get("Night Landing"))),
            )
        )
    return rows


# ── Aggregation ───────────────────────────────────────────────────────────────


@dataclass
class FamilyAgg:
    family: str
    block: float = 0.0
    pic: float = 0.0
    sic: float = 0.0          # SIC time exactly as logged (FAA sense)
    app_sic: float = 0.0      # SIC for airline apps: military non-PIC time = SIC
    ip: float = 0.0
    dual_recv: float = 0.0
    night: float = 0.0
    instrument: float = 0.0
    xc: float = 0.0
    day_ldg: int = 0
    night_ldg: int = 0
    night_ldg_pic: int = 0
    night_ldg_sic: int = 0
    mil_block: float = 0.0
    last_flown: datetime.date | None = None
    # hours bucketed by recency (months ago): keys 12/24/36/48/60/None(older)
    recency: dict[str, float] = field(default_factory=lambda: defaultdict(float))

    @property
    def meta(self) -> Family:
        return AF.FAMILIES[self.family]

    # x0.3 sortie-converted role hours (raw + factor * sorties)
    @property
    def conv_pic(self) -> float:
        return self.pic + SORTIE_FACTOR * self.meta.sorties.pic

    @property
    def conv_sic(self) -> float:
        return self.app_sic + SORTIE_FACTOR * self.meta.sorties.sic

    @property
    def conv_ip(self) -> float:
        return self.ip + SORTIE_FACTOR * self.meta.sorties.ip

    @property
    def conv_total(self) -> float:
        return self.conv_pic + self.conv_sic


def _recency_bucket(d: datetime.date | None, today: datetime.date) -> str:
    if d is None:
        return "older"
    months = (today.year - d.year) * 12 + (today.month - d.month)
    for cap in (12, 24, 36, 48, 60):
        if months <= cap:
            return str(cap)
    return "older"


def aggregate(rows: list[Row], today: datetime.date | None = None) -> dict[str, FamilyAgg]:
    today = today or datetime.date.today()
    aggs: dict[str, FamilyAgg] = {}
    for r in rows:
        if not r.family:
            continue
        a = aggs.get(r.family) or FamilyAgg(r.family)
        aggs[r.family] = a
        a.block += r.block
        a.pic += r.pic
        a.sic += r.sic
        # Airline convention: any non-PIC, non-instructor military time is SIC,
        # even where the FAA logbook recorded it as dual received (student time).
        if r.is_military:
            a.app_sic += max(r.sic, r.block - r.pic - r.ip)
        else:
            a.app_sic += r.sic
        a.ip += r.ip
        a.dual_recv += r.dual_recv
        a.night += r.night
        a.instrument += r.instrument
        a.xc += r.xc
        a.day_ldg += r.day_ldg
        a.night_ldg += r.night_ldg
        if r.pic > 0:
            a.night_ldg_pic += r.night_ldg
        elif r.sic > 0:
            a.night_ldg_sic += r.night_ldg
        if r.is_military:
            a.mil_block += r.block
        if r.date and (a.last_flown is None or r.date > a.last_flown):
            a.last_flown = r.date
        a.recency[_recency_bucket(r.date, today)] += r.block
    return aggs


def ordered(aggs: dict[str, FamilyAgg]) -> list[FamilyAgg]:
    """Families in worksheet order, then any extras, dropping empty ones."""
    seen = set()
    out: list[FamilyAgg] = []
    for code in AF.FAMILY_ORDER:
        if code in aggs:
            out.append(aggs[code])
            seen.add(code)
    for code, a in aggs.items():
        if code not in seen:
            out.append(a)
    return [a for a in out if a.block or a.pic or a.sic]


# ── Derived totals ────────────────────────────────────────────────────────────


def faa_class_code(fam: Family) -> str | None:
    if fam.faa_bucket == "Rotorcraft":
        return "Helicopter"
    if fam.faa_bucket == "Powered Lift":
        return None
    return "ASEL" if "Single" in fam.ual_class else "AMEL"


@dataclass
class Totals:
    total_time: float = 0.0
    pic: float = 0.0
    sic: float = 0.0
    app_sic: float = 0.0
    conv_pic: float = 0.0
    conv_sic: float = 0.0
    conv_total: float = 0.0
    sorties: int = 0
    fw_turbine: float = 0.0       # fixed-wing turbine block
    rotorcraft: float = 0.0       # rotorcraft block
    airplane: float = 0.0         # airplane block


def grand_totals(aggs: dict[str, FamilyAgg]) -> Totals:
    t = Totals()
    for a in aggs.values():
        m = a.meta
        t.total_time += a.block
        t.pic += a.pic
        t.sic += a.sic
        t.app_sic += a.app_sic
        t.conv_pic += a.conv_pic
        t.conv_sic += a.conv_sic
        t.sorties += m.sorties.picsic
        if m.faa_bucket == "Rotorcraft":
            t.rotorcraft += a.block
        elif m.faa_bucket == "Airplane":
            t.airplane += a.block
            if _is_turbine(m):
                t.fw_turbine += a.block
    t.conv_total = t.conv_pic + t.conv_sic
    return t


def _is_turbine(m: Family) -> bool:
    """Fixed-wing turbine = jet or turboprop airplane families."""
    if m.faa_bucket != "Airplane":
        return False
    if m.ual_powerplant == "Jet":
        return True
    # Turboprops in this fleet: UC-12W and T-6B.
    return m.code in {"UC12W", "T6"}


# ── HTML rendering ────────────────────────────────────────────────────────────

_CSS = """
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
body { font: 14px/1.45 -apple-system, system-ui, sans-serif; margin: 0; padding: 1.25rem;
       color: #1a1a1a; background: #fff; }
h1 { font-size: 1.35rem; margin: 0 0 .15rem; }
h2 { font-size: 1.05rem; margin: 1.5rem 0 .5rem; border-bottom: 2px solid #0a6; padding-bottom: .2rem; }
.sub { color: #666; margin: 0 0 1rem; font-size: .85rem; }
table { border-collapse: collapse; width: 100%; margin: .25rem 0 1rem; font-variant-numeric: tabular-nums; }
th, td { padding: .3rem .55rem; text-align: right; border-bottom: 1px solid #e3e3e3; }
th:first-child, td:first-child { text-align: left; }
thead th { background: #f4f7f6; border-bottom: 2px solid #0a6; font-weight: 600; }
tr.total td { font-weight: 700; border-top: 2px solid #0a6; background: #f4f7f6; }
.note { color: #888; font-size: .8rem; font-style: italic; }
.warn { color: #b30; }
"""


def _esc(s: object) -> str:
    return html.escape(str(s))


def _h(x: float) -> str:
    return f"{x:.1f}"


def _doc(title: str, body: str, generated: str) -> str:
    return (
        f"<!doctype html><html lang=en><head><meta charset=utf-8>"
        f"<meta name=viewport content='width=device-width, initial-scale=1'>"
        f"<title>{_esc(title)}</title><style>{_CSS}</style></head><body>"
        f"<h1>{_esc(title)}</h1>"
        f"<p class=sub>Generated {generated} from the live Airtable logbook · "
        f"copy-paste reference for pilot-hours sections</p>"
        f"{body}"
        f"<p class=note>Military rotary/tilt-rotor time uses the standard "
        f"0.3-hour-per-sortie conversion where shown. Figures are generated "
        f"directly from logbook records; verify against your official logbook "
        f"before certifying any application.</p>"
        f"</body></html>"
    )


def render_swa(aggs: dict[str, FamilyAgg], generated: str) -> str:
    fams = ordered(aggs)
    rows = []
    for a in fams:
        m = a.meta
        s = m.sorties
        rows.append(
            f"<tr><td>{_esc(m.label)}</td>"
            f"<td>{_h(a.pic)}</td><td>{s.pic or ''}</td><td>{_h(a.conv_pic)}</td>"
            f"<td>{_h(a.app_sic)}</td><td>{s.sic or ''}</td><td>{_h(a.conv_sic)}</td>"
            f"<td>{_h(a.ip)}</td><td>{s.ip or ''}</td><td>{_h(a.conv_ip)}</td>"
            f"<td>{a.last_flown or ''}</td></tr>"
        )
    t = grand_totals(aggs)
    raw_picsic = sum(a.pic + a.app_sic for a in fams)
    rows.append(
        f"<tr class=total><td>TOTAL</td>"
        f"<td>{_h(t.pic)}</td><td>{sum(a.meta.sorties.pic for a in fams)}</td><td>{_h(t.conv_pic)}</td>"
        f"<td>{_h(sum(a.app_sic for a in fams))}</td><td>{sum(a.meta.sorties.sic for a in fams)}</td><td>{_h(t.conv_sic)}</td>"
        f"<td>{_h(sum(a.ip for a in fams))}</td><td>{sum(a.meta.sorties.ip for a in fams)}</td>"
        f"<td>{_h(sum(a.conv_ip for a in fams))}</td><td></td></tr>"
    )
    by_cat = _swa_categories(aggs)
    cat_rows = "".join(
        f"<tr><td>{_esc(c)}</td><td>{_h(p)}</td><td>{_h(s)}</td></tr>"
        for c, (p, s) in by_cat
    )
    cur_rows = _currency_rows(fams)
    body = (
        "<h2>Flight Hours by Aircraft (PIC / SIC / Instructor)</h2>"
        "<table><thead><tr><th>Aircraft</th>"
        "<th>PIC</th><th>Mil&nbsp;Sorties</th><th>PIC&nbsp;×0.3</th>"
        "<th>SIC</th><th>Mil&nbsp;Sorties</th><th>SIC&nbsp;×0.3</th>"
        "<th>Instr</th><th>Sorties</th><th>Instr&nbsp;×0.3</th>"
        "<th>Last&nbsp;Flown</th></tr></thead><tbody>"
        + "".join(rows) + "</tbody></table>"
        f"<p class=sub><b>Total flying time (PIC+SIC) with conversion: "
        f"{_h(t.conv_total)}</b> &nbsp;·&nbsp; raw {_h(raw_picsic)} + "
        f"{t.sorties} sorties × {SORTIE_FACTOR}</p>"
        "<h2>Aircraft Category Totals</h2>"
        "<table><thead><tr><th>Category</th><th>PIC</th><th>SIC</th></tr></thead>"
        f"<tbody>{cat_rows}</tbody></table>"
        "<h2>Verification of Currency (block hours by recency)</h2>"
        "<table><thead><tr><th>Aircraft</th><th>0–12&nbsp;mo</th><th>13–24</th>"
        "<th>25–36</th><th>37–48</th><th>49–60</th><th>Older</th></tr></thead>"
        f"<tbody>{cur_rows}</tbody></table>"
    )
    return _doc("Southwest Airlines — Pilot Hours", body, generated)


def _swa_categories(aggs: dict[str, FamilyAgg]) -> list[tuple[str, tuple[float, float]]]:
    acc: dict[str, list[float]] = {c: [0.0, 0.0] for c in AF.SWA_CATEGORIES}
    for a in aggs.values():
        acc[a.meta.swa_category][0] += a.pic
        acc[a.meta.swa_category][1] += a.app_sic
    return [(c, (p, s)) for c, (p, s) in ((c, acc[c]) for c in AF.SWA_CATEGORIES) if p or s]


def _currency_rows(fams: list[FamilyAgg]) -> str:
    out = []
    for a in fams:
        r = a.recency
        out.append(
            f"<tr><td>{_esc(a.meta.label)}</td>"
            f"<td>{_h(r.get('12',0))}</td><td>{_h(r.get('24',0))}</td>"
            f"<td>{_h(r.get('36',0))}</td><td>{_h(r.get('48',0))}</td>"
            f"<td>{_h(r.get('60',0))}</td><td>{_h(r.get('older',0))}</td></tr>"
        )
    return "".join(out)


def render_ual(aggs: dict[str, FamilyAgg], generated: str) -> str:
    civ, mil = [], []
    for a in ordered(aggs):
        m = a.meta
        row = (
            f"<tr><td>{_esc(m.ual_mfr)}</td><td>{_esc(m.ual_model)}</td>"
            f"<td>{_esc(m.ual_class)}</td><td>{_esc(m.ual_powerplant)}</td>"
            f"<td>{'Yes' if m.ual_type_rated else 'No'}</td>"
            f"<td>{_h(a.pic)}</td><td>{_h(a.sic)}</td><td>{_h(a.ip)}</td>"
            f"<td>{_h(a.dual_recv)}</td><td>{a.last_flown or ''}</td></tr>"
        )
        (mil if a.mil_block > 0 else civ).append(row)
    head = (
        "<thead><tr><th>Manufacturer</th><th>Model</th><th>Class</th>"
        "<th>Powerplant</th><th>Type&nbsp;Rated</th><th>PIC</th><th>SIC</th>"
        "<th>Instructor</th><th>Instr&nbsp;Recv</th><th>Last&nbsp;Flown</th></tr></thead>"
    )
    body = (
        "<p class=sub>United enters flight time per aircraft, split into civilian "
        "and military sections. Values below are raw logged hours (no sortie "
        "conversion — United does not apply one).</p>"
        "<h2>Civilian Flight Time</h2>"
        f"<table>{head}<tbody>{''.join(civ) or '<tr><td colspan=10 class=note>None</td></tr>'}</tbody></table>"
        "<h2>Military Flight Time</h2>"
        f"<table>{head}<tbody>{''.join(mil) or '<tr><td colspan=10 class=note>None</td></tr>'}</tbody></table>"
    )
    return _doc("United Airlines — Pilot Hours", body, generated)


def render_faa(aggs: dict[str, FamilyAgg], generated: str) -> str:
    buckets = {"Airplane": [], "Rotorcraft": [], "Powered Lift": []}
    for a in aggs.values():
        buckets.setdefault(a.meta.faa_bucket, []).append(a)

    def col(metric) -> str:
        cells = []
        for b in ("Airplane", "Rotorcraft", "Powered Lift"):
            cells.append(f"<td>{_h(sum(metric(a) for a in buckets.get(b, [])))}</td>")
        return "".join(cells)

    metrics = [
        ("Total Hours", lambda a: a.block),
        ("Instruction Received", lambda a: a.dual_recv),
        ("Pilot in Command (PIC)", lambda a: a.pic),
        ("Second in Command (SIC)", lambda a: a.sic),
        ("Instructor (Dual Given)", lambda a: a.ip),
        ("Cross Country", lambda a: a.xc),
        ("Instrument", lambda a: a.instrument),
        ("Night", lambda a: a.night),
        ("Night Takeoff/Landings", lambda a: a.night_ldg),
        ("Night T/O Landing PIC", lambda a: a.night_ldg_pic),
        ("Night T/O Landing SIC", lambda a: a.night_ldg_sic),
    ]
    body_rows = "".join(
        f"<tr><td>{_esc(label)}</td>{col(fn)}</tr>" for label, fn in metrics
    )

    # Class-hours breakdown (ASEL/AMEL/Helicopter PIC & SIC).
    cls: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
    for a in aggs.values():
        c = faa_class_code(a.meta)
        if c:
            cls[c][0] += a.pic
            cls[c][1] += a.sic
    class_rows = "".join(
        f"<tr><td>{_esc(c)}</td><td>{_h(cls[c][0])}</td><td>{_h(cls[c][1])}</td></tr>"
        for c in ("ASEL", "AMEL", "Helicopter")
        if c in cls
    )
    body = (
        "<p class=sub>FAA Form 8710 / IACRA Section III — Airplane, Rotorcraft, "
        "and Powered-Lift hours. Raw logged time (FAA does not use sortie "
        "conversion).</p>"
        "<h2>Hours by Category</h2>"
        "<table><thead><tr><th>Metric</th><th>Airplane</th><th>Rotorcraft</th>"
        "<th>Powered&nbsp;Lift</th></tr></thead><tbody>"
        f"{body_rows}</tbody></table>"
        "<h2>Class Hours (PIC / SIC)</h2>"
        "<table><thead><tr><th>Class</th><th>PIC</th><th>SIC</th></tr></thead>"
        f"<tbody>{class_rows}</tbody></table>"
    )
    return _doc("FAA / IACRA — Pilot Time (Section III)", body, generated)


def render_summary(aggs: dict[str, FamilyAgg], generated: str) -> str:
    t = grand_totals(aggs)
    fams = ordered(aggs)
    rows = "".join(
        f"<tr><td>{_esc(a.meta.label)}</td><td>{_h(a.block)}</td>"
        f"<td>{_h(a.pic)}</td><td>{_h(a.sic)}</td><td>{_h(a.night)}</td>"
        f"<td>{_h(a.instrument)}</td><td>{_h(a.xc)}</td>"
        f"<td>{a.day_ldg + a.night_ldg}</td></tr>"
        for a in fams
    )

    def milestone(label: str, have: float, need: float) -> str:
        done = have >= need
        pct = min(100, 100 * have / need) if need else 100
        mark = "✅" if done else f"{pct:.0f}%"
        return (
            f"<tr><td>{_esc(label)}</td><td>{_h(have)}</td><td>{_h(need)}</td>"
            f"<td>{mark}</td></tr>"
        )

    fw_pic = sum(a.pic for a in fams if a.meta.faa_bucket == "Airplane")
    fw_turb_pic = sum(
        a.pic for a in fams if a.meta.faa_bucket == "Airplane" and _is_turbine(a.meta)
    )
    body = (
        "<h2>Totals by Aircraft</h2>"
        "<table><thead><tr><th>Aircraft</th><th>Total</th><th>PIC</th><th>SIC</th>"
        "<th>Night</th><th>Instr</th><th>XC</th><th>Ldgs</th></tr></thead>"
        f"<tbody>{rows}<tr class=total><td>TOTAL</td><td>{_h(t.total_time)}</td>"
        f"<td>{_h(t.pic)}</td><td>{_h(t.sic)}</td>"
        f"<td>{_h(sum(a.night for a in fams))}</td>"
        f"<td>{_h(sum(a.instrument for a in fams))}</td>"
        f"<td>{_h(sum(a.xc for a in fams))}</td>"
        f"<td>{sum(a.day_ldg + a.night_ldg for a in fams)}</td></tr></tbody></table>"
        "<h2>Headline Numbers</h2>"
        "<table><tbody>"
        f"<tr><td>Total Time</td><td>{_h(t.total_time)}</td></tr>"
        f"<tr><td>Total PIC</td><td>{_h(t.pic)}</td></tr>"
        f"<tr><td>Fixed-Wing Turbine</td><td>{_h(t.fw_turbine)}</td></tr>"
        f"<tr><td>Fixed-Wing Turbine PIC</td><td>{_h(fw_turb_pic)}</td></tr>"
        f"<tr><td>Rotorcraft</td><td>{_h(t.rotorcraft)}</td></tr>"
        f"<tr><td>Airplane</td><td>{_h(t.airplane)}</td></tr>"
        "</tbody></table>"
        "<h2>Milestones</h2>"
        "<table><thead><tr><th>Milestone</th><th>Have</th><th>Need</th><th>Status</th>"
        "</tr></thead><tbody>"
        + milestone("1000 hr Fixed-Wing Turbine PIC", fw_turb_pic, 1000)
        + milestone("1500 hr Total Turbine", t.fw_turbine + t.rotorcraft, 1500)
        + milestone("1000 hr Fixed-Wing Turbine", t.fw_turbine, 1000)
        + "</tbody></table>"
    )
    return _doc("Flight Time Summary & Milestones", body, generated)


RENDERERS = {
    "swa": render_swa,
    "ual": render_ual,
    "faa": render_faa,
    "summary": render_summary,
}
