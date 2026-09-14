"""
Backfill Duty_Periods report/release time zones, Trips TAFB and Trips Planned_Block
from the archived SkedPlus exports in recorded/{actual,planned}.

Why: before the per-airport duty time-zone fix, report/release were stored as
naive local clocks interpreted in the importing machine's zone, and report and
release shared one zone.  TAFB was only written by planned imports, and some
Planned_Block values match no source file.

What it does (only for trips that already exist in Grist — never creates rows):
- Duty_Periods Report_Time / Release_Time recomputed with
  ``import_planner.duty_report_release_utc`` (report zone = first line origin,
  release zone = last line destination).  Source = actual file when it has that
  duty date, else the planned file.  Duty days that fall back to naive times are
  skipped, never written.
- Trips TAFB from the newest file for the trip (actual if present, else planned).
- Trips Planned_Block from the planned file header (only when a planned file exists).
- Lists Flight rows that the placeholder rule would exclude (CXL/FDP/REF/... ).
  They are printed only — never deleted.

Matching: Trip_Key / Duty_Period_Key are built with ``keys.py``, which strips a
SkyWest revision suffix (E3405A -> E3405).  Pre-normalization rows kept the raw
pairing id (e.g. E3058E|2026-05-09), so both spellings are tried.

Default: dry-run (only GET requests; nothing is written). Pass --commit to write.

Usage:
    uv run python scripts/backfill_duty_tz_tafb.py [--recorded DIR] [--env PATH] [--commit]
"""

from __future__ import annotations

import argparse
import os
import sys
import urllib.parse
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from logbook_import import grist_fields as F  # noqa: E402
from logbook_import.config import discover_pairing_file_sets  # noqa: E402
from logbook_import.grist_airports import fetch_airport_index  # noqa: E402
from logbook_import.grist_client import GristClient  # noqa: E402
from logbook_import.grist_mapper import format_grist_datetime  # noqa: E402
from logbook_import.grist_settings import DEFAULT_GRIST_URL, GristSettings  # noqa: E402
from logbook_import.import_planner import duty_report_release_utc  # noqa: E402
from logbook_import.keys import import_flight_key, trip_key  # noqa: E402
from logbook_import.leg_classifier import is_loggable_flight  # noqa: E402
from logbook_import.models import PairingExport  # noqa: E402
from logbook_import.parsers.merge import load_pairing_export  # noqa: E402

# ── Paths ─────────────────────────────────────────────────────────────────────

TOOLS_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = TOOLS_ROOT.parent
DEFAULT_RECORDED = REPO_ROOT / "recorded"
DEFAULT_ENV = TOOLS_ROOT / ".env"

FLOAT_EPS = 1e-6


# ── Grist access ──────────────────────────────────────────────────────────────

class ReadGetClient(GristClient):
    """GristClient whose SQL reads use GET /sql?q= (no POST during dry-run)."""

    def sql(self, query: str, args: list[Any] | None = None) -> list[dict[str, Any]]:
        if args:
            raise ValueError("ReadGetClient.sql does not support bound args")
        path = self._doc_path("/sql?q=" + urllib.parse.quote(query))
        resp = self._request("GET", path)
        return [r["fields"] for r in resp["records"]]


def load_settings(env_path: Path) -> GristSettings:
    load_dotenv(env_path, override=True)
    url = os.environ.get("GRIST_URL", DEFAULT_GRIST_URL).strip().rstrip("/")
    api_key = os.environ.get("GRIST_API_KEY", "").strip()
    doc_id = os.environ.get("GRIST_DOC", "").strip()
    if not api_key or not doc_id:
        sys.exit(f"GRIST_API_KEY / GRIST_DOC not set. Add them to {env_path}")
    return GristSettings(url=url, api_key=api_key, doc_id=doc_id)


# ── Source files ──────────────────────────────────────────────────────────────

@dataclass
class TripSources:
    grist_trip: dict[str, Any]
    matched_key: str
    actual: list[PairingExport] = field(default_factory=list)
    planned: list[PairingExport] = field(default_factory=list)

    @property
    def newest(self) -> PairingExport:
        return (self.actual or self.planned)[-1]


def load_exports(recorded: Path, mode: str) -> tuple[list[PairingExport], list[str]]:
    sets, warnings = discover_pairing_file_sets(recorded / mode)
    warnings = [w for w in warnings if "Ignoring unrelated file" not in w]
    exports: list[PairingExport] = []
    for fs in sets:
        pairing, warns = load_pairing_export(fs)
        exports.append(pairing)
        warnings.extend(f"{fs.txt_path.name}: {w}" for w in warns)
    return exports, warnings


