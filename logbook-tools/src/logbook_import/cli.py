from __future__ import annotations

import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import click

from logbook_import import airtable_fields as F
from logbook_import.airtable_airports import fetch_airport_index
from logbook_import.airport_map import (
    aggregate_route_stats,
    build_geojson,
    fetch_flight_records,
    resolve_airports,
)
from logbook_import.airtable_settings import load_airtable_settings
from logbook_import.airtable_sync import AirtableImporter, format_commit_summary
from logbook_import.config import RECORDED_DIR, WORKSPACE_ROOT, discover_pairing_file_sets, move_processed_files
from logbook_import.dry_run import format_run_summary
from logbook_import.import_planner import build_plans_for_exports
from logbook_import.models import CrewRole, ImportMode, Operator
from logbook_import.night_enrichment import compute_night_data
from logbook_import.parsers.merge import load_pairing_export


def _resolve_mode(command: str) -> ImportMode:
    if command == "import-planned":
        return ImportMode.PLANNED
    if command == "import-actual":
        return ImportMode.ACTUAL
    raise click.ClickException(f"Unknown command: {command}")


@click.group()
def main() -> None:
    """SkedPlus logbook importer."""


def _import_options(func):  # type: ignore[no-untyped-def]
    func = click.option(
        "--role",
        type=click.Choice(["pic", "sic"], case_sensitive=False),
        default="sic",
        show_default=True,
        help="Crew position flown; sets PIC/SIC time and Flight Position. Defaults to SIC.",
    )(func)
    func = click.option(
        "--operator",
        type=click.Choice(["skw"], case_sensitive=False),
        default="skw",
        show_default=True,
        help="Carrier the flying was performed for; sets Operation (Part 121) and Airline.",
    )(func)
    func = click.option("--dry-run", is_flag=True, default=False)(func)
    func = click.option("--commit", is_flag=True, default=False)(func)
    return func


@main.command("import-planned")
@_import_options
def import_planned(
    role: str,
    operator: str | None,
    dry_run: bool,
    commit: bool,
) -> None:
    """Import planned pairing data (no Flight rows)."""
    _run_import(ImportMode.PLANNED, role, operator, dry_run, commit)


@main.command("import-actual")
@_import_options
@click.option(
    "--update-map",
    "update_map",
    is_flag=True,
    default=False,
    help="After a successful --commit, regenerate map_data.geojson and push to GitHub.",
)
@click.option(
    "--update-apps",
    "update_apps",
    is_flag=True,
    default=False,
    help="After a successful --commit, regenerate the app reference pages and push to GitHub.",
)
@click.option(
    "--update-all",
    "update_all",
    is_flag=True,
    default=False,
    help="Shorthand for --update-map and --update-apps together.",
)
def import_actual(
    role: str,
    operator: str | None,
    dry_run: bool,
    commit: bool,
    update_map: bool,
    update_apps: bool,
    update_all: bool,
) -> None:
    """Import actual flown legs as Flight rows."""
    _run_import(
        ImportMode.ACTUAL,
        role,
        operator,
        dry_run,
        commit,
        update_map=update_map or update_all,
        update_apps=update_apps or update_all,
    )


