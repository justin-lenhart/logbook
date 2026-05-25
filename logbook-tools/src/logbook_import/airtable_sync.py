from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from pyairtable import Api

from logbook_import import airtable_fields as F
from logbook_import.airtable_airports import fetch_airport_index
from logbook_import.airtable_mapper import (
    map_duty_period_fields,
    map_flight_fields,
    map_import_batch_fields,
    map_trip_fields,
)
from logbook_import.airtable_settings import AirtableSettings
from logbook_import.models import ImportMode, ImportPlan
from logbook_import.night_enrichment import compute_night_data


@dataclass
class TableUpsertCounts:
    created: int = 0
    updated: int = 0


@dataclass
class PlanSyncResult:
    pairing_id: str
    batch_record_id: str
    batch_name: str
    trips: TableUpsertCounts = field(default_factory=TableUpsertCounts)
    duty_periods: TableUpsertCounts = field(default_factory=TableUpsertCounts)
    flights: TableUpsertCounts = field(default_factory=TableUpsertCounts)
    night_enriched: int = 0
    warnings: list[str] = field(default_factory=list)


def _count_upsert(result: dict[str, Any]) -> TableUpsertCounts:
    return TableUpsertCounts(
        created=len(result.get("createdRecords", [])),
        updated=len(result.get("updatedRecords", [])),
    )


def _index_records_by_field(
    records: list[dict[str, Any]],
    field_name: str,
) -> dict[str, str]:
    index: dict[str, str] = {}
    for record in records:
        value = record.get("fields", {}).get(field_name)
        if value:
            index[str(value)] = record["id"]
    return index


def _load_aircraft_index(api: Api, settings: AirtableSettings) -> dict[str, str]:
    table = api.base(settings.base_id).table(F.TABLE_AIRCRAFT)
    records = table.all(fields=[F.F_AIRCRAFT_CODE])
    index: dict[str, str] = {}
    for record in records:
        code = record.get("fields", {}).get(F.F_AIRCRAFT_CODE)
        if code:
            index[str(code)] = record["id"]
    return index


def _upsert_records(
    table: Any,
    payloads: list[dict[str, Any]],
    key_field: str,
) -> tuple[dict[str, Any], dict[str, str]]:
    if not payloads:
        return {"createdRecords": [], "updatedRecords": [], "records": []}, {}
    records = [{"fields": fields} for fields in payloads]
    result = table.batch_upsert(records, key_fields=[key_field], typecast=True)
    key_index = _index_records_by_field(result.get("records", []), key_field)
    return result, key_index


