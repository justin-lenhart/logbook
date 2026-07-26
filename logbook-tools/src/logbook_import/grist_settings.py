from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

from logbook_import.config import TOOLS_ROOT

ENV_PATH = TOOLS_ROOT / ".env"

# Canonical URL for the mintbox Grist instance. It binds to the Tailscale IP
# ONLY (localhost is refused) and APP_HOME_URL pins this hostname.
DEFAULT_GRIST_URL = "http://100.78.241.102:8484"


@dataclass(frozen=True)
class GristSettings:
    url: str
    api_key: str
    doc_id: str


def load_grist_settings() -> GristSettings:
    load_dotenv(ENV_PATH)
    url = os.environ.get("GRIST_URL", DEFAULT_GRIST_URL).strip().rstrip("/")
    api_key = os.environ.get("GRIST_API_KEY", "").strip()
    doc_id = os.environ.get("GRIST_DOC", "").strip()
    if not api_key:
        raise ValueError(
            f"GRIST_API_KEY is not set. Add it to {ENV_PATH} (see .env.example)."
        )
    if not doc_id:
        raise ValueError(
            f"GRIST_DOC is not set. Add it to {ENV_PATH} (see .env.example)."
        )
    return GristSettings(url=url, api_key=api_key, doc_id=doc_id)
