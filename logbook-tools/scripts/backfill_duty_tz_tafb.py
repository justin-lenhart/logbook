"""
One-time backfill of existing Grist rows to the current importer rules, from the
archived SkedPlus exports in recorded/{actual,planned}.  Updates only: it never
creates or deletes a row.  Pre-Jul-2026 source files are only READ here; nothing
is re-imported (golden rule 2).

Changes (each listed old -> new in the output):
1. Re-key (R2): drop the SkyWest pairing revision suffix from Trips.Trip_Key,
   Trips.Trip_Number_Pairing_ID, Duty_Periods.Duty_Period_Key,
   Flights.Import_Flight_Key and Import_Batch.Batch_Name in one operation.
   Links between tables are row ids, so they stay valid.  Key collisions (a new
   key that another row already has) are listed; --commit refuses to run while
   any collision is unresolved.
2. Duty_Periods, per duty day (source = actual file when it has that date, else
   the planned file):
   - Report_Time / Release_Time with per-airport time zones
     (``duty_report_release_utc``); naive fallbacks are never written.
   - Report_Airport / Release_Airport (``duty_airports``).
   - Actual_Credit = Day Total credit (R7): actual file, days dated <= today.
   - Status: flown day in the actual file with no flight lines -> Cancelled (R9),
     with flight lines -> Actual.  Only Planned/Actual rows are changed.
   - Status: the trip's Planned rows that the actual file no longer contains,
     dated <= today -> Cancelled (trip cut short).
3. Trips:
   - TAFB from the newest file (actual if present, else planned) (R6).
   - Planned_Block from the planned file header.
   - Base = origin of the first schedule line of the newest file (R4, one-time
     correction; the importer itself never overwrites Base).
   - Actual_Credit = actual file header "Credit:" (R7).
   - End_Date = last duty date of the actual file (flown span).
4. Flights: deadhead rows get Passengers = 0.
Printed only (never written): placeholder Flight rows, R8 day-credit warnings,
trip credit (header vs Day Totals) warnings.

--commit also refuses to run while Trips.Actual_Credit or
Duty_Periods.Actual_Credit is still a formula column.

Default: dry-run (GET requests only; nothing is written). Pass --commit to write.

Usage:
    uv run python scripts/backfill_duty_tz_tafb.py [--recorded DIR] [--env PATH] [--commit]
"""

from __future__ import annotations

import argparse
import os
import re
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
from logbook_import.grist_mapper import format_grist_date, format_grist_datetime  # noqa: E402
from logbook_import.grist_settings import DEFAULT_GRIST_URL, GristSettings  # noqa: E402
from logbook_import.import_planner import (  # noqa: E402
    day_credit_check,
    duty_airports,
    duty_report_release_utc,
    trip_credit_check,
)
from logbook_import.keys import duty_period_key, import_flight_key, normalize_pairing_id, trip_key  # noqa: E402
from logbook_import.leg_classifier import is_loggable_flight  # noqa: E402
from logbook_import.models import PairingExport  # noqa: E402
from logbook_import.parsers.merge import load_pairing_export  # noqa: E402

# ── Paths ─────────────────────────────────────────────────────────────────────

TOOLS_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = TOOLS_ROOT.parent
DEFAULT_RECORDED = REPO_ROOT / "recorded"
DEFAULT_ENV = TOOLS_ROOT / ".env"

FLOAT_EPS = 1e-6

# A SkyWest pairing with a revision suffix: 5-char body + 1 letter (E3436D).
# HIST-0001 style keys and 5-char ids never match.
SUFFIXED_PAIRING_RE = re.compile(r"^[A-Z][A-Z0-9]{4}[A-Z]$")


# ── Re-keying (pure helpers, unit-tested) ─────────────────────────────────────

def rekey(key: str) -> str:
    """Drop the pairing revision suffix from the first ``|`` segment of a key."""
    head, sep, rest = key.partition("|")
    if sep and SUFFIXED_PAIRING_RE.match(head):
        return normalize_pairing_id(head) + sep + rest
    return key