def _run_import(
    mode: ImportMode,
    role: str,
    operator: str | None,
    dry_run: bool,
    commit: bool,
    update_map: bool = False,
    update_apps: bool = False,
) -> None:
    if dry_run and commit:
        raise click.ClickException("Use only one of --dry-run or --commit")
    if not dry_run and not commit:
        dry_run = True

    crew_role = CrewRole(role.lower())
    op = Operator(operator.lower()) if operator else None

    file_sets, inbox_warnings = discover_pairing_file_sets()
    if not file_sets:
        raise click.ClickException("No valid pairing file sets found in inbox/")

    pairings = []
    plan_warnings: list[str] = []
    for file_set in file_sets:
        pairing, warnings = load_pairing_export(file_set)
        pairings.append(pairing)
        plan_warnings.extend(warnings)

    # The planner needs the airport index up front to convert SkedPlus local
    # times to UTC.  Try to load it now; if Airtable isn't reachable (e.g. no
    # creds during dry-run), fall back to naive datetimes with a loud warning.
    try:
        settings = load_airtable_settings()
        airport_index = fetch_airport_index(settings.api_key, settings.base_id)
    except (ValueError, Exception) as exc:
        if not dry_run:
            raise click.ClickException(
                f"Cannot load Airtable airport index (needed for UTC conversion): {exc}"
            ) from exc
        settings = None
        airport_index = None
        plan_warnings.append(
            f"Could not load airport index — flight times will be NAIVE LOCAL, "
            f"NOT UTC.  Do not --commit until this is fixed: {exc}"
        )

    plans = build_plans_for_exports(
        pairings, mode, role=crew_role, operator=op, airport_index=airport_index
    )
    for plan in plans:
        plan_warnings.extend(plan.warnings)
    all_warnings = inbox_warnings + plan_warnings

    if dry_run:
        click.echo(format_run_summary(plans, all_warnings))
        if airport_index is not None:
            click.echo("\nMap data (current state — import not committed):")
            _update_map(settings, airport_index, push=False)
        return

    # Abort if any flight times could not be converted to UTC.  Naive datetimes
    # in the fallback path look valid to Airtable but store local time as UTC,
    # corrupting logbook data silently.
    if mode == ImportMode.ACTUAL:
        naive_warns = [w for w in all_warnings if "times left naive" in w]
        if naive_warns:
            for w in naive_warns:
                click.echo(f"ERROR: {w}", err=True)
            raise click.ClickException(
                "Aborting commit: one or more flight times could not be converted to UTC. "
                "Ensure all airports are in the Airports table with lat/lon before committing."
            )

    assert settings is not None  # we already raised above if not dry_run
    importer = AirtableImporter(
        settings,
        include_equipment_family=True,
        airport_index=airport_index,
    )
    results = [importer.sync_plan(plan) for plan in plans]
    summary = format_commit_summary(results)
    if all_warnings:
        warning_lines = "\n".join(f"WARN: {w}" for w in all_warnings)
        summary = f"{warning_lines}\n\n{summary}"
    click.echo(summary)

    dest_dir = RECORDED_DIR / mode.value
    moved = move_processed_files(plans, dest_dir)
    if moved:
        click.echo(f"\nMoved {len(moved)} file(s) to {dest_dir.relative_to(RECORDED_DIR.parent)}/")

    click.echo("\nMap data:")
    assert airport_index is not None
    _update_map(settings, airport_index, push=update_map)

    if update_apps:
        click.echo("\nApp reference pages:")
        _update_apps(settings, push=True)


def _update_map(settings: object, airport_index: dict, *, push: bool) -> None:
    """Show map stats and optionally write + commit + push map_data.geojson."""
    flight_records = fetch_flight_records(settings.api_key, settings.base_id, airport_index)  # type: ignore[attr-defined]
    if not flight_records:
        click.echo("  No qualifying flights found.")
        return

    route_stats = aggregate_route_stats(flight_records)
    resolved, missing = resolve_airports(route_stats, airport_index)
    for iata in missing:
        click.echo(f"  WARNING: Airport not found in Airports table: {iata}", err=True)

    click.echo(f"  {len(resolved)} airports · {len(route_stats)} routes")

    if not push:
        click.echo("  (run with --update-map to write and push to GitHub Pages)")
        return

    geojson = build_geojson(resolved, route_stats)
    output_path = WORKSPACE_ROOT / "docs" / "map_data.geojson"
    output_path.write_text(json.dumps(geojson, indent=2), encoding="utf-8")

    repo = str(WORKSPACE_ROOT)
    today = date.today().strftime("%Y-%m-%d")
    subprocess.run(["git", "-C", repo, "add", "docs/map_data.geojson"], check=True)
    diff = subprocess.run(["git", "-C", repo, "diff", "--cached", "--quiet"])
    if diff.returncode != 0:
        subprocess.run(
            ["git", "-C", repo, "commit", "-m", f"Update map data ({today})"],
            check=True,
        )
    else:
        click.echo("  Map data unchanged — skipping commit.")
    subprocess.run(["git", "-C", repo, "push", "--set-upstream", "origin", "HEAD"], check=True)
    click.echo(f"  Wrote {len(resolved)} airports, {len(route_stats)} routes → pushed to GitHub Pages.")


ALL_APP_PAGES = ["swa", "ual", "faa", "summary"]


