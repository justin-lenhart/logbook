from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from logbook_import.config import TOOLS_ROOT

ENV_PATH = TOOLS_ROOT / ".env"


@dataclass(frozen=True)
class AirtableSettings:
    api_key: str
    base_id: str


def load_airtable_settings() -> AirtableSettings:
    load_dotenv(ENV_PATH)
    api_key = os.environ.get("AIRTABLE_API_KEY", "").strip()
    base_id = os.environ.get("AIRTABLE_BASE_ID", "").strip()
    if not api_key:
        raise ValueError(
            f"AIRTABLE_API_KEY is not set. Add it to {ENV_PATH} (see .env.example)."
        )
    if not base_id:
        raise ValueError(
            f"AIRTABLE_BASE_ID is not set. Add it to {ENV_PATH} (see .env.example)."
        )
    return AirtableSettings(api_key=api_key, base_id=base_id)
