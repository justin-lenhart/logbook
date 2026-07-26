"""Grist import sync — mirrors ``airtable_sync.AirtableImporter`` exactly.

Differences from the Airtable backend, all consequences of the Grist schema:
- Reference columns take a single int row id (not a one-element list).
- The Import Batch link lists (Imported Trips/Flights, Duty Periods) are
  FORMULA columns in Grist — they compute from the children's Import_Batch
  references, so this importer never writes them.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from logbook_import import grist_fields as F
from logbook_import.airtable_sync import PlanSyncResult, TableUpsertCounts
from logbook_import.grist_airports import fetch_airport_index
from logbook_import.grist_client import GristClient, UpsertResult
from logbook_import.grist_mapper import (
    map_duty_period_fields,
    map_flight_fields,
    map_import_batch_fields,
    map_trip_fields,
)
from logbook_import.grist_settings import GristSettings
from logbook_import.models import ImportMode, ImportPlan
from logbook_import.night_enrichment import compute_night_data


def _counts(result: UpsertResult) -> TableUpsertCounts:
    return TableUpsertCounts(created=result.created, updated=result.updated)


class GristImporter:
    """Upserts import plans into the logbook Grist doc."""

    def __init__(
        self,
        settings: GristSettings,
        *,
        include_equipment_family: bool = False,
        airport_index: dict[str, dict] | None = None,
        client: GristClient | None = None,
    ) -> None:
        self._settings = settings
        self._include_equipment_family = include_equipment_family
        self._client = client if client is not None else GristClient(settings)
        self._airport_index = (
            airport_index
            if airport_index is not None
            else fetch_airport_index(self._client)
        )

    def _load_aircraft_index(self) -> dict[str, int]:
        rows = self._client.sql(
            f'SELECT id, "{F.F_AIRCRAFT_CODE}" FROM "{F.TABLE_AIRCRAFT}" '
            f'WHERE "{F.F_AIRCRAFT_CODE}" IS NOT NULL'
        )
        return {
            str(r[F.F_AIRCRAFT_CODE]): int(r["id"])
            for r in rows
            if r.get(F.F_AIRCRAFT_CODE)
        }

    def sync_plan(self, plan: ImportPlan) -> PlanSyncResult:
        imported_at = datetime.now().astimezone()
        warnings = list(plan.warnings)
        aircraft_index = self._load_aircraft_index()

        batch_fields = map_import_batch_fields(plan.import_batch, imported_at=imported_at)
        batch_result = self._client.upsert_by_key(
            F.TABLE_IMPORT_BATCH, [batch_fields], F.F_BATCH_NAME
        )
        batch_id = batch_result.key_to_id.get(plan.import_batch.batch_name)
        if not batch_id:
            raise RuntimeError(f"Import batch upsert returned no row for {plan.pairing_id}")

        trip_payloads = [
            {
                **map_trip_fields(
                    trip,
                    mode=plan.mode,
                    include_equipment_family=self._include_equipment_family,
                ),
                F.F_TRIP_IMPORT_BATCH: batch_id,
            }
            for trip in plan.trips
        ]
        trip_result = self._client.upsert_by_key(
            F.TABLE_TRIPS, trip_payloads, F.F_TRIP_KEY
        )
        trip_ids = trip_result.key_to_id
        trip_counts = _counts(trip_result)

        # An actual import that *creates* (rather than updates) its trip means no
        # planned trip matched — so Planned Block/Credit stay empty. This is the
        # E3436D case: a trip picked up after the start-of-month planned import.
        # Surface it instead of letting the planned fields silently go blank.
        if plan.mode == ImportMode.ACTUAL and trip_counts.created:
            for trip in plan.trips:
                warnings.append(
                    f"No planned trip matched {trip.trip_key} ({plan.pairing_id}); "
                    f"created a new Actual trip with empty Planned Block/Credit. "
                    f"Backfill from the crew pay report if this trip was flown."
                )

        duty_payloads = []
        for duty in plan.duty_periods:
            trip_id = trip_ids.get(duty.trip_key)
            if not trip_id:
                warnings.append(
                    f"Skipping duty period {duty.duty_period_key}: trip {duty.trip_key} not found"
                )
                continue
            duty_payloads.append(
                {
                    **map_duty_period_fields(duty, mode=plan.mode),
                    F.F_DUTY_TRIPS: trip_id,
                    F.F_DUTY_IMPORT_BATCH: batch_id,
                }
            )
        duty_result = self._client.upsert_by_key(
            F.TABLE_DUTY_PERIODS, duty_payloads, F.F_DUTY_PERIOD_KEY
        )
        duty_ids = duty_result.key_to_id
        duty_counts = _counts(duty_result)

        flight_payloads = []
        for flight in plan.flights:
            trip_id = trip_ids.get(flight.trip_key)
            duty_id = duty_ids.get(flight.duty_period_key)
            if not trip_id:
                warnings.append(
                    f"Skipping flight {flight.import_flight_key}: trip {flight.trip_key} not found"
                )
                continue
            if not duty_id:
                warnings.append(
                    f"Skipping flight {flight.import_flight_key}: "
                    f"duty period {flight.duty_period_key} not found"
                )
                continue
            fields: dict[str, Any] = {
                **map_flight_fields(flight),
                F.F_FLIGHT_TRIPS: trip_id,
                F.F_FLIGHT_DUTY_PERIOD: duty_id,
                F.F_FLIGHT_IMPORT_BATCH: batch_id,
            }
            if flight.aircraft_code:
                aircraft_id = aircraft_index.get(flight.aircraft_code)
                if aircraft_id:
                    fields[F.F_FLIGHT_AIRCRAFT] = aircraft_id
                else:
                    warnings.append(
                        f"Flight {flight.import_flight_key}: unknown aircraft code "
                        f"{flight.aircraft_code!r}; Aircraft link omitted"
                    )

            dep_id = self._airport_index.get(flight.origin, {}).get("record_id")
            arr_id = self._airport_index.get(flight.destination, {}).get("record_id")
            if dep_id:
                fields[F.F_FLIGHT_DEPARTURE] = dep_id
            else:
                warnings.append(
                    f"Flight {flight.import_flight_key}: airport {flight.origin!r} "
                    f"not in index; Departure Airport link omitted"
                )
            if arr_id:
                fields[F.F_FLIGHT_ARRIVAL] = arr_id
            else:
                warnings.append(
                    f"Flight {flight.import_flight_key}: airport {flight.destination!r} "
                    f"not in index; Arrival Airport link omitted"
                )

            flight_payloads.append(fields)

        flight_result = self._client.upsert_by_key(
            F.TABLE_FLIGHTS, flight_payloads, F.F_IMPORT_FLIGHT_KEY
        )
        flight_key_index = flight_result.key_to_id
        flight_counts = _counts(flight_result)

        # Enrich night time and landing data for actual-mode imports.
        night_enriched = 0
        if plan.mode == ImportMode.ACTUAL:
            night_updates: list[tuple[int, dict[str, Any]]] = []
            leg_counter = 0
            for flight in plan.flights:
                if flight.deadhead:
                    gets_credit = False
                else:
                    leg_counter += 1
                    gets_credit = (leg_counter % 2 == 0)

                record_id = flight_key_index.get(flight.import_flight_key)
                if not record_id:
                    continue

                origin = self._airport_index.get(flight.origin)
                dest = self._airport_index.get(flight.destination)
                if not origin or not dest:
                    warnings.append(
                        f"Night enrichment: airport not found for {flight.import_flight_key} "
                        f"({flight.origin}/{flight.destination}) — skipped"
                    )
                    continue

                # Times from the planner are timezone-aware UTC; if a fallback
                # path produced a naive datetime, attach UTC.
                out_utc = (
                    flight.out_time
                    if flight.out_time.tzinfo is not None
                    else flight.out_time.replace(tzinfo=timezone.utc)
                )
                in_utc = (
                    flight.in_time
                    if flight.in_time.tzinfo is not None
                    else flight.in_time.replace(tzinfo=timezone.utc)
                )

                try:
                    night_hours, day_landing, night_landing = compute_night_data(
                        out_utc, in_utc,
                        origin["lat"], origin["lon"],
                        dest["lat"], dest["lon"],
                        gets_credit,
                    )
                except Exception as exc:
                    warnings.append(
                        f"Night computation failed for {flight.import_flight_key}: {exc} — skipped"
                    )
                    continue

                night_updates.append((
                    record_id,
                    {
                        F.F_FLIGHT_NIGHT_TIME: night_hours,
                        F.F_FLIGHT_DAY_LANDING: day_landing,
                        F.F_FLIGHT_NIGHT_LANDING: night_landing,
                    },
                ))

            if night_updates:
                self._client.update_records(F.TABLE_FLIGHTS, night_updates)
                night_enriched = len(night_updates)

        # NOTE: no batch link-list update here — in Grist, Import Batch's
        # Imported Trips / Duty Periods / Imported Flights are reverse-lookup
        # formulas over the children's Import_Batch refs set above.

        return PlanSyncResult(
            pairing_id=plan.pairing_id,
            batch_record_id=str(batch_id),
            batch_name=plan.import_batch.batch_name,
            trips=trip_counts,
            duty_periods=duty_counts,
            flights=flight_counts,
            night_enriched=night_enriched,
            warnings=warnings,
        )


def format_commit_summary(results: list[PlanSyncResult]) -> str:
    lines = ["=== Grist import commit ===", ""]
    for result in results:
        lines.append(f"--- {result.pairing_id} ---")
        lines.append(f"  batch: {result.batch_name} (row {result.batch_record_id})")
        lines.append(
            f"  trips:         {result.trips.created} created, "
            f"{result.trips.updated} updated"
        )
        lines.append(
            f"  duty_periods: {result.duty_periods.created} created, "
            f"{result.duty_periods.updated} updated"
        )
        lines.append(
            f"  flights:       {result.flights.created} created, "
            f"{result.flights.updated} updated"
        )
        if result.night_enriched:
            lines.append(f"  night enriched: {result.night_enriched} flight(s)")
        for warning in result.warnings:
            lines.append(f"  WARN: {warning}")
        lines.append("")
    return "\n".join(lines).rstrip()