def candidate_trip_keys(pairing: PairingExport) -> list[str]:
    normalized = trip_key(pairing.pairing_id, pairing.start_date)
    raw = f"{pairing.pairing_id.strip().upper()}|{pairing.start_date.isoformat()}"
    return [normalized] if raw == normalized else [normalized, raw]


# ── Formatting ────────────────────────────────────────────────────────────────

def fmt_epoch(value: Any) -> str:
    if value in (None, ""):
        return "-"
    return datetime.fromtimestamp(int(value), tz=timezone.utc).strftime("%Y-%m-%d %H:%MZ")


def fmt_hours(report: Any, release: Any) -> str:
    if report in (None, "") or release in (None, ""):
        return "-"
    minutes = round((int(release) - int(report)) / 60)
    return f"{minutes // 60}:{minutes % 60:02d}"


def fmt_num(value: Any) -> str:
    return "-" if value in (None, "") else f"{float(value):g}"


def print_table(headers: list[str], rows: list[list[str]]) -> None:
    if not rows:
        print("  (none)")
        return
    widths = [max(len(h), *(len(r[i]) for r in rows)) for i, h in enumerate(headers)]
    line = "  " + "  ".join(h.ljust(w) for h, w in zip(headers, widths))
    print(line)
    print("  " + "  ".join("-" * w for w in widths))
    for r in rows:
        print("  " + "  ".join(c.ljust(w) for c, w in zip(r, widths)))