def _render_app_pages(settings: object, out_dir: Path, wanted: list[str]) -> tuple[int, int]:
    """Generate the application reference HTML pages. Returns (n_flights, n_families)."""
    from datetime import datetime

    from pyairtable import Api

    from logbook_import import app_report as R

    out_dir.mkdir(parents=True, exist_ok=True)
    api = Api(settings.api_key)  # type: ignore[attr-defined]
    aircraft = api.table(settings.base_id, F.TABLE_AIRCRAFT).all(fields=[F.F_AIRCRAFT_CODE])  # type: ignore[attr-defined]
    ac_by_id = {r["id"]: r["fields"].get(F.F_AIRCRAFT_CODE) for r in aircraft}
    flights = api.table(settings.base_id, F.TABLE_FLIGHTS).all()  # type: ignore[attr-defined]

    rows = R.normalize(flights, ac_by_id)
    missing = [r for r in rows if not r.family]
    if missing:
        click.echo(
            f"  WARNING: {len(missing)} flight(s) have an aircraft with no family "
            f"mapping; excluded. Add them to app_families.AIRCRAFT_TO_FAMILY.",
            err=True,
        )

    aggs = R.aggregate(rows)
    generated = datetime.now().strftime("%Y-%m-%d %H:%M")
    for name in wanted:
        (out_dir / f"{name}.html").write_text(R.RENDERERS[name](aggs, generated), encoding="utf-8")
    return len(rows), len(aggs)


def _update_apps(settings: object, *, push: bool) -> None:
    """Regenerate the application reference pages and optionally commit + push."""
    out = WORKSPACE_ROOT / "docs" / "apps"
    n_flights, n_families = _render_app_pages(settings, out, ALL_APP_PAGES)
    click.echo(f"  {n_flights} flights · {n_families} families → {len(ALL_APP_PAGES)} pages")
    if not push:
        click.echo("  (run with --update-apps to commit and push to GitHub Pages)")
        return

    repo = str(WORKSPACE_ROOT)
    today = date.today().strftime("%Y-%m-%d")
    subprocess.run(["git", "-C", repo, "add", "docs/apps"], check=True)
    diff = subprocess.run(["git", "-C", repo, "diff", "--cached", "--quiet"])
    if diff.returncode != 0:
        subprocess.run(
            ["git", "-C", repo, "commit", "-m", f"Update app reference pages ({today})"],
            check=True,
        )
    else:
        click.echo("  App pages unchanged — skipping commit.")
    subprocess.run(["git", "-C", repo, "push", "--set-upstream", "origin", "HEAD"], check=True)
    click.echo("  App reference pages pushed to GitHub Pages.")


@main.command("export-map")
@click.option(
    "--output",
    "output_path",
    type=click.Path(path_type=Path),
    default=None,
    show_default=False,
    help="File path for GeoJSON output (default: docs/map_data.geojson in repo root).",
)
@click.option(
    "--update",
    "update",
    is_flag=True,
    default=False,
    help="After writing the file, commit and push to GitHub Pages.",
)
def export_map(output_path: Path | None, update: bool) -> None:
    """Export airport points and route lines as GeoJSON."""
    try:
        settings = load_airtable_settings()
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    resolved_output = output_path or (WORKSPACE_ROOT / "docs" / "map_data.geojson")

    airport_index = fetch_airport_index(settings.api_key, settings.base_id)
    flight_records = fetch_flight_records(settings.api_key, settings.base_id, airport_index)
    if not flight_records:
        raise click.ClickException("No qualifying flights found in Flights table")

    route_stats = aggregate_route_stats(flight_records)
    resolved, missing = resolve_airports(route_stats, airport_index)

    for iata in missing:
        click.echo(
            f"WARNING: Airport not found in Airports table: {iata}",
            err=True,
        )

    geojson = build_geojson(resolved, route_stats)
    resolved_output.write_text(json.dumps(geojson, indent=2), encoding="utf-8")

    n_airports = len(resolved)
    n_routes = len(route_stats)
    click.echo(f"Exported {n_airports} airports, {n_routes} routes → {resolved_output}")

    if update:
        repo = str(WORKSPACE_ROOT)
        today = date.today().strftime("%Y-%m-%d")
        subprocess.run(["git", "-C", repo, "add", "docs/map_data.geojson"], check=True)
        diff = subprocess.run(["git", "-C", repo, "diff", "--cached", "--quiet"])
        if diff.returncode != 0:
            subprocess.run(
                ["git", "-C", repo, "commit", "-m", f"Update map data ({today})"],
                check=True,
            )
            click.echo("Map data committed.")
        else:
            click.echo("Map data unchanged — skipping commit.")
        subprocess.run(["git", "-C", repo, "push", "--set-upstream", "origin", "HEAD"], check=True)
        click.echo("Pushed to GitHub Pages.")


