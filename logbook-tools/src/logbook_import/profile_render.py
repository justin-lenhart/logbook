"""HTML rendering for the logbook export profiles (print-first, no dependencies).

One document per export: the summary page, the target's own sections, then the
certified log pages. Print CSS puts the summary/target sheets on portrait
letter and the log pages on landscape letter (named ``@page``).

The certified log pages print only values that are genuine per flight. Night,
instrument, cross-country and landings are synthetic on the pre-2026 rows
(correct in aggregate only), so those columns do not exist here at all.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from html import escape

from logbook_import import profile_data as pd
from logbook_import.profile_data import Leg
from logbook_import.profiles import (
    SUMMARY_SECTIONS,
    SYNTHETIC_NOTE,
    Context,
    Profile,
    Row,
    Section,
    Value,
)

LOG_ROWS_PER_PAGE = 50
CERTIFICATION = "I certify that the entries in this log are true."
SIGNATURE_LINE = "_" * 25


def fmt(value: Value) -> str:
    """Display text for a metric value. ``None`` means "not tracked"."""
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, float):
        return f"{value + 0.0:.1f}".replace("-0.0", "0.0")
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _is_number(value: Value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _cell(value: Value, tag: str = "td") -> str:
    cls = ' class="num"' if _is_number(value) or value is None else ""
    return f"<{tag}{cls}>{escape(fmt(value))}</{tag}>"


def _notes(notes: Sequence[str]) -> str:
    return "".join(f'<p class="note">{escape(n)}</p>' for n in notes)


# -- sections ---------------------------------------------------------------

def _render_metrics(section: Section, legs: Sequence[Leg], ctx: Context) -> str:
    tiles = "".join(
        f'<div class="metric"><div class="lbl">{escape(row.label)}</div>'
        f'<div class="val">{escape(fmt(row.value(legs, ctx)))}</div></div>'
        for row in section.rows
    )
    return f'<div class="metrics">{tiles}</div>'


def _render_matrix(section: Section, legs: Sequence[Leg], ctx: Context) -> str:
    column_legs = [[leg for leg in legs if col.where(leg)] for col in section.columns]
    head = "".join(f"<th>{escape(col.label)}</th>" for col in section.columns)
    body = "".join(
        f"<tr><th>{escape(row.label)}</th>"
        + "".join(_cell(row.value(subset, ctx)) for subset in column_legs)
        + "</tr>"
        for row in section.rows
    )
    return (f'<table class="matrix"><thead><tr><th></th>{head}</tr></thead>'
            f"<tbody>{body}</tbody></table>")


def _group_header(rows: Sequence[Row]) -> str:
    """A heading row spanning each run of columns that share a group."""
    if not any(row.group for row in rows):
        return ""
    cells, run, span = [], None, 0
    for row in rows:
        if row.group == run:
            span += 1
            continue
        if run is not None:
            cells.append(f'<th colspan="{span}">{escape(run)}</th>')
        run, span = row.group, 1
    cells.append(f'<th colspan="{span}">{escape(run or "")}</th>')
    return f'<tr class="groups"><th></th>{"".join(cells)}</tr>'


def _render_by_type(section: Section, legs: Sequence[Leg], ctx: Context) -> str:
    head = "".join(f"<th>{escape(row.label)}</th>" for row in section.rows)
    body = "".join(
        f"<tr><th>{escape(agg.key or '(no aircraft)')}</th>"
        + "".join(_cell(row.value(agg.legs, ctx)) for row in section.rows)
        + "</tr>"
        for agg in pd.by_type(legs, section.group)
    )
    foot = ""
    if section.totals:
        foot = ("<tfoot><tr><th>TOTAL</th>"
                + "".join(_cell(row.value(legs, ctx)) for row in section.rows)
                + "</tr></tfoot>")
    return (f'<table class="by-type"><thead>{_group_header(section.rows)}'
            f"<tr><th>TYPE</th>{head}</tr></thead><tbody>{body}</tbody>{foot}</table>")


def _render_form(section: Section, legs: Sequence[Leg], ctx: Context) -> str:
    width = max(len(cells) for cells in section.form)
    blocks = []
    for agg in pd.by_type(legs, section.group):
        trs = []
        for cells in section.form:
            tds = "".join(
                f'<td><div class="lbl">{escape(cell.label)}</div>'
                f'<div class="val">{escape(fmt(cell.value(agg.legs, ctx)))}</div></td>'
                for cell in cells
            )
            if len(cells) < width:
                tds += f'<td class="empty" colspan="{width - len(cells)}"></td>'
            trs.append(f"<tr>{tds}</tr>")
        blocks.append(f'<table class="form">{"".join(trs)}</table>')
    return "".join(blocks)


_RENDERERS: dict[str, Callable[[Section, Sequence[Leg], Context], str]] = {
    "metrics": _render_metrics,
    "matrix": _render_matrix,
    "by_type": _render_by_type,
    "per_aircraft_form": _render_form,
}


def render_section(section: Section, legs: Sequence[Leg], ctx: Context) -> str:
    body = _RENDERERS[section.kind](section, legs, ctx)
    return (f'<section class="section {section.kind}"><h2>{escape(section.title)}</h2>'
            f"{body}{_notes(section.notes)}</section>")


# -- certified log pages ----------------------------------------------------

@dataclass(frozen=True)
class LogColumn:
    group: str
    label: str
    value: Callable[[Leg], float | str]
    kind: str = "hours"      # hours | count | text


def _when(pred: pd.Predicate) -> Callable[[Leg], float]:
    return lambda leg: leg.block if pred(leg) else 0.0


def _route(leg: Leg) -> str:
    return "-".join(p for p in (leg.origin, leg.dest) if p)


def _remark(leg: Leg) -> str:
    return leg.remark or " ".join(p for p in (leg.airline, leg.flight_number) if p)


# Deliberately absent: landings, NT, ACT IN, XC (synthetic before 2026) and
# SIM IN, APP, SOLO, the PIC AC/PF split, SPEC CREW, TRAPS (not tracked).
LOG_COLUMNS: tuple[LogColumn, ...] = (
    LogColumn("GENERAL INFORMATION", "DATE", lambda leg: leg.date.isoformat(), "text"),
    LogColumn("GENERAL INFORMATION", "TYPE", lambda leg: leg.aircraft, "text"),
    LogColumn("GENERAL INFORMATION", "IDENT", lambda leg: leg.tail, "text"),
    LogColumn("ROUTE", "ROUTE", _route, "text"),
    LogColumn("TOTAL", "TOTAL", lambda leg: leg.block),
    LogColumn("CAT / CLASS", "ASEL", _when(pd.is_single)),
    LogColumn("CAT / CLASS", "AMEL", _when(pd.is_multi)),
    LogColumn("CAT / CLASS", "ASES", lambda leg: 0.0),
    LogColumn("CAT / CLASS", "AMES", lambda leg: 0.0),
    LogColumn("CAT / CLASS", "HELO", _when(pd.is_rotorcraft)),
    LogColumn("CAT / CLASS", "LIFT", _when(pd.is_powered_lift)),
    LogColumn("CAT / CLASS", "GLIDE", lambda leg: 0.0),
    LogColumn("TYPE OF PILOTING TIME", "PIC", lambda leg: leg.pic),
    LogColumn("TYPE OF PILOTING TIME", "SIC", lambda leg: leg.sic),
    LogColumn("TYPE OF PILOTING TIME", "DUAL", lambda leg: leg.dual_received),
    LogColumn("TYPE OF PILOTING TIME", "IP/CFI", lambda leg: leg.dual_given),
    LogColumn("MILITARY", "MIL SORTIE", lambda leg: leg.mil_sortie, "count"),
    LogColumn("MILITARY", "NVG", lambda leg: leg.nvg),
    LogColumn("MILITARY", "COMBAT", lambda leg: leg.combat),
    LogColumn("REMARKS", "REMARKS", _remark, "text"),
)
_FIRST_SUM = next(i for i, col in enumerate(LOG_COLUMNS) if col.kind != "text")


def _units(col: LogColumn, leg: Leg) -> int:
    """A summable cell as an integer (tenths of an hour, or a plain count), so
    page totals and the carry-forward add up exactly as printed."""
    value = col.value(leg)
    return round(value * 10) if col.kind == "hours" else round(value)  # type: ignore[operator]


def _show(col: LogColumn, units: int, blank_zero: bool) -> str:
    if blank_zero and units == 0:
        return ""
    return f"{units / 10:.1f}" if col.kind == "hours" else str(units)


@dataclass(frozen=True)
class LogPage:
    number: int
    legs: tuple[Leg, ...]
    page_totals: tuple[int, ...]     # one per LOG_COLUMNS entry (0 for text)
    forwarded: tuple[int, ...]
    to_date: tuple[int, ...]


def paginate_log(legs: Sequence[Leg], per_page: int = LOG_ROWS_PER_PAGE) -> list[LogPage]:
    """Split the legs (already oldest-first) into pages with running totals."""
    pages: list[LogPage] = []
    forwarded = tuple(0 for _ in LOG_COLUMNS)
    for start in range(0, len(legs), per_page):
        chunk = tuple(legs[start:start + per_page])
        totals = tuple(
            0 if col.kind == "text" else sum(_units(col, leg) for leg in chunk)
            for col in LOG_COLUMNS
        )
        to_date = tuple(a + b for a, b in zip(forwarded, totals))
        pages.append(LogPage(len(pages) + 1, chunk, totals, forwarded, to_date))
        forwarded = to_date
    return pages


def _log_header(title: str) -> str:
    groups, labels = [], []
    index = 0
    while index < len(LOG_COLUMNS):
        col = LOG_COLUMNS[index]
        span = sum(1 for c in LOG_COLUMNS if c.group == col.group)
        if span == 1:
            groups.append(f'<th rowspan="2">{escape(col.group)}</th>')
        else:
            groups.append(f'<th colspan="{span}">{escape(col.group)}</th>')
            labels += [f"<th>{escape(c.label)}</th>" for c in LOG_COLUMNS[index:index + span]]
        index += span
    return (f'<thead><tr class="banner"><th colspan="{len(LOG_COLUMNS)}">{title}</th></tr>'
            f'<tr>{"".join(groups)}</tr><tr>{"".join(labels)}</tr></thead>')


def _log_colgroup() -> str:
    return "<colgroup>" + "".join(
        f'<col class="c-{col.label.lower().replace(" ", "-").replace("/", "-")}">'
        for col in LOG_COLUMNS
    ) + "</colgroup>"


def _log_row(leg: Leg) -> str:
    cells = []
    for col in LOG_COLUMNS:
        if col.kind == "text":
            cells.append(f"<td>{escape(str(col.value(leg)))}</td>")
        else:
            cells.append(f'<td class="num">{_show(col, _units(col, leg), True)}</td>')
    return f'<tr>{"".join(cells)}</tr>'


def _log_footer(page: LogPage, pilot_name: str) -> str:
    certify = (f'<td class="certify" rowspan="3"><div>{escape(CERTIFICATION)}</div>'
               f"<div>{SIGNATURE_LINE}</div><div>{escape(pilot_name)}</div></td>")
    rows = []
    for label, sums in (("TOTALS THIS PAGE", page.page_totals),
                        ("AMT. FORWARDED", page.forwarded),
                        ("TOTALS TO DATE", page.to_date)):
        cells = "".join(
            f'<td class="num">{_show(col, sums[i], False)}</td>'
            for i, col in enumerate(LOG_COLUMNS) if col.kind != "text"
        )
        rows.append(f'<tr><th colspan="{_FIRST_SUM}">{label}</th>{cells}'
                    f'{certify if not rows else ""}</tr>')
    return f'<tfoot>{"".join(rows)}</tfoot>'


def render_log_pages(legs: Sequence[Leg], ctx: Context) -> str:
    pages = paginate_log(legs)
    name = ctx.pilot.name
    blank = "<tr>" + "<td></td>" * len(LOG_COLUMNS) + "</tr>"
    out = []
    for page in pages:
        title = (f'<span>PILOT LOGBOOK{" — " + escape(name) if name else ""}</span>'
                 f"<span>Page {page.number} of {len(pages)}</span>")
        body = "".join(_log_row(leg) for leg in page.legs)
        body += blank * (LOG_ROWS_PER_PAGE - len(page.legs))
        out.append(
            f'<section class="log-page"><table class="log">{_log_colgroup()}'
            f"{_log_header(title)}<tbody>{body}</tbody>{_log_footer(page, name)}</table>"
            f'<p class="note">{escape(SYNTHETIC_NOTE)}</p></section>'
        )
    return "".join(out)


# -- document ---------------------------------------------------------------

CSS = """
@page { size: letter portrait; margin: 0.5in; }
@page log { size: letter landscape; margin: 0.3in; }
* { box-sizing: border-box; }
body { margin: 0; color: #111; background: #fff;
       font: 9pt/1.35 "Helvetica Neue", Helvetica, Arial, sans-serif; }