def rekey_pairing_id(pairing_id: str) -> str:
    pid = pairing_id.strip().upper()
    return normalize_pairing_id(pid) if SUFFIXED_PAIRING_RE.match(pid) else pairing_id


def find_collisions(rows: list[tuple[int, str]]) -> dict[str, list[tuple[int, str]]]:
    """Group (row id, old key) by re-keyed value; return groups with > 1 row
    where at least one row's key changes."""
    groups: dict[str, list[tuple[int, str]]] = {}
    for rid, old in rows:
        groups.setdefault(rekey(old), []).append((rid, old))
    return {
        new: members
        for new, members in groups.items()
        if len(members) > 1 and any(old != new for _, old in members)
    }


def missing_days_to_cancel(
    rows: list[dict[str, Any]], file_keys: set[str], today: date
) -> list[dict[str, Any]]:
    """Planned duty rows of a trip that the actual file does not contain, dated
    <= today. ``rows`` carry ``key`` (re-keyed), ``status`` and ``date`` (epoch)."""
    cutoff = format_grist_date(today)
    return [
        r for r in rows
        if r["status"] == "Planned"
        and r["key"] not in file_keys
        and r["date"] not in (None, "")
        and int(r["date"]) <= cutoff
    ]


# ── Grist access ──────────────────────────────────────────────────────────────

class ReadGetClient(GristClient):
    """GristClient whose SQL reads use GET /sql?q= (no POST during dry-run)."""

    def sql(self, query: str, args: list[Any] | None = None) -> list[dict[str, Any]]:
        if args:
            raise ValueError("ReadGetClient.sql does not support bound args")
        path = self._doc_path("/sql?q=" + urllib.parse.quote(query))
        resp = self._request("GET", path)
        return [r["fields"] for r in resp["records"]]

    def formula_columns(self, table: str) -> set[str]:
        cols = self._request("GET", self._doc_path(f"/tables/{table}/columns"))["columns"]
        return {c["id"] for c in cols if c["fields"].get("isFormula")}

    def row_counts(self) -> dict[str, int]:
        tables = (F.TABLE_TRIPS, F.TABLE_DUTY_PERIODS, F.TABLE_FLIGHTS, F.TABLE_IMPORT_BATCH)
        sel = ", ".join(f'(SELECT COUNT(*) FROM "{t}") AS "{t}"' for t in tables)
        return self.sql(f"SELECT {sel}")[0]


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
    key: str  # re-keyed Trip_Key
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


# ── Formatting ────────────────────────────────────────────────────────────────

def fmt_epoch(value: Any) -> str:
    if value in (None, ""):
        return "-"
    return datetime.fromtimestamp(int(value), tz=timezone.utc).strftime("%Y-%m-%d %H:%MZ")


def fmt_date(value: Any) -> str:
    if value in (None, ""):
        return "-"
    return datetime.fromtimestamp(int(value), tz=timezone.utc).strftime("%Y-%m-%d")


def fmt_hours(report: Any, release: Any) -> str:
    if report in (None, "") or release in (None, ""):
        return "-"
    minutes = round((int(release) - int(report)) / 60)
    return f"{minutes // 60}:{minutes % 60:02d}"


def fmt_num(value: Any) -> str:
    return "-" if value in (None, "") else f"{float(value):g}"


def fmt_str(value: Any) -> str:
    return "-" if value in (None, "") else str(value)


def print_table(title: str, headers: list[str], rows: list[list[str]]) -> None:
    print(f"=== {title}: {len(rows)} ===")
    if not rows:
        print("  (none)\n")
        return
    widths = [max(len(h), *(len(r[i]) for r in rows)) for i, h in enumerate(headers)]
    print("  " + "  ".join(h.ljust(w) for h, w in zip(headers, widths)))
    print("  " + "  ".join("-" * w for w in widths))
    for r in rows:
        print("  " + "  ".join(c.ljust(w) for c, w in zip(r, widths)))
    print()


