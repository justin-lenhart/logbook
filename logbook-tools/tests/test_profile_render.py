"""Profiles + rendering: FAA matrix, carrier forms, certified log pages, CLI."""

from __future__ import annotations

import re
from datetime import date, timedelta

import pytest
from click.testing import CliRunner

from logbook_import import cli, profiles
from logbook_import import profile_render as render
from logbook_import.profile_data import Leg
from logbook_import.profiles import FAA, SWA, UAL, Context, Pilot
from test_profile_data import COBRA, CRJ, OSPREY, SKYHAWK, leg

PILOT = Pilot(name="Pat <Test> Pilot", certificate="ATP", certificate_number="123",
              ratings=("AMEL",), type_ratings=("CL65",))
CTX = Context(as_of=date(2026, 11, 3), pilot=PILOT)


@pytest.fixture
def legs() -> list[Leg]:
    return [
        leg(1, "2015-03-01", SKYHAWK, block=1.0, dual_received=1.0, xc=0.5,
            night=0.2, remark="IFS, 5R4"),
        leg(2, "2019-06-01", COBRA, block=2.0, pic=2.0, night=1.0, nvg=1.0,
            mil_sortie=1, combat=2.0, night_landings=2, dual_given=2.0,
            instrument=0.3, day_landings=4, tail="168001"),
        leg(3, "2020-06-01", COBRA, block=1.5, sic=1.5, mil_sortie=1, night_landings=1),
        leg(4, "2021-01-01", OSPREY, block=0.6, sic=0.6, mil_sortie=1),
        leg(5, "2026-05-10", {**CRJ, "aircraft": "CR2"}, block=2.2, sic=2.2, night=0.4,
            xc=2.2, origin="KORD", dest="KSGF", airline="SKW", flight_number="5852"),
        leg(6, "2026-11-01", CRJ, block=1.8, sic=1.8, xc=1.8, night_landings=1),
    ]


def section(profile: profiles.Profile, title: str) -> profiles.Section:
    return next(s for s in profile.sections if s.title == title)


def matrix(sec: profiles.Section, legs: list[Leg]) -> dict[str, list]:
    return {
        row.label: [row.value([l for l in legs if col.where(l)], CTX)
                    for col in sec.columns]
        for row in sec.rows
    }


