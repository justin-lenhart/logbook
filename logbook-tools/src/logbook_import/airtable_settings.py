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
    # Prefer logbook.json (web app config) over .env (legacy CLI config).
    try:
        from logbook_import.app_config import load_app_config
        cfg = load_app_config()
        api_key = cfg.get("airtable", {}).get("api_key", "").strip()
        base_id = cfg.get("airtable", {}).get("base_id", "").strip()
        if api_key and base_id:
            return AirtableSettings(api_key=api_key, base_id=base_id)
    except Exception:
        pass

    # Fall back to .env for backwards compatibility.
    load_dotenv(ENV_PATH)
    api_key = os.environ.get("AIRTABLE_API_KEY", "").strip()
    base_id = os.environ.get("AIRTABLE_BASE_ID", "").strip()
    if not api_key:
        raise ValueError(
            f"AIRTABLE_API_KEY is not set. Add it to {ENV_PATH} or configure via the web UI."
        )
    if not base_id:
        raise ValueError(
            f"AIRTABLE_BASE_ID is not set. Add it to {ENV_PATH} or configure via the web UI."
        )
    return AirtableSettings(api_key=api_key, base_id=base_id)