def num_changed(before: Any, after: float) -> bool:
    if before in (None, ""):
        return True
    return abs(float(before) - after) > FLOAT_EPS


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Backfill existing Grist rows to the current importer rules (re-key, duty "
            "times/airports/credit/status, trip TAFB/Base/credit/dates, deadhead "
            "passengers). Dry-run by default — pass --commit to write."
        )
    )
    parser.add_argument("--recorded", type=Path, default=DEFAULT_RECORDED, metavar="DIR",
                        help=f"Directory holding actual/ and planned/ (default: {DEFAULT_RECORDED})")
    parser.add_argument("--env", type=Path, default=DEFAULT_ENV, metavar="PATH",
                        help=f".env with GRIST_URL/GRIST_API_KEY/GRIST_DOC (default: {DEFAULT_ENV})")
    parser.add_argument("--commit", action="store_true",
                        help="Write the updates. Omit to perform a dry-run.")
    args = parser.parse_args()

    dry_run = not args.commit
    tag = "[DRY RUN] " if dry_run else ""
    today = date.today()

    settings = load_settings(args.env)
    client = ReadGetClient(settings)

    print(f"{tag}Backfill Grist rows to the current importer rules")
    print(f"  recorded: {args.recorded}")
    print(f"  grist:    {settings.url} doc {settings.doc_id}")
    print(f"  run at:   {datetime.now(timezone.utc):%Y-%m-%d %H:%MZ} (today = {today})\n")

    # ── Load files ────────────────────────────────────────────────────────────
    actual, warns_a = load_exports(args.recorded, "actual")
    planned, warns_p = load_exports(args.recorded, "planned")
    print(f"Files: {len(actual)} actual, {len(planned)} planned")
    for w in warns_a + warns_p:
        print(f"  WARN: {w}")
    print()

    # ── Load Grist state (GET only) ───────────────────────────────────────────
    counts_before = client.row_counts()
    airport_index = fetch_airport_index(client)
    trips = client.sql(
        f'SELECT id, "{F.F_TRIP_KEY}" AS key, "{F.F_TRIP_PAIRING_ID}" AS pid, '
        f'"{F.F_TRIP_TAFB}" AS tafb, "{F.F_TRIP_PLANNED_BLOCK}" AS pblock, '
        f'"{F.F_TRIP_BASE}" AS base, "{F.F_TRIP_ACTUAL_CREDIT}" AS acredit, '
        f'"{F.F_TRIP_END_DATE}" AS end_date FROM "{F.TABLE_TRIPS}"'
    )
    duties = client.sql(
        f'SELECT d.id, d."{F.F_DUTY_PERIOD_KEY}" AS key, d."{F.F_DUTY_TRIPS}" AS trip, '
        f'd."{F.F_DUTY_STATUS}" AS status, d."{F.F_DUTY_DATE}" AS date, '
        f'd."{F.F_DUTY_REPORT_TIME}" AS report, d."{F.F_DUTY_RELEASE_TIME}" AS release, '
        f'd."{F.F_DUTY_REPORT_AIRPORT}" AS rpt_ap, d."{F.F_DUTY_RELEASE_AIRPORT}" AS rel_ap, '
        f'd."{F.F_DUTY_ACTUAL_CREDIT}" AS acredit, '
        f'(SELECT COUNT(*) FROM "{F.TABLE_FLIGHTS}" f WHERE f."{F.F_FLIGHT_DUTY_PERIOD}" = d.id) AS nf '
        f'FROM "{F.TABLE_DUTY_PERIODS}" d'
    )
    flights = client.sql(
        f'SELECT f.id, f."{F.F_IMPORT_FLIGHT_KEY}" AS key, f."{F.F_FLIGHT_NUMBER}" AS num, '
        f'f."{F.F_FLIGHT_BLOCK_TIME}" AS block, f."{F.F_FLIGHT_DEADHEAD}" AS dh, '
        f'f."{F.F_FLIGHT_PASSENGERS}" AS pax, '
        f'dep."{F.F_AIRPORT_IATA}" AS dep, arr."{F.F_AIRPORT_IATA}" AS arr '
        f'FROM "{F.TABLE_FLIGHTS}" f '
        f'LEFT JOIN "{F.TABLE_AIRPORTS}" dep ON dep.id = f."{F.F_FLIGHT_DEPARTURE}" '
        f'LEFT JOIN "{F.TABLE_AIRPORTS}" arr ON arr.id = f."{F.F_FLIGHT_ARRIVAL}"'
    )
    batches = client.sql(f'SELECT id, "{F.F_BATCH_NAME}" AS key FROM "{F.TABLE_IMPORT_BATCH}"')
    print("Grist rows: " + ", ".join(f"{t} {n}" for t, n in counts_before.items())
          + f"; {len(airport_index)} airports\n")

    # Per-table updates keyed by row id; merged into one PATCH set at the end.
    updates: dict[str, dict[int, dict[str, Any]]] = {
        F.TABLE_TRIPS: {}, F.TABLE_DUTY_PERIODS: {}, F.TABLE_FLIGHTS: {}, F.TABLE_IMPORT_BATCH: {},
    }

    def put(table: str, rid: int, col: str, value: Any) -> None:
        updates[table].setdefault(int(rid), {})[col] = value

    # ── 1. Re-key ─────────────────────────────────────────────────────────────
    key_col = {
        F.TABLE_TRIPS: F.F_TRIP_KEY, F.TABLE_DUTY_PERIODS: F.F_DUTY_PERIOD_KEY,
        F.TABLE_FLIGHTS: F.F_IMPORT_FLIGHT_KEY, F.TABLE_IMPORT_BATCH: F.F_BATCH_NAME,
    }
    rows_by_table = {
        F.TABLE_TRIPS: trips, F.TABLE_DUTY_PERIODS: duties,
        F.TABLE_FLIGHTS: flights, F.TABLE_IMPORT_BATCH: batches,
    }
    collisions: dict[str, dict[str, list[tuple[int, str]]]] = {}
    rekey_counts: dict[str, int] = {}
    for table, rows in rows_by_table.items():
        rekey_rows = []
        for r in rows:
            old = str(r.get("key") or "")
            new = rekey(old)
            r["new_key"] = new
            if old and new != old:
                put(table, r["id"], key_col[table], new)
                rekey_rows.append([str(r["id"]), old, new])
        if table == F.TABLE_TRIPS:
            for r in rows:
                old_pid = str(r.get("pid") or "")
                new_pid = rekey_pairing_id(old_pid)
                if old_pid and new_pid != old_pid:
                    put(table, r["id"], F.F_TRIP_PAIRING_ID, new_pid)
                    rekey_rows.append([str(r["id"]), f"pid {old_pid}", f"pid {new_pid}"])
        rekey_counts[table] = len(rekey_rows)
        print_table(f"Re-key {table}.{key_col[table]} (old -> new)",
                    ["row id", "old", "new"], rekey_rows)
        found = find_collisions([(int(r["id"]), str(r.get("key") or "")) for r in rows if r.get("key")])
        if found:
            collisions[table] = found

    by_id = {t: {int(r["id"]): r for r in rows} for t, rows in rows_by_table.items()}
    coll_rows = []
    for table, found in collisions.items():
        for new, members in sorted(found.items()):
            for rid, old in members:
                r = by_id[table][rid]
                extra = (f"status={r.get('status')} flights={r.get('nf')}"
                         if table == F.TABLE_DUTY_PERIODS else "")
                coll_rows.append([table, new, str(rid), old, extra])
    print_table("KEY COLLISIONS (commit is blocked until resolved)",
                ["table", "new key", "row id", "current key", "detail"], coll_rows)
    replaced = [r for r in coll_rows if "status=Replaced" in r[4] and "flights=0" in r[4]]
    if replaced:
        print("  PROPOSAL (not done by this script): delete the Duty_Periods rows "
              f"{', '.join(r[2] for r in replaced)} (Status Replaced, no flights) in Grist, "
              "then re-run.\n")

    # Indexes by the re-keyed value.  On a collision the dry-run plans against the
    # row that holds flights (not a "Replaced" copy); --commit is blocked anyway.
    def index(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for r in sorted(rows, key=lambda r: (r.get("status") == "Replaced", -int(r.get("nf") or 0))):
            out.setdefault(r["new_key"], r)
        return out

    trips_by_key = index(trips)
    duties_by_key = index([d for d in duties if d.get("key")])
    duties_by_trip: dict[int, list[dict[str, Any]]] = {}
    for d in duties:
        duties_by_trip.setdefault(int(d["trip"] or 0), []).append(d)
    flights_by_key = index([f for f in flights if f.get("key")])

    # ── Match files to trips ──────────────────────────────────────────────────
    sources: dict[int, TripSources] = {}
    unmatched: list[str] = []
    for mode, exports in (("actual", actual), ("planned", planned)):
        for pairing in exports:
            key = trip_key(pairing.pairing_id, pairing.start_date)
            name = Path(pairing.source_txt).name if pairing.source_txt else pairing.pairing_id
            t = trips_by_key.get(key)
            if t is None:
                unmatched.append(f"{mode}/{name} ({key})")
                continue
            src = sources.setdefault(int(t["id"]), TripSources(t, key))
            getattr(src, mode).append(pairing)
    print(f"Trips matched to files: {len(sources)} of {len(trips)}")
    for u in unmatched:
        print(f"  file with no Grist trip (skipped): {u}")
    no_file = sorted(t["new_key"] for t in trips if int(t["id"]) not in sources)
    if no_file:
        print(f"  trips with no file (left as-is): {', '.join(no_file)}")
    print()

    # ── 2. Duty periods ───────────────────────────────────────────────────────
    time_rows, ap_rows, dcredit_rows, status_rows = [], [], [], []
    duty_warnings: list[str] = []
    credit_warnings: list[str] = []
    missing_duty_rows: list[str] = []
    for src in sorted(sources.values(), key=lambda s: s.key):
        ordered = [("actual", p) for p in reversed(src.actual)] + [
            ("planned", p) for p in reversed(src.planned)
        ]
        seen_dates: set[date] = set()
        for mode, pairing in ordered:
            for duty in pairing.duty_days:
                if duty.duty_date in seen_dates:
                    continue
                seen_dates.add(duty.duty_date)
                dp_key = duty_period_key(pairing.pairing_id, pairing.start_date, duty.duty_date)
                row = duties_by_key.get(dp_key)
                if row is None:
                    missing_duty_rows.append(f"{dp_key} ({mode} {pairing.pairing_id})")
                    continue
                rid = int(row["id"])
                src_label = f"{mode}:{pairing.pairing_id}"

                report, release, warns = duty_report_release_utc(duty, airport_index)
                duty_warnings.extend(f"{dp_key} [{src_label}]: {w}" for w in warns)
                if report.tzinfo is not None and release.tzinfo is not None:
                    new_report = format_grist_datetime(report)
                    new_release = format_grist_datetime(release)
                    if (row.get("report"), row.get("release")) != (new_report, new_release):
                        put(F.TABLE_DUTY_PERIODS, rid, F.F_DUTY_REPORT_TIME, new_report)
                        put(F.TABLE_DUTY_PERIODS, rid, F.F_DUTY_RELEASE_TIME, new_release)
                        time_rows.append([
                            dp_key, src_label,
                            fmt_epoch(row.get("report")), fmt_epoch(new_report),
                            fmt_epoch(row.get("release")), fmt_epoch(new_release),
                            fmt_hours(row.get("report"), row.get("release")),
                            fmt_hours(new_report, new_release), f"{duty.duty_hours:g}",
                        ])

                rpt_ap, rel_ap = duty_airports(duty)
                if rpt_ap and (row.get("rpt_ap") or "") != rpt_ap:
                    put(F.TABLE_DUTY_PERIODS, rid, F.F_DUTY_REPORT_AIRPORT, rpt_ap)
                if rel_ap and (row.get("rel_ap") or "") != rel_ap:
                    put(F.TABLE_DUTY_PERIODS, rid, F.F_DUTY_RELEASE_AIRPORT, rel_ap)
                if (rpt_ap, rel_ap) != (row.get("rpt_ap") or "", row.get("rel_ap") or ""):
                    ap_rows.append([dp_key, src_label,
                                    f"{fmt_str(row.get('rpt_ap'))}/{fmt_str(row.get('rel_ap'))}",
                                    f"{rpt_ap}/{rel_ap}"])

                flown = mode == "actual" and duty.duty_date <= today
                if not flown:
                    continue
                warn = day_credit_check(duty)
                if warn:
                    credit_warnings.append(
                        f"{dp_key}: credit check {pairing.pairing_id} {duty.duty_date}: {warn}")
                if num_changed(row.get("acredit"), duty.day_credit_hours):
                    put(F.TABLE_DUTY_PERIODS, rid, F.F_DUTY_ACTUAL_CREDIT, duty.day_credit_hours)
                    dcredit_rows.append([dp_key, src_label, fmt_num(row.get("acredit")),
                                         f"{duty.day_credit_hours:g}"])
                target = ("Actual" if any(is_loggable_flight(leg) for leg in duty.legs)
                          else "Cancelled")
                if row.get("status") in ("Planned", "Actual") and row.get("status") != target:
                    put(F.TABLE_DUTY_PERIODS, rid, F.F_DUTY_STATUS, target)
                    status_rows.append([dp_key, "in actual file", str(row.get("status")),
                                        target, f"flights in Grist={row.get('nf')}"])

        # Trip cut short: Planned rows the actual file no longer contains.
        if src.actual:
            file_keys = {
                duty_period_key(p.pairing_id, p.start_date, d.duty_date)
                for p in src.actual for d in p.duty_days
            }
            trip_rows = [
                {"id": d["id"], "key": d["new_key"], "status": d.get("status"),
                 "date": d.get("date"), "nf": d.get("nf")}
                for d in duties_by_trip.get(int(src.grist_trip["id"]), [])
            ]
            for r in missing_days_to_cancel(trip_rows, file_keys, today):
                put(F.TABLE_DUTY_PERIODS, int(r["id"]), F.F_DUTY_STATUS, "Cancelled")
                status_rows.append([r["key"], "not in actual file", "Planned", "Cancelled",
                                    f"flights in Grist={r['nf']}"])

    print_table("Duty_Periods Report_Time / Release_Time",
                ["Duty_Period_Key", "source", "report before", "report after",
                 "release before", "release after", "duty bef", "duty aft", "sheet"], time_rows)
    for w in duty_warnings:
        print(f"  WARN: {w}")
    for m in missing_duty_rows:
        print(f"  duty day not in Grist (skipped): {m}")
    if duty_warnings or missing_duty_rows:
        print()
    print_table("Duty_Periods Report_Airport / Release_Airport",
                ["Duty_Period_Key", "source", "before", "after"], ap_rows)
    print_table("Duty_Periods Actual_Credit (Day Total)",
                ["Duty_Period_Key", "source", "before", "after"], dcredit_rows)
    print_table("Duty_Periods Status",
                ["Duty_Period_Key", "rule", "before", "after", "detail"], status_rows)

    # ── 3. Trips ──────────────────────────────────────────────────────────────
    tafb_rows, pb_rows, base_rows, tcredit_rows, end_rows = [], [], [], [], []
    trip_warnings: list[str] = []
    for trip_id, src in sorted(sources.items(), key=lambda kv: kv[1].key):
        t = src.grist_trip
        newest = src.newest
        newest_label = f"{'actual' if src.actual else 'planned'}:{newest.pairing_id}"
        if newest.tafb_hours:
            new_tafb = round(newest.tafb_hours, 2)
            if num_changed(t.get("tafb"), new_tafb):
                put(F.TABLE_TRIPS, trip_id, F.F_TRIP_TAFB, new_tafb)
                tafb_rows.append([src.key, newest_label, fmt_num(t.get("tafb")), fmt_num(new_tafb)])
        if src.planned:
            plan_file = src.planned[-1]
            new_pb = plan_file.block_hours
            if new_pb and num_changed(t.get("pblock"), new_pb):
                put(F.TABLE_TRIPS, trip_id, F.F_TRIP_PLANNED_BLOCK, new_pb)
                pb_rows.append([src.key, f"planned:{plan_file.pairing_id}",
                                fmt_num(t.get("pblock")), fmt_num(new_pb)])
        new_base = newest.first_origin
        if new_base and (t.get("base") or "") != new_base:
            put(F.TABLE_TRIPS, trip_id, F.F_TRIP_BASE, new_base)
            base_rows.append([src.key, newest_label, fmt_str(t.get("base")), new_base])
        if src.actual:
            act = src.actual[-1]
            act_label = f"actual:{act.pairing_id}"
            warn = trip_credit_check(act)
            if warn:
                trip_warnings.append(f"{src.key}: {warn}")
            if num_changed(t.get("acredit"), act.credit_hours):
                put(F.TABLE_TRIPS, trip_id, F.F_TRIP_ACTUAL_CREDIT, act.credit_hours)
                tcredit_rows.append([src.key, act_label, fmt_num(t.get("acredit")),
                                     f"{act.credit_hours:g}"])
            new_end = format_grist_date(act.end_date)
            if t.get("end_date") != new_end:
                put(F.TABLE_TRIPS, trip_id, F.F_TRIP_END_DATE, new_end)
                end_rows.append([src.key, act_label, fmt_date(t.get("end_date")),
                                 act.end_date.isoformat()])

    print_table("Trips TAFB", ["Trip_Key", "source", "before", "after"], tafb_rows)
    no_planned = sorted(s.key for s in sources.values() if not s.planned)
    if no_planned:
        print(f"  no planned file (Planned_Block left as-is): {', '.join(no_planned)}\n")
    print_table("Trips Planned_Block", ["Trip_Key", "source", "before", "after"], pb_rows)
    print_table("Trips Base (first schedule line origin)",
                ["Trip_Key", "source", "before", "after"], base_rows)
    print_table("Trips Actual_Credit (header Credit:)",
                ["Trip_Key", "source", "before", "after"], tcredit_rows)
    print_table("Trips End_Date (flown span)", ["Trip_Key", "source", "before", "after"], end_rows)

    # ── 4. Deadhead passengers ────────────────────────────────────────────────
    pax_rows = []
    for f in flights:
        if f.get("dh") and f.get("pax") not in (None, "", 0):
            put(F.TABLE_FLIGHTS, int(f["id"]), F.F_FLIGHT_PASSENGERS, 0)
            pax_rows.append([str(f["id"]), f["new_key"], fmt_num(f.get("pax")), "0"])
    print_table("Flights Passengers on deadheads", ["row id", "Import_Flight_Key", "before", "after"],
                pax_rows)

    # ── Placeholder Flight rows (report only) ─────────────────────────────────
    placeholder_rows: dict[int, list[str]] = {}
    for src in sources.values():
        for mode, exports in (("actual", src.actual), ("planned", src.planned)):
            for pairing in exports:
                for duty in pairing.duty_days:
                    for leg in duty.legs:
                        if is_loggable_flight(leg):
                            continue
                        k = import_flight_key(pairing.pairing_id, leg.duty_date or duty.duty_date,
                                              leg.flight, leg.origin, leg.destination, leg.departure)
                        f = flights_by_key.get(k)
                        if f is not None:
                            placeholder_rows.setdefault(int(f["id"]), [
                                str(f["id"]), k, str(f.get("num")), f"{f.get('dep')}-{f.get('arr')}",
                                fmt_num(f.get("block")), f"{mode}:{pairing.pairing_id}"])
    for f in flights:
        num = str(f.get("num") or "").strip().lstrip("*")
        if (num and not num.isdigit() and not f.get("block") and f.get("dep")
                and f.get("dep") == f.get("arr") and int(f["id"]) not in placeholder_rows):
            placeholder_rows[int(f["id"])] = [str(f["id"]), f["new_key"], num,
                                              f"{f.get('dep')}-{f.get('arr')}",
                                              fmt_num(f.get("block")), "grist-scan"]
    print_table("Placeholder Flight rows (listed only, never deleted)",
                ["row id", "Import_Flight_Key", "flight", "route", "block", "found via"],
                [placeholder_rows[k] for k in sorted(placeholder_rows)])

    # ── Warnings ──────────────────────────────────────────────────────────────
    print(f"=== R8 day credit warnings (Day Total < max(leg sum, 4:12)): {len(credit_warnings)} ===")
    for w in credit_warnings:
        print(f"  WARN: {w}")
    print()
    print(f"=== Trip credit warnings (header Credit != sum of Day Totals): {len(trip_warnings)} ===")
    for w in trip_warnings:
        print(f"  WARN: {w}")
    print()

    # ── Summary ───────────────────────────────────────────────────────────────
    formula_left = []
    for table, col in ((F.TABLE_TRIPS, F.F_TRIP_ACTUAL_CREDIT),
                       (F.TABLE_DUTY_PERIODS, F.F_DUTY_ACTUAL_CREDIT)):
        if col in client.formula_columns(table):
            formula_left.append(f"{table}.{col}")
    rows_touched = {t: len(u) for t, u in updates.items()}
    print("=" * 70)
    print("Change counts:")
    for label, n in (
        ("re-key Trips (Trip_Key + Pairing_ID)", rekey_counts[F.TABLE_TRIPS]),
        ("re-key Duty_Periods.Duty_Period_Key", rekey_counts[F.TABLE_DUTY_PERIODS]),
        ("re-key Flights.Import_Flight_Key", rekey_counts[F.TABLE_FLIGHTS]),
        ("re-key Import_Batch.Batch_Name", rekey_counts[F.TABLE_IMPORT_BATCH]),
        ("key collisions (rows)", len(coll_rows)),
        ("duty report/release times", len(time_rows)),
        ("duty report/release airports", len(ap_rows)),
        ("duty Actual_Credit", len(dcredit_rows)),
        ("duty Status", len(status_rows)),
        ("trip TAFB", len(tafb_rows)),
        ("trip Planned_Block", len(pb_rows)),
        ("trip Base", len(base_rows)),
        ("trip Actual_Credit", len(tcredit_rows)),
        ("trip End_Date", len(end_rows)),
        ("deadhead Passengers -> 0", len(pax_rows)),
        ("placeholder flights (listed only)", len(placeholder_rows)),
        ("R8 day credit warnings", len(credit_warnings)),
        ("trip credit warnings", len(trip_warnings)),
    ):
        print(f"  {label:<40} {n}")
    print("Rows to update (PATCH only): "
          + ", ".join(f"{t} {n}" for t, n in rows_touched.items()))
    print("Rows to create: 0    Rows to delete: 0")
    print("Row counts now: " + ", ".join(f"{t} {n}" for t, n in counts_before.items()))
    if formula_left:
        print(f"Still formula columns: {', '.join(formula_left)}")

    blockers = []
    if coll_rows:
        blockers.append(f"{len(coll_rows)} key-collision row(s) — resolve in Grist first")
    if formula_left:
        blockers.append(f"{', '.join(formula_left)} still formula — convert to data first")
    if dry_run:
        print("\nDRY RUN complete — no data was written.")
        if blockers:
            print("--commit is currently BLOCKED: " + "; ".join(blockers))
        return
    if blockers:
        sys.exit("ABORT (nothing written): " + "; ".join(blockers))

    for table, table_updates in updates.items():
        client.update_records(table, sorted(table_updates.items()))
    counts_after = client.row_counts()
    print("\nWrote: " + ", ".join(f"{t} {n} row(s)" for t, n in rows_touched.items()))
    print("Row counts after: " + ", ".join(f"{t} {n}" for t, n in counts_after.items()))
    if counts_after != counts_before:
        sys.exit("ERROR: row counts changed — investigate before continuing")
    print("Row counts unchanged.")


if __name__ == "__main__":
    main()
