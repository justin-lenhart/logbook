from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import click

from logbook_import import airtable_fields as F
from logbook_import.airtable_airports import fetch_airport_index
from logbook_import.airport_map import (
    build_geojson,
    fetch_flight_airport_pairs,
    resolve_airports,
)
from logbook_import.airtable_settings import load_airtable_settings
from logbook_import.airtable_sync import AirtableImporter, format_commit_summary
from logbook_import.config import RECORDED_DIR, discover_pairing_file_sets, move_processed_files
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
        required=True,
    )(func)
    func = click.option(
        "--operator",
        type=click.Choice(["skw"], case_sensitive=False),
        default=None,
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
def import_actual(
    role: str,
    operator: str | None,
    dry_run: bool,
    commit: bool,
) -> None:
    """Import actual flown legs as Flight rows."""
    _run_import(ImportMode.ACTUAL, role, operator, dry_run, commit)


def _run_import(
    mode: ImportMode,
    role: str,
    operator: str | None,
    dry_run: bool,
    commit: bool,
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


@main.command("export-map")
@click.option(
    "--output",
    "output_path",
    type=click.Path(path_type=Path),
    default="map_data.geojson",
    show_default=True,
    help="File path for GeoJSON output.",
)
def export_map(output_path: Path) -> None:
    """Export airport points and route lines as GeoJSON."""
    try:
        settings = load_airtable_settings()
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    flight_pairs = fetch_flight_airport_pairs(settings.api_key, settings.base_id)
    if not flight_pairs:
        raise click.ClickException("No qualifying flights found in Flights table")

    airport_index = fetch_airport_index(settings.api_key, settings.base_id)
    resolved, valid_pairs, missing = resolve_airports(flight_pairs, airport_index)

    for iata in missing:
        click.echo(
            f"WARNING: Airport not found in Airports table: {iata}",
            err=True,
        )

    pair_counts = Counter(
        tuple(sorted((origin, dest))) for origin, dest in flight_pairs
    )
    valid_pairs_with_counts = [(pair, pair_counts[pair]) for pair in valid_pairs]

    geojson = build_geojson(resolved, valid_pairs_with_counts)
    output_path.write_text(json.dumps(geojson, indent=2), encoding="utf-8")

    n_airports = len(resolved)
    n_routes = len(valid_pairs)
    click.echo(f"Exported {n_airports} airports, {n_routes} routes → {output_path}")


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


if __name__ == "__main__":
    try:
        main(standalone_mode=True)
    except click.ClickException as exc:
        click.echo(str(exc), err=True)
        sys.exit(1)
