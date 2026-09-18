"""Write parsed RSR system-wide metrics to the Grist ``RSR_Metrics`` table.

One row per Scope|Fleet|Data_Month (``Key``). Reports overlap (13-month rolling
history), so rows are merged before writing: per metric, the newest report
with a value wins, except that a report's oldest (year-ago) column only fills
gaps — every bad value seen so far sat in that column. That rule also holds
across runs: a month known only from an oldest column is not written over a
row Grist already has. Blank values are never sent, so a report that lacks a
month (or had an impossible value dropped) cannot clear a stored value.
"""

from __future__ import annotations

from typing import Any

from logbook_import.grist_client import GristClient, UpsertResult
from logbook_import.parsers.rsr_pdf import METRICS, RsrMonth

TABLE = "RSR_Metrics"
KEY_COL = "Key"
FILL_ONLY = "_fill_only"  # internal flag, stripped before writing


def build_payloads(rows: list[RsrMonth], source_files: dict[str, str]) -> list[dict[str, Any]]:
    """Merge rows from any number of reports into one payload per key.

    ``source_files`` maps report_month -> PDF file name.
    """
    merged: dict[str, dict[str, Any]] = {}
    # Later rows overwrite earlier ones: oldest-column values go first.
    for row in sorted(rows, key=lambda r: (not r.is_oldest_column, r.report_month)):
        payload = merged.setdefault(
            row.key,
            {KEY_COL: row.key, "Scope": row.scope, "Fleet": row.fleet,
             "Data_Month": row.data_month},
        )
        values = {col: v for col, v in row.metrics.items() if v is not None}
        if values:
            payload.update(values)
            payload["Report_Month"] = row.report_month
            payload["Source_File"] = source_files.get(row.report_month, "")
            payload[FILL_ONLY] = row.is_oldest_column
    # Months with no values in any report (e.g. CRJ550 Dec-Mar) carry no data.
    return [
        p for _, p in sorted(merged.items())
        if any(col in p for col in METRICS.values())
    ]


def sync_rsr(client: GristClient, payloads: list[dict[str, Any]]) -> UpsertResult:
    existing = client.fetch_key_index(TABLE, KEY_COL, [p[KEY_COL] for p in payloads])
    writes = [
        {k: v for k, v in p.items() if k != FILL_ONLY}
        for p in payloads
        if not (p.get(FILL_ONLY) and p[KEY_COL] in existing)
    ]
    return client.upsert_by_key(TABLE, writes, KEY_COL)
