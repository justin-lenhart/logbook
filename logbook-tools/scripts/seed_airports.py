#!/usr/bin/env python3
"""Seed the Airports table from OurAirports public data."""

from __future__ import annotations

import csv
import os
import tempfile
import urllib.request
from pathlib import Path

from dotenv import load_dotenv
from pyairtable import Api

OURAIRPORTS_URL = "https://davidmegginson.github.io/ourairports-data/airports.csv"
TABLE_NAME = "Airports"
FIELD_IATA = "IATA Code"
FIELD_NAME = "Airport Name"
FIELD_CITY = "City"
FIELD_COUNTRY = "Country"
FIELD_LAT = "Latitude"
FIELD_LON = "Longitude"

TOOLS_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = TOOLS_ROOT / ".env"


def main() -> None:
    load_dotenv(ENV_PATH)
    api_key = os.environ.get("AIRTABLE_API_KEY", "").strip()
    base_id = os.environ.get("AIRTABLE_BASE_ID", "").strip()
    if not api_key:
        raise SystemExit(
            f"AIRTABLE_API_KEY is not set. Add it to {ENV_PATH} (see .env.example)."
        )
    if not base_id:
        raise SystemExit(
            f"AIRTABLE_BASE_ID is not set. Add it to {ENV_PATH} (see .env.example)."
        )

    with tempfile.NamedTemporaryFile(suffix=".csv") as tmp:
        urllib.request.urlretrieve(OURAIRPORTS_URL, tmp.name)
        with open(tmp.name, newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            records = []
            for row in reader:
                if row.get("type") not in {"large_airport", "medium_airport"}:
                    continue
                iata = (row.get("iata_code") or "").strip()
                if not iata:
                    continue
                records.append(
                    {
                        "fields": {
                            FIELD_IATA: iata.upper(),
                            FIELD_NAME: row["name"],
                            FIELD_CITY: row["municipality"],
                            FIELD_COUNTRY: row["iso_country"],
                            FIELD_LAT: float(row["latitude_deg"]),
                            FIELD_LON: float(row["longitude_deg"]),
                        }
                    }
                )

    table = Api(api_key).base(base_id).table(TABLE_NAME)
    table.batch_upsert(records, key_fields=[FIELD_IATA], typecast=True)
    print(f"Seeded {len(records)} airports into Airports table.")


if __name__ == "__main__":
    main()