@main.command("export-apps")
@click.option(
    "--output",
    "output_dir",
    type=click.Path(path_type=Path),
    default=None,
    show_default=False,
    help="Directory for HTML output (default: docs/apps in repo root).",
)
@click.option(
    "--page",
    "pages",
    type=click.Choice(["swa", "ual", "faa", "summary"], case_sensitive=False),
    multiple=True,
    help="Limit to specific page(s). Default: all.",
)
@click.option(
    "--update",
    "update",
    is_flag=True,
    default=False,
    help="After writing, commit and push docs/apps to GitHub Pages.",
)
def export_apps(output_dir: Path | None, pages: tuple[str, ...], update: bool) -> None:
    """Generate airline/FAA application reference pages (SWA, UAL, FAA, Summary)."""
    try:
        settings = load_airtable_settings()
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    out = output_dir or (WORKSPACE_ROOT / "docs" / "apps")
    wanted = [p.lower() for p in pages] or ALL_APP_PAGES

    n_flights, n_families = _render_app_pages(settings, out, wanted)
    for name in wanted:
        click.echo(f"Wrote {out / f'{name}.html'}")
    click.echo(
        f"Done — {n_flights} flights across {n_families} families. "
        f"Open the HTML files or embed them as Airtable custom blocks."
    )

    if update:
        repo = str(WORKSPACE_ROOT)
        today = date.today().strftime("%Y-%m-%d")
        subprocess.run(["git", "-C", repo, "add", "docs/apps"], check=True)
        diff = subprocess.run(["git", "-C", repo, "diff", "--cached", "--quiet"])
        if diff.returncode != 0:
            subprocess.run(
                ["git", "-C", repo, "commit", "-m", f"Update app reference pages ({today})"],
                check=True,
            )
            click.echo("App pages committed.")
        else:
            click.echo("App pages unchanged — skipping commit.")
        subprocess.run(["git", "-C", repo, "push", "--set-upstream", "origin", "HEAD"], check=True)
        click.echo("Pushed to GitHub Pages.")