def cells(html: str) -> list[str]:
    return [re.sub(r"<[^>]+>", "", c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", html)]


# -- FAA 8710 ---------------------------------------------------------------

def test_faa_section_iii_rows_and_values(legs: list[Leg]) -> None:
    sec = section(FAA, "Section III — Record of Pilot Time")
    assert [c.label for c in sec.columns] == ["Airplane", "Rotorcraft", "Powered Lift"]
    assert [r.label for r in sec.rows] == [
        "Total Hours", "Instruction Received", "Solo", "Pilot in Command (PIC)",
        "Second in Command (SIC)", "Cross Country Instruction", "Cross Country Solo",
        "Cross Country PIC", "Cross Country SIC", "Instrument", "Night Instruction",
        "Night Takeoff Landings", "Night PIC", "Night SIC",
        "Night Takeoff Landing PIC", "Night Takeoff Landing SIC",
    ]
    m = matrix(sec, legs)
    assert m["Total Hours"] == pytest.approx([5.0, 3.5, 0.6])
    assert m["Instruction Received"] == pytest.approx([1.0, 0, 0])
    assert m["Pilot in Command (PIC)"] == pytest.approx([0, 2.0, 0])
    assert m["Second in Command (SIC)"] == pytest.approx([4.0, 1.5, 0.6])
    assert m["Solo"] == [None, None, None]                  # not tracked
    assert m["Cross Country Instruction"] == pytest.approx([0.5, 0, 0])
    assert m["Cross Country SIC"] == pytest.approx([4.0, 0, 0])
    assert m["Night Instruction"] == pytest.approx([0.2, 0, 0])
    assert m["Night PIC"] == pytest.approx([0, 1.0, 0])
    assert m["Night SIC"] == pytest.approx([0.4, 0, 0])
    assert m["Night Takeoff Landings"] == [1, 3, 0]
    assert m["Night Takeoff Landing PIC"] == [0, 2, 0]
    assert m["Night Takeoff Landing SIC"] == [1, 1, 0]


def test_faa_keeps_only_its_own_sections(legs: list[Leg]) -> None:
    """Class Hours now ships in the shared reference block, not under FAA."""
    titles = [s.title for s in FAA.sections]
    assert titles == ["Section III — Record of Pilot Time",
                      "Glider / Lighter Than Air"]
    assert section(FAA, "Glider / Lighter Than Air").rows


# -- carriers ---------------------------------------------------------------

def test_united_form_per_aircraft(legs: list[Leg]) -> None:
    html = render.render_section(UAL.sections[0], legs, CTX)
    assert html.count('<table class="form">') == 4       # CL-65, AH-1Z, C172, MV-22B
    crj, cobra = html.split('<table class="form">')[1:3]
    assert cells(crj) == [
        "Aircraft manufacturerBombardier", "ModelCRJ-200 / CRJ-700",
        "Aircraft classMulti Engine Land", "PowerplantJet",
        "Type of operationFAR Part 121", "Type ratedYes",
        "Last flown monthNovember", "Last flown year2026",
        "Total PIC (including time as an instructor)0.0", "",
    ]
    assert "Type of operationMilitary" in cells(cobra)
    assert "Type ratedNo" in cells(cobra)
    assert "Total PIC (including time as an instructor)2.0" in cells(cobra)


def test_southwest_sortie_conversion(legs: list[Leg]) -> None:
    html = render.render_section(SWA.sections[0], legs, CTX)
    cobra = cells(html.split('<table class="form">')[2])
    assert cobra == [
        "AircraftAH-1Z", "PIC2.0", "SIC1.5", "Instructor2.0", "Last 24 mo0.0",
        "Operating RuleMilitary", "PIC Sorties1", "SIC Sorties1",
        "Last Flown Date2020-06-01", "",
        "Sortie factor 0.3", "PIC conversion0.3", "SIC conversion0.3", "",
        "Total w/ conversion", "PIC2.3", "SIC1.8", "",
    ]
    skyhawk = cells(html.split('<table class="form">')[3])
    assert "Operating RuleFAR Part 91" in skyhawk and "PIC Sorties0" in skyhawk


# -- summary ----------------------------------------------------------------

def test_summary_headline_and_by_type_totals(legs: list[Leg]) -> None:
    headline, history, by_type = profiles.SUMMARY_SECTIONS
    values = {r.label: r.value(legs, CTX) for r in headline.rows}
    assert values == pytest.approx({
        "Total Time": 9.1, "FW Multi-Eng": 4.0, "FW Turbine": 4.0,
        "FW PIC": 0.0, "Hrs PIC": 2.0, "Military": 4.1,
    })
    assert headline.notes == ("No military conversions applied.",
                              "No simulator time included.")
    assert [r.value(legs, CTX) for r in history.rows] == pytest.approx([4.0, 4.0, 4.0])

    html = render.render_section(by_type, legs, CTX)
    total_row = cells(html.split("<tfoot>")[1])
    assert total_row[:2] == ["TOTAL", "9.1"]
    assert "CONDITIONS" in html and "LANDINGS" in html     # summary may use them


# -- certified log pages ----------------------------------------------------

def many_legs(n: int) -> list[Leg]:
    start = date(2019, 1, 1)
    return [
        leg(i, (start + timedelta(days=i)).isoformat(), COBRA, block=1.1, pic=1.1,
            mil_sortie=1, nvg=0.3, night=0.9, instrument=0.8, xc=0.7,
            day_landings=6, night_landings=5)
        for i in range(n)
    ]


def test_log_pages_paginate_and_carry_forward() -> None:
    pages = render.paginate_log(many_legs(120))
    assert [len(p.legs) for p in pages] == [50, 50, 20]
    col = {c.label: i for i, c in enumerate(render.LOG_COLUMNS)}
    total, sortie, nvg = col["TOTAL"], col["MIL SORTIE"], col["NVG"]

    assert pages[0].forwarded[total] == 0
    assert pages[0].page_totals[total] == 550               # tenths: 50 x 1.1
    assert pages[1].forwarded == pages[0].to_date
    assert pages[2].to_date[total] == 1320                  # 132.0 h, exact
    assert pages[2].to_date[sortie] == 120
    assert pages[2].to_date[nvg] == 360
    for page in pages:
        assert all(f + t == d for f, t, d in
                   zip(page.forwarded, page.page_totals, page.to_date))


def test_log_pages_never_print_synthetic_or_untracked_columns() -> None:
    labels = [c.label for c in render.LOG_COLUMNS]
    assert labels == [
        "DATE", "TYPE", "IDENT", "ROUTE", "TOTAL",
        "ASEL", "AMEL", "ASES", "AMES", "HELO", "LIFT", "GLIDE",
        "PIC", "SIC", "DUAL", "IP/CFI", "MIL SORTIE", "NVG", "COMBAT", "REMARKS",
    ]
    html = render.render_log_pages(many_legs(3), CTX)
    # The synthetic per-row values (0.9 night, 0.8 inst, 0.7 xc, 6/5 landings)
    # must not appear in any body cell.
    body = cells(html.split("<tbody>")[1].split("</tbody>")[0])
    assert not {"0.9", "0.8", "0.7", "6", "5"} & set(body)
    assert "pre-2026 night, instrument, cross-country and landing" in html.lower()


def test_log_page_layout(legs: list[Leg]) -> None:
    html = render.render_log_pages(legs, CTX)
    assert html.count('<section class="log-page">') == 1
    body = html.split("<tbody>")[1].split("</tbody>")[0]
    assert body.count("<tr>") == 50                  # short page padded to 50 rows
    assert html.split("<tfoot>")[1].count("<tr>") == 3
    for text in ("TOTALS THIS PAGE", "AMT. FORWARDED", "TOTALS TO DATE",
                 render.CERTIFICATION, "_" * 25, "Pat &lt;Test&gt; Pilot",
                 "GENERAL INFORMATION", "TYPE OF PILOTING TIME", "MILITARY",
                 "Page 1 of 1"):
        assert text in html
    row = cells(html.split("<tbody>")[1].split("</tr>")[4])      # leg 5 (CR2)
    assert row[:5] == ["2026-05-10", "CR2", "", "KORD-KSGF", "2.2"]
    assert row[-1] == "SKW 5852"                     # no remark -> flight number
    assert "IFS, 5R4" in html


# -- document + CLI ---------------------------------------------------------

@pytest.mark.parametrize("target", profiles.TARGETS)
def test_render_profile_document(target: str, legs: list[Leg]) -> None:
    html = render.render_profile(profiles.PROFILES[target], legs, CTX)
    assert html.startswith("<!doctype html>")
    assert html.index("Flight Time Summary") < html.index('class="log-page"')
    assert "<Test>" not in html                       # pilot.toml text is escaped
    assert "size: letter landscape" in html and "break-inside: avoid" in html
    assert "2015-03-01 to 2026-11-01" in html
    # An export is handed to the airline: no personal goal tracking in it.
    assert "Milestones" not in html and "to go" not in html
    # The section wrapper must not pick up the tile grid's own class.
    assert 'class="section metrics"' not in html
    short = render.render_profile(profiles.PROFILES[target], legs, CTX, include_log=False)
    assert 'class="log-page"' not in short


def test_load_pilot(tmp_path) -> None:
    assert profiles.load_pilot(tmp_path / "missing.toml") == Pilot()
    path = tmp_path / "pilot.toml"
    path.write_text('name = "A B"\ncertificate_number = "9"\ntype_ratings = ["CL65"]\n')
    pilot = profiles.load_pilot(path)
    assert (pilot.name, pilot.certificate_number, pilot.type_ratings) == ("A B", "9", ("CL65",))


def test_cli_targets_match_profiles() -> None:
    result = CliRunner().invoke(cli.main, ["export-profile", "--help"])
    assert result.exit_code == 0
    assert f"[{'|'.join(profiles.TARGETS)}]" in result.output
    assert profiles.TARGETS == ("faa", "ual", "swa", "allegiant")
    assert "--commit" not in result.output            # read-only: nothing to commit


def test_cli_writes_export(tmp_path, monkeypatch, legs: list[Leg]) -> None:
    import logbook_import.grist_settings as gs
    import logbook_import.profile_data as pd_mod

    monkeypatch.setattr(cli, "active_backend", lambda: "grist")
    monkeypatch.setattr(gs, "load_grist_settings",
                        lambda: gs.GristSettings("http://test", "k", "d"))
    monkeypatch.setattr(pd_mod, "load_legs", lambda client: legs)
    pilot = tmp_path / "pilot.toml"
    pilot.write_text('name = "A B"\n')

    result = CliRunner().invoke(cli.main, [
        "export-profile", "--target", "faa", "--output", str(tmp_path / "out"),
        "--pilot", str(pilot), "--as-of", "2026-06-01",
    ])
    assert result.exit_code == 0, result.output
    out = tmp_path / "out" / "logbook-faa-2026-06-01.html"
    assert out.is_file() and out.stat().st_mode & 0o077 == 0
    assert "5 flights, total 7.3 h" in result.output      # 2026-11-01 leg left out
    assert "Section III" in out.read_text()