h1 { font-size: 15pt; margin: 0; }
h2 { font-size: 10.5pt; margin: 14pt 0 5pt; padding-bottom: 2pt; border-bottom: 1.2pt solid #111;
     break-after: avoid; }
table { border-collapse: collapse; width: 100%; }
thead { display: table-header-group; }
tfoot { display: table-row-group; }
tr, .metric, table.form, .identity { break-inside: avoid; }
th, td { border: 0.5pt solid #777; padding: 2pt 4pt; text-align: left; }
thead th, tfoot th, tfoot td { background: #eee; }
td.num, tfoot td { text-align: right; font-variant-numeric: tabular-nums; }
.note { font-size: 7.5pt; color: #444; margin: 4pt 0 0; }
.sheet { break-after: page; padding: 0; }
.identity { display: flex; justify-content: space-between; align-items: flex-end;
            border-bottom: 2pt solid #111; padding-bottom: 6pt; }
.identity .sub { font-size: 11pt; }
.identity .meta { text-align: right; font-size: 8pt; }
.metrics { display: grid; grid-template-columns: repeat(3, 1fr); gap: 6pt; }
.metric { border: 0.5pt solid #777; padding: 5pt 7pt; }
.lbl { font-size: 7pt; text-transform: uppercase; letter-spacing: 0.04em; color: #444; }
.val { font-size: 12pt; font-weight: 600; font-variant-numeric: tabular-nums; min-height: 1.35em; }
table.matrix th:first-child { width: 46%; font-weight: 500; }
table.matrix thead th, table.by-type thead th { text-align: center; }
table.matrix td { text-align: right; }
table.by-type { font-size: 7pt; }
table.by-type th, table.by-type td { padding: 2pt 2.5pt; }
table.form { margin: 0 0 9pt; table-layout: fixed; }
table.form .val { font-size: 10.5pt; }
table.form td.empty { border: 0; }

.log-page { page: log; break-after: page; }
table.log { table-layout: fixed; font-size: 6.4pt; line-height: 9pt; }
table.log th, table.log td { padding: 0 2pt; height: 9pt; overflow: hidden;
                             white-space: nowrap; text-overflow: ellipsis; }
table.log thead th { text-align: center; font-size: 5.6pt; padding: 0 1pt; }
table.log tr.banner th { font-size: 7pt; background: #fff; border-width: 0 0 0.5pt; }
table.log tr.banner th span:first-child { float: left; }
table.log tr.banner th span:last-child { float: right; }
table.log tfoot th { text-align: right; font-size: 5.8pt; }
table.log tfoot td { font-weight: 600; }
table.log td.certify { text-align: center; font-weight: 400; font-size: 5.8pt;
                       white-space: normal; background: #fff; }
table.log td.certify div { height: 9pt; white-space: nowrap; }
.log-page .note { font-size: 5.6pt; margin-top: 2pt; }
col.c-date { width: 0.56in; } col.c-type { width: 0.5in; } col.c-ident { width: 0.55in; }
col.c-route { width: 0.78in; } col.c-total { width: 0.42in; }
col.c-asel, col.c-amel, col.c-ases, col.c-ames, col.c-helo, col.c-lift, col.c-glide { width: 0.36in; }
col.c-pic, col.c-sic, col.c-dual, col.c-ip-cfi { width: 0.4in; }
col.c-mil-sortie { width: 0.5in; } col.c-nvg, col.c-combat { width: 0.42in; }

@media screen {
  body { background: #d8d8d8; }
  .sheet, .log-page { background: #fff; margin: 16px auto; padding: 0.5in;
                      box-shadow: 0 1px 4px rgba(0,0,0,.3); }
  .sheet { width: 8.5in; min-height: 11in; }
  .log-page { width: 11in; min-height: 8.5in; padding: 0.3in; }
}
"""


def _identity(legs: Sequence[Leg], ctx: Context, subtitle: str) -> str:
    pilot = ctx.pilot
    span = f"{legs[0].date.isoformat()} to {legs[-1].date.isoformat()}" if legs else ""
    cert = " ".join(p for p in (pilot.certificate, pilot.certificate_number) if p)
    meta = [span, cert, ", ".join(pilot.ratings),
            ("Type ratings: " + ", ".join(pilot.type_ratings)) if pilot.type_ratings else "",
            f"As of {ctx.as_of.isoformat()}"]
    return (f'<header class="identity"><div><h1>{escape(pilot.name or "Pilot")}</h1>'
            f'<div class="sub">{escape(subtitle)}</div></div><div class="meta">'
            + "".join(f"<div>{escape(m)}</div>" for m in meta if m)
            + "</div></header>")


def render_profile(profile: Profile, legs: Sequence[Leg], ctx: Context,
                   include_log: bool = True) -> str:
    """The whole export as one self-contained HTML document."""
    summary = _identity(legs, ctx, "Flight Time Summary") + "".join(
        render_section(s, legs, ctx) for s in SUMMARY_SECTIONS)
    target = _identity(legs, ctx, profile.title) + "".join(
        render_section(s, legs, ctx) for s in profile.sections)
    log = render_log_pages(legs, ctx) if include_log else ""
    title = escape(f"{ctx.pilot.name or 'Pilot'} — {profile.title}")
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        f"<title>{title}</title><style>{CSS}</style></head><body>"
        f'<section class="sheet">{summary}</section>'
        f'<section class="sheet">{target}</section>{log}</body></html>\n'
    )