@main.command("enrich-night")
@click.option("--commit", is_flag=True, default=False, help="Write to Airtable (default: dry run).")
def enrich_night(commit: bool) -> None:
    """Compute and write Night Time, Day Landing, Night Landing for existing Flight records."""
    try:
        settings = load_airtable_settings()
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    from pyairtable import Api

    api = Api(settings.api_key)
    base = api.base(settings.base_id)
    flights_table = base.table(F.TABLE_FLIGHTS)

    click.echo("Loading airport index…")
    airport_index = fetch_airport_index(settings.api_key, settings.base_id)

    click.echo("Fetching flight records…")
    all_records = flights_table.all(
        fields=[
            F.F_IMPORT_FLIGHT_KEY,
            F.F_FLIGHT_DEPARTURE,
            F.F_FLIGHT_ARRIVAL,
            F.F_FLIGHT_OUT_TIME,
            F.F_FLIGHT_IN_TIME,
            F.F_FLIGHT_NIGHT_TIME,
            F.F_FLIGHT_DEADHEAD,
        ]
    )

    # Group all records by pairing (first component of Import Flight Key) so we
    # can establish correct leg numbers before filtering to unenriched records.
    from collections import defaultdict

    pairing_groups: dict[str, list[dict]] = defaultdict(list)
    skipped_no_key = 0
    for rec in all_records:
        key = rec.get("fields", {}).get(F.F_IMPORT_FLIGHT_KEY)
        if not key:
            skipped_no_key += 1
            continue
        parts = key.split("|")
        pairing = parts[0]
        pairing_groups[pairing].append(rec)

    if skipped_no_key:
        click.echo(f"  WARN: {skipped_no_key} record(s) have no Import Flight Key — skipped.")

    # Build the enrichment payload, assigning leg numbers within each pairing.
    updates: list[dict] = []
    warnings: list[str] = []

    for pairing, records in sorted(pairing_groups.items()):
        sorted_records = sorted(
            records,
            key=lambda r: (
                (r["fields"].get(F.F_IMPORT_FLIGHT_KEY) or "").split("|")[1],  # date
                (r["fields"].get(F.F_IMPORT_FLIGHT_KEY) or "").split("|")[5] if len((r["fields"].get(F.F_IMPORT_FLIGHT_KEY) or "").split("|")) > 5 else "",  # hhmm
            ),
        )

        leg_counter = 0
        for rec in sorted_records:
            fields = rec.get("fields", {})
            deadhead = bool(fields.get(F.F_FLIGHT_DEADHEAD, False))

            if not deadhead:
                leg_counter += 1
                gets_credit = (leg_counter % 2 == 0)
            else:
                gets_credit = False

            if fields.get(F.F_FLIGHT_NIGHT_TIME) is not None:
                continue  # already enriched — idempotent skip

            origin_iata = str(fields.get(F.F_FLIGHT_DEPARTURE) or "").strip().upper()
            dest_iata = str(fields.get(F.F_FLIGHT_ARRIVAL) or "").strip().upper()
            out_raw = fields.get(F.F_FLIGHT_OUT_TIME)
            in_raw = fields.get(F.F_FLIGHT_IN_TIME)
            import_key = fields.get(F.F_IMPORT_FLIGHT_KEY, "?")

            if not origin_iata or not dest_iata:
                warnings.append(f"Missing airport code on {import_key} — skipped")
                continue
            if not out_raw or not in_raw:
                warnings.append(f"Missing time on {import_key} — skipped")
                continue

            origin = airport_index.get(origin_iata)
            dest = airport_index.get(dest_iata)
            if not origin:
                warnings.append(f"Airport not found: {origin_iata} on {import_key} — skipped")
                continue
            if not dest:
                warnings.append(f"Airport not found: {dest_iata} on {import_key} — skipped")
                continue

            from datetime import datetime, timezone

            def _parse_utc(s: str) -> datetime:
                dt = datetime.fromisoformat(s)
                if dt.tzinfo is None:
                    return dt.replace(tzinfo=timezone.utc)
                return dt

            try:
                out_utc = _parse_utc(str(out_raw))
                in_utc = _parse_utc(str(in_raw))
            except ValueError as exc:
                warnings.append(f"Cannot parse time on {import_key}: {exc} — skipped")
                continue

            try:
                night_hours, day_landing, night_landing = compute_night_data(
                    out_utc, in_utc,
                    origin["lat"], origin["lon"],
                    dest["lat"], dest["lon"],
                    gets_credit,
                )
            except Exception as exc:
                warnings.append(f"Night computation failed for {import_key}: {exc} — skipped")
                continue

            updates.append({
                "record_id": rec["id"],
                "import_key": import_key,
                "origin": origin_iata,
                "dest": dest_iata,
                "out_time": out_utc,
                "in_time": in_utc,
                "leg": leg_counter,
                "gets_credit": gets_credit,
                "night_hours": night_hours,
                "day_landing": day_landing,
                "night_landing": night_landing,
            })

    for warn in warnings:
        click.echo(f"WARN: {warn}")

    total_records = len(all_records) - skipped_no_key
    already_enriched = total_records - sum(
        1 for rec in all_records
        if rec.get("fields", {}).get(F.F_IMPORT_FLIGHT_KEY)
        and rec.get("fields", {}).get(F.F_FLIGHT_NIGHT_TIME) is None
    )

    if not commit:
        click.echo(f"\n=== enrich-night dry run ===")
        click.echo(f"Found {total_records} qualifying record(s). {len(updates)} need enrichment.\n")
        for u in updates:
            click.echo(
                f"  {u['import_key']}"
                f"  {u['origin']}→{u['dest']}"
                f"  {u['out_time'].strftime('%Y-%m-%dT%H:%MZ')} → {u['in_time'].strftime('%Y-%m-%dT%H:%MZ')}"
            )
            click.echo(
                f"    Night: {u['night_hours']}h"
                f"  Day Landing: {u['day_landing']}"
                f"  Night Landing: {u['night_landing']}"
                f"  (leg {u['leg']}, credit={'Y' if u['gets_credit'] else 'N'})"
            )
        click.echo(f"\nRun with --commit to write {len(updates)} record(s) to Airtable.")
        return

    if not updates:
        click.echo("Nothing to enrich.")
        return

    payloads = [
        {
            "id": u["record_id"],
            "fields": {
                F.F_FLIGHT_NIGHT_TIME: u["night_hours"],
                F.F_FLIGHT_DAY_LANDING: u["day_landing"],
                F.F_FLIGHT_NIGHT_LANDING: u["night_landing"],
            },
        }
        for u in updates
    ]
    flights_table.batch_update(payloads, typecast=True)
    click.echo(f"Updated {len(updates)} flight(s) with night time and landing data.")


