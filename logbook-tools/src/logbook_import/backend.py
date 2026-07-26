"""Backend selection: Airtable (legacy) vs Grist (mintbox).

Set ``LOGBOOK_BACKEND=grist`` (env or logbook-tools/.env) to write to the
self-hosted Grist doc; the default remains ``airtable`` until cutover.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

from logbook_import.config import TOOLS_ROOT

VALID_BACKENDS = ("airtable", "grist")


def active_backend() -> str:
    load_dotenv(TOOLS_ROOT / ".env")
    backend = os.environ.get("LOGBOOK_BACKEND", "airtable").strip().lower()
    if backend not in VALID_BACKENDS:
        raise ValueError(
            f"LOGBOOK_BACKEND={backend!r} is not valid; use one of {VALID_BACKENDS}"
        )
    return backend