class AirtableImporter:
    """Upserts import plans into the logbook Airtable base."""

    def __init__(
        self,
        settings: AirtableSettings,
        *,
        include_equipment_family: bool = False,
        airport_index: dict[str, dict] | None = None,
    ) -> None:
        self._settings = settings
        self._include_equipment_family = include_equipment_family
        self._api = Api(settings.api_key)
        self._base = self._api.base(settings.base_id)
        self._airport_index = (
            airport_index
            if airport_index is not None
            else fetch_airport_index(settings.api_key, settings.base_id)
        )

    def sync_plan(self, plan: ImportPlan) -> PlanSyncResult:
        imported_at = datetime.now().astimezone()
        warnings = list(plan.warnings)
        aircraft_index = _load_aircraft_index(self._api, self._settings)

        batch_table = self._base.table(F.TABLE_IMPORT_BATCH)
        batch_fields = map_import_batch_fields(plan.import_batch, imported_at=imported_at)
        batch_result, _ = _upsert_records(batch_table, [batch_fields], F.F_BATCH_NAME)
        batch_records = batch_result.get("records", [])
        if not batch_records:
            raise RuntimeError(f"Import batch upsert returned no records for {plan.pairing_id}")
        batch_id = batch_records[0]["id"]

        trips_table = self._base.table(F.TABLE_TRIPS)
        trip_payloads = [
            {
                **map_trip_fields(
                    trip,
                    mode=plan.mode,
                    include_equipment_family=self._include_equipment_family,
                ),
                F.F_TRIP_IMPORT_BATCH: [batch_id],
            }
            for trip in plan.trips
        ]
        trip_result, trip_ids = _upsert_records(trips_table, trip_payloads, F.F_TRIP_KEY)
        trip_counts = _count_upsert(trip_result)

        duty_table = self._base.table(F.TABLE_DUTY_PERIODS)
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
                    F.F_DUTY_TRIPS: [trip_id],
                    F.F_DUTY_IMPORT_BATCH: [batch_id],
                }
            )
        duty_result, duty_ids = _upsert_records(
            duty_table, duty_payloads, F.F_DUTY_PERIOD_KEY
        )
        duty_counts = _count_upsert(duty_result)

        flights_table = self._base.table(F.TABLE_FLIGHTS)
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
            fields = {
                **map_flight_fields(flight),
                F.F_FLIGHT_TRIPS: [trip_id],
                F.F_FLIGHT_DUTY_PERIOD: [duty_id],
                F.F_FLIGHT_IMPORT_BATCH: [batch_id],
            }
            if flight.aircraft_code:
                aircraft_id = aircraft_index.get(flight.aircraft_code)
                if aircraft_id:
                    fields[F.F_FLIGHT_AIRCRAFT] = [aircraft_id]
                else:
                    warnings.append(
                        f"Flight {flight.import_flight_key}: unknown aircraft code "
                        f"{flight.aircraft_code!r}; Aircraft link omitted"
                    )

            dep_id = self._airport_index.get(flight.origin, {}).get("record_id")
            arr_id = self._airport_index.get(flight.destination, {}).get("record_id")
            if dep_id:
                fields[F.F_FLIGHT_DEPARTURE] = [dep_id]
            else:
                warnings.append(
                    f"Flight {flight.import_flight_key}: airport {flight.origin!r} "
                    f"not in index; Departure Airport link omitted"
                )
            if arr_id:
                fields[F.F_FLIGHT_ARRIVAL] = [arr_id]
            else:
                warnings.append(
                    f"Flight {flight.import_flight_key}: airport {flight.destination!r} "
                    f"not in index; Arrival Airport link omitted"
                )

            flight_payloads.append(fields)

        flight_result, flight_key_index = _upsert_records(
            flights_table, flight_payloads, F.F_IMPORT_FLIGHT_KEY
        )
        flight_counts = _count_upsert(flight_result)

        # Enrich night time and landing data for actual-mode imports.
        night_enriched = 0
        if plan.mode == ImportMode.ACTUAL:
            night_payloads: list[dict[str, Any]] = []
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

                night_payloads.append({
                    "id": record_id,
                    "fields": {
                        F.F_FLIGHT_NIGHT_TIME: night_hours,
                        F.F_FLIGHT_DAY_LANDING: day_landing,
                        F.F_FLIGHT_NIGHT_LANDING: night_landing,
                    },
                })

            if night_payloads:
                flights_table.batch_update(night_payloads, typecast=True)
                night_enriched = len(night_payloads)

        trip_record_ids = list(trip_ids.values())
        duty_record_ids = list(duty_ids.values())
        flight_record_ids = [
            record["id"] for record in flight_result.get("records", [])
        ]
        batch_table.update(
            batch_id,
            {
                F.F_BATCH_IMPORTED_TRIPS: trip_record_ids,
                F.F_BATCH_DUTY_PERIODS: duty_record_ids,
                F.F_BATCH_IMPORTED_FLIGHTS: flight_record_ids,
            },
            typecast=True,
        )

        return PlanSyncResult(
            pairing_id=plan.pairing_id,
            batch_record_id=batch_id,
            batch_name=plan.import_batch.batch_name,
            trips=trip_counts,
            duty_periods=duty_counts,
            flights=flight_counts,
            night_enriched=night_enriched,
            warnings=warnings,
        )


def format_commit_summary(results: list[PlanSyncResult]) -> str:
    lines = ["=== Airtable import commit ===", ""]
    for result in results:
        lines.append(f"--- {result.pairing_id} ---")
        lines.append(f"  batch: {result.batch_name} ({result.batch_record_id})")
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
