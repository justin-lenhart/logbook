from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date, datetime, time
from enum import Enum

from logbook_import.models import ImportPlan


class _DryRunEncoder(json.JSONEncoder):
    def default(self, o: object) -> object:
        if isinstance(o, (date, datetime)):
            return o.isoformat()
        if isinstance(o, time):
            return o.strftime("%H:%M")
        if isinstance(o, Enum):
            return o.value
        return super().default(o)


def format_import_plan(plan: ImportPlan) -> str:
    payload = {
        "mode": plan.mode.value,
        "pairing_id": plan.pairing_id,
        "source_txt": plan.source_txt,
        "source_csv": plan.source_csv,
        "summary": {
            "trips": len(plan.trips),
            "duty_periods": len(plan.duty_periods),
            "flights": len(plan.flights),
        },
        "import_batch": asdict(plan.import_batch),
        "trips": [asdict(t) for t in plan.trips],
        "duty_periods": [asdict(d) for d in plan.duty_periods],
        "flights": [asdict(f) for f in plan.flights],
        "warnings": plan.warnings,
    }
    return json.dumps(payload, indent=2, cls=_DryRunEncoder)


def format_run_summary(
    plans: list[ImportPlan],
    inbox_warnings: list[str],
) -> str:
    lines = ["=== Logbook import dry-run ===", ""]
    for warning in inbox_warnings:
        lines.append(f"WARN: {warning}")
    if inbox_warnings:
        lines.append("")

    for plan in plans:
        lines.append(f"--- {plan.mode.value.upper()} import: {plan.pairing_id} ---")
        lines.append(f"  source: {plan.source_txt}")
        if plan.source_csv:
            lines.append(f"  csv:    {plan.source_csv}")
        lines.append(
            f"  batch:         {plan.import_batch.batch_name} "
            f"({plan.import_batch.import_type})"
        )
        lines.append(f"  trips:         {len(plan.trips)}")
        lines.append(f"  duty_periods: {len(plan.duty_periods)}")
        lines.append(f"  flights:       {len(plan.flights)} (would {'create' if plan.flights else 'skip'})")
        for warning in plan.warnings:
            lines.append(f"  WARN: {warning}")

        for trip in plan.trips:
            lines.append(
                f"  TRIP [{trip.status}] {trip.trip_key} "
                f"block={trip.planned_block} credit={trip.planned_credit} "
                f"duty_days={trip.planned_duty_periods} legs={trip.planned_legs}"
            )

        for duty in plan.duty_periods:
            lines.append(
                f"  DUTY [{duty.status}] {duty.duty_period_key} "
                f"date={duty.duty_date} block={duty.planned_block} "
                f"credit={duty.planned_credit} legs={duty.planned_legs}"
            )

        for flight in plan.flights:
            dh = " DH" if flight.deadhead else ""
            lines.append(
                f"  FLIGHT{dh} {flight.import_flight_key} "
                f"block={flight.block_hours} pic={flight.pic_hours} sic={flight.sic_hours} "
                f"ac={flight.aircraft_code} tail={flight.tail_number}"
            )
        lines.append("")

    lines.append("No Airtable writes performed (dry-run).")
    return "\n".join(lines)
