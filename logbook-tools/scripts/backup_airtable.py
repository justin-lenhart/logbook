"""
Full read-only backup of the Logbook Airtable base.

Dumps every table (all records, raw cell values) plus each table's field
schema to a timestamped folder under <repo>/backups/. This is a restore
point taken before any schema/data changes — it is purely read-only and
writes nothing back to Airtable.

Usage:
    .venv/bin/python scripts/backup_airtable.py
"""

from __future__ import annotations

import datetime
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from pyairtable import Api

TOOLS_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = TOOLS_ROOT.parent
ENV_PATH = TOOLS_ROOT / ".env"
BASE_ID = "appJSWcRpFXhwWOqd"


def main() -> None:
    load_dotenv(ENV_PATH)
    api_key = os.environ.get("AIRTABLE_API_KEY", "").strip()
    if not api_key:
        sys.exit(f"AIRTABLE_API_KEY not set. Add it to {ENV_PATH}")

    api = Api(api_key)
    base = api.base(BASE_ID)

    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = REPO_ROOT / "backups" / f"airtable-{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)

    schema = base.schema()
    manifest: dict = {
        "base_id": BASE_ID,
        "taken_at": ts,
        "tables": [],
    }

    for table_schema in schema.tables:
        tbl = base.table(table_schema.id)
        records = tbl.all()
        safe = table_schema.name.replace("/", "_").replace(" ", "_")
        (out_dir / f"{safe}.json").write_text(
            json.dumps(
                {
                    "table_id": table_schema.id,
                    "table_name": table_schema.name,
                    "fields": [
                        {"id": f.id, "name": f.name, "type": f.type}
                        for f in table_schema.fields
                    ],
                    "records": records,
                },
                indent=2,
                default=str,
            )
        )
        manifest["tables"].append(
            {"name": table_schema.name, "id": table_schema.id, "records": len(records)}
        )
        print(f"  {table_schema.name:<16} {len(records):>5} records")

    (out_dir / "_manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"\nBackup written to {out_dir}")


if __name__ == "__main__":
    main()