@main.command("backfill-passengers")
@click.option(
    "--source",
    type=click.Choice(["actual", "planned"], case_sensitive=False),
    default="actual",
    show_default=True,
    help="Which recorded/ subfolder to read txt exports from.",
)
@click.option("--commit", is_flag=True, default=False, help="Write to Airtable (default: dry run).")
def backfill_passengers(source: str, commit: bool) -> None:
    """Backfill the Passengers field on existing Flight records from recorded txt files.

    Re-parses the archived SkedPlus exports, derives each leg's Import Flight Key the
    same way the importer does, and updates the matching Flight record's Passengers
    value. Idempotent: only records whose value actually differs are written.
    """
    try:
        settings = load_airtable_settings()
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    source_dir = RECORDED_DIR / source.lower()
    file_sets, discover_warnings = discover_pairing_file_sets(source_dir)
    if not file_sets:
        raise click.ClickException(f"No pairing file sets found in {source_dir}")

    # Airport index is needed by the planner for UTC time conversion. We don't use
    # the times here, but loading it keeps the derived Import Flight Keys identical
    # to a real import and avoids noisy naive-time warnings.
    airport_index = fetch_airport_index(settings.api_key, settings.base_id)

    pairings = []
    warnings: list[str] = list(discover_warnings)
    for file_set in file_sets:
        pairing, warns = load_pairing_export(file_set)
        pairings.append(pairing)
        warnings.extend(warns)

    plans = build_plans_for_exports(
        pairings, ImportMode.ACTUAL, airport_index=airport_index
    )

    # Desired Passengers value per Import Flight Key, derived from the txt exports.
    desired: dict[str, int] = {}
    for plan in plans:
        for flight in plan.flights:
            desired[flight.import_flight_key] = flight.passengers

    from pyairtable import Api

    api = Api(settings.api_key)
    flights_table = api.base(settings.base_id).table(F.TABLE_FLIGHTS)

    click.echo("Fetching flight records…")
    records = flights_table.all(
        fields=[F.F_IMPORT_FLIGHT_KEY, F.F_FLIGHT_PASSENGERS]
    )
    record_by_key = {
        rec["fields"].get(F.F_IMPORT_FLIGHT_KEY): rec
        for rec in records
        if rec.get("fields", {}).get(F.F_IMPORT_FLIGHT_KEY)
    }

    updates: list[dict] = []
    unmatched: list[str] = []
    unchanged = 0
    for key, passengers in sorted(desired.items()):
        rec = record_by_key.get(key)
        if rec is None:
            unmatched.append(key)
            continue
        current = rec["fields"].get(F.F_FLIGHT_PASSENGERS)
        if current == passengers:
            unchanged += 1
            continue
        updates.append(
            {
                "id": rec["id"],
                "fields": {F.F_FLIGHT_PASSENGERS: passengers},
                "_key": key,
                "_from": current,
                "_to": passengers,
            }
        )

    for warn in warnings:
        click.echo(f"WARN: {warn}")
    for key in unmatched:
        click.echo(f"WARN: no Flight record found for Import Flight Key: {key}")

    click.echo(
        f"\n{len(desired)} leg(s) across {len(plans)} file(s): "
        f"{len(updates)} to update, {unchanged} already correct, "
        f"{len(unmatched)} unmatched."
    )

    if not commit:
        for u in updates:
            click.echo(f"  {u['_key']}  {u['_from']} → {u['_to']}")
        click.echo(f"\nRun with --commit to write {len(updates)} record(s) to Airtable.")
        return

    if not updates:
        click.echo("Nothing to update.")
        return

    payloads = [{"id": u["id"], "fields": u["fields"]} for u in updates]
    flights_table.batch_update(payloads, typecast=True)
    click.echo(f"Updated Passengers on {len(updates)} flight(s).")


if __name__ == "__main__":
    try:
        main(standalone_mode=True)
    except click.ClickException as exc:
        click.echo(str(exc), err=True)
        sys.exit(1)