def num_changed(before: Any, after: float) -> bool:
    if before in (None, ""):
        return True
    return abs(float(before) - after) > FLOAT_EPS


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Backfill duty report/release zones, Trips TAFB and Planned_Block from "
            "recorded SkedPlus exports. Dry-run by default — pass --commit to write."
        )
    )
    parser.add_argument("--recorded", type=Path, default=DEFAULT_RECORDED, metavar="DIR",
                        help=f"Directory holding actual/ and planned/ (default: {DEFAULT_RECORDED})")
    parser.add_argument("--env", type=Path, default=DEFAULT_ENV, metavar="PATH",
                        help=f".env with GRIST_URL/GRIST_API_KEY/GRIST_DOC (default: {DEFAULT_ENV})")
    parser.add_argument("--commit", action="store_true",
                        help="Write Duty_Periods and Trips updates. Omit to perform a dry-run.")
    args = parser.parse_args()

    dry_run = not args.commit
    tag = "[DRY RUN] " if dry_run else ""

    settings = load_settings(args.env)
    client = ReadGetClient(settings)

    print(f"{tag}Backfill duty time zones / TAFB / Planned_Block")
    print(f"  recorded: {args.recorded}")
    print(f"  grist:    {settings.url} doc {settings.doc_id}")
    print(f"  run at:   {datetime.now(timezone.utc):%Y-%m-%d %H:%MZ}\n")

    # ── Load files ────────────────────────────────────────────────────────────
    actual, warns_a = load_exports(args.recorded, "actual")
    planned, warns_p = load_exports(args.recorded, "planned")
    print(f"Files: {len(actual)} actual, {len(planned)} planned")
    for w in warns_a + warns_p:
        print(f"  WARN: {w}")
    print()

    # ── Load Grist state (GET only) ───────────────────────────────────────────
    airport_index = fetch_airport_index(client)
    trips = client.sql(
        f'SELECT id, "{F.F_TRIP_KEY}", "{F.F_TRIP_PAIRING_ID}", "{F.F_TRIP_TAFB}", '
        f'"{F.F_TRIP_PLANNED_BLOCK}" FROM "{F.TABLE_TRIPS}"'
    )
    trips_by_key = {str(t[F.F_TRIP_KEY]): t for t in trips if t.get(F.F_TRIP_KEY)}
    duties = client.sql(
        f'SELECT id, "{F.F_DUTY_PERIOD_KEY}", "{F.F_DUTY_REPORT_TIME}", '
        f'"{F.F_DUTY_RELEASE_TIME}", "{F.F_DUTY_TRIPS}" FROM "{F.TABLE_DUTY_PERIODS}"'
    )
    duties_by_key = {str(d[F.F_DUTY_PERIOD_KEY]): d for d in duties if d.get(F.F_DUTY_PERIOD_KEY)}
    flights = client.sql(
        f'SELECT f.id, f."{F.F_IMPORT_FLIGHT_KEY}" AS k, f."{F.F_FLIGHT_NUMBER}" AS num, '
        f'f."{F.F_FLIGHT_BLOCK_TIME}" AS block, f."{F.F_FLIGHT_DEADHEAD}" AS dh, '
        f'dep."{F.F_AIRPORT_IATA}" AS dep, arr."{F.F_AIRPORT_IATA}" AS arr, '
        f'f."{F.F_FLIGHT_TRIPS}" AS trip '
        f'FROM "{F.TABLE_FLIGHTS}" f '
        f'LEFT JOIN "{F.TABLE_AIRPORTS}" dep ON dep.id = f."{F.F_FLIGHT_DEPARTURE}" '
        f'LEFT JOIN "{F.TABLE_AIRPORTS}" arr ON arr.id = f."{F.F_FLIGHT_ARRIVAL}"'
    )
    flights_by_key = {str(f["k"]): f for f in flights if f.get("k")}
    print(f"Grist: {len(trips)} trips, {len(duties)} duty periods, {len(flights)} flights, "
          f"{len(airport_index)} airports\n")

    # ── Match files to Grist trips ────────────────────────────────────────────
    sources: dict[int, TripSources] = {}
    unmatched: list[str] = []
    for mode, exports in (("actual", actual), ("planned", planned)):
        for pairing in exports:
            keys = candidate_trip_keys(pairing)
            hits = [k for k in keys if k in trips_by_key]
            name = Path(pairing.source_txt).name if pairing.source_txt else pairing.pairing_id
            if not hits:
                unmatched.append(f"{mode}/{name} (tried {', '.join(keys)})")
                continue
            if len(hits) > 1:
                print(f"  WARN: {mode}/{name}: both {hits} exist in Grist — using {hits[0]}")
            grist_trip = trips_by_key[hits[0]]
            src = sources.setdefault(int(grist_trip["id"]), TripSources(grist_trip, hits[0]))
            getattr(src, mode).append(pairing)

    print(f"Trips matched: {len(sources)}")
    for u in unmatched:
        print(f"  not in Grist (skipped): {u}")
    print()

    # ── Duty periods ──────────────────────────────────────────────────────────
    duty_updates: list[tuple[int, dict[str, Any]]] = []
    duty_rows: list[list[str]] = []
    duty_warnings: list[str] = []
    missing_duty_rows: list[str] = []
    for src in sorted(sources.values(), key=lambda s: s.matched_key):
        ordered = [("actual", p) for p in reversed(src.actual)] + [
            ("planned", p) for p in reversed(src.planned)
        ]
        seen_dates: set[date] = set()
        for mode, pairing in ordered:
            for duty in pairing.duty_days:
                if duty.duty_date in seen_dates:
                    continue
                seen_dates.add(duty.duty_date)
                dp_key = f"{src.matched_key}|{duty.duty_date.isoformat()}"
                row = duties_by_key.get(dp_key)
                if row is None:
                    missing_duty_rows.append(f"{dp_key} ({mode} {pairing.pairing_id})")
                    continue
                report, release, warns = duty_report_release_utc(duty, airport_index)
                for w in warns:
                    duty_warnings.append(f"{dp_key} [{mode} {pairing.pairing_id}]: {w}")
                if report.tzinfo is None or release.tzinfo is None:
                    continue  # naive fallback — never write
                new_report = format_grist_datetime(report)
                new_release = format_grist_datetime(release)
                old_report = row.get(F.F_DUTY_REPORT_TIME)
                old_release = row.get(F.F_DUTY_RELEASE_TIME)
                if old_report == new_report and old_release == new_release:
                    continue
                duty_updates.append((int(row["id"]), {
                    F.F_DUTY_REPORT_TIME: new_report,
                    F.F_DUTY_RELEASE_TIME: new_release,
                }))
                report_ap = duty.legs[0].origin
                release_ap = duty.legs[-1].destination
                duty_rows.append([
                    dp_key,
                    f"{mode}:{pairing.pairing_id}",
                    f"{report_ap}->{release_ap}",
                    fmt_epoch(old_report), fmt_epoch(new_report),
                    fmt_epoch(old_release), fmt_epoch(new_release),
                    fmt_hours(old_report, old_release), fmt_hours(new_report, new_release),
                    f"{duty.duty_hours:g}",
                ])

    print(f"=== Duty_Periods Report_Time / Release_Time: {len(duty_updates)} to change ===")
    print_table(
        ["Duty_Period_Key", "source", "rpt->rel", "report before", "report after",
         "release before", "release after", "duty bef", "duty aft", "sheet"],
        duty_rows,
    )
    for w in duty_warnings:
        print(f"  WARN: {w}")
    for m in missing_duty_rows:
        print(f"  duty day not in Grist (skipped): {m}")
    print()

    # ── Trips TAFB / Planned_Block ────────────────────────────────────────────
    trip_updates: dict[int, dict[str, Any]] = {}
    tafb_rows: list[list[str]] = []
    pb_rows: list[list[str]] = []
    for trip_id, src in sorted(sources.items(), key=lambda kv: kv[1].matched_key):
        newest = src.newest
        newest_mode = "actual" if src.actual else "planned"
        if newest.tafb_hours:
            new_tafb = round(newest.tafb_hours, 2)
            old_tafb = src.grist_trip.get(F.F_TRIP_TAFB)
            if num_changed(old_tafb, new_tafb):
                trip_updates.setdefault(trip_id, {})[F.F_TRIP_TAFB] = new_tafb
                tafb_rows.append([src.matched_key, f"{newest_mode}:{newest.pairing_id}",
                                  fmt_num(old_tafb), fmt_num(new_tafb)])
        if src.planned:
            plan_file = src.planned[-1]
            new_pb = plan_file.block_hours
            old_pb = src.grist_trip.get(F.F_TRIP_PLANNED_BLOCK)
            if new_pb and num_changed(old_pb, new_pb):
                trip_updates.setdefault(trip_id, {})[F.F_TRIP_PLANNED_BLOCK] = new_pb
                pb_rows.append([src.matched_key, f"planned:{plan_file.pairing_id}",
                                fmt_num(old_pb), fmt_num(new_pb)])

    print(f"=== Trips TAFB: {len(tafb_rows)} to change ===")
    print_table(["Trip_Key", "source", "before", "after"], tafb_rows)
    print()
    print(f"=== Trips Planned_Block: {len(pb_rows)} to change ===")
    print_table(["Trip_Key", "source", "before", "after"], pb_rows)
    no_planned = sorted(s.matched_key for s in sources.values() if not s.planned)
    if no_planned:
        print(f"  no planned file (Planned_Block left as-is): {', '.join(no_planned)}")
    print()

    # ── Placeholder Flight rows (report only) ─────────────────────────────────
    placeholder_rows: dict[int, list[str]] = {}
    for src in sources.values():
        for mode, exports in (("actual", src.actual), ("planned", src.planned)):
            for pairing in exports:
                raw_pid = pairing.pairing_id.strip().upper()
                for duty in pairing.duty_days:
                    for leg in duty.legs:
                        if is_loggable_flight(leg):
                            continue
                        leg_date = leg.duty_date or duty.duty_date
                        normalized = import_flight_key(
                            pairing.pairing_id, leg_date, leg.flight,
                            leg.origin, leg.destination, leg.departure,
                        )
                        raw = raw_pid + normalized[normalized.index("|"):]
                        for k in dict.fromkeys([normalized, raw]):
                            f = flights_by_key.get(k)
                            if f is not None:
                                placeholder_rows.setdefault(int(f["id"]), [
                                    str(f["id"]), k, str(f.get("num")),
                                    f"{f.get('dep')}-{f.get('arr')}", fmt_num(f.get("block")),
                                    "Y" if f.get("dh") else "N", f"{mode}:{pairing.pairing_id}",
                                ])
    # Generic scan for rows whose source file is not in recorded/.
    for f in flights:
        num = str(f.get("num") or "").strip().lstrip("*")
        if (
            num and not num.isdigit()
            and not f.get("block")
            and f.get("dep") and f.get("dep") == f.get("arr")
            and int(f["id"]) not in placeholder_rows
        ):
            placeholder_rows[int(f["id"])] = [
                str(f["id"]), str(f.get("k")), num, f"{f.get('dep')}-{f.get('arr')}",
                fmt_num(f.get("block")), "Y" if f.get("dh") else "N", "grist-scan",
            ]

    print(f"=== Placeholder Flight rows (NOT deleted — listed only): {len(placeholder_rows)} ===")
    print_table(["row id", "Import_Flight_Key", "flight", "route", "block", "DH", "found via"],
                [placeholder_rows[k] for k in sorted(placeholder_rows)])
    print()

    # ── Write / summary ───────────────────────────────────────────────────────
    print("=" * 60)
    print(f"Duty periods changed:        {len(duty_updates)}")
    print(f"Trips with TAFB change:      {len(tafb_rows)}")
    print(f"Trips with Planned_Block chg: {len(pb_rows)}")
    print(f"Placeholder flights found:   {len(placeholder_rows)}")
    if dry_run:
        print("DRY RUN complete — no data was written.")
        print("Re-run with --commit to write Duty_Periods and Trips.")
        return

    client.update_records(F.TABLE_DUTY_PERIODS, duty_updates)
    client.update_records(F.TABLE_TRIPS, list(trip_updates.items()))
    print(f"Wrote {len(duty_updates)} duty period(s) and {len(trip_updates)} trip(s).")


if __name__ == "__main__":
    main()
