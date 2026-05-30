from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

TOOLS_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = TOOLS_ROOT / "logbook.json"

DEFAULT_CONFIG: dict[str, Any] = {
    "airtable": {"api_key": "", "base_id": ""},
    "paths": {"inbox": str(TOOLS_ROOT.parent / "inbox")},
    "pilot": {"role": "sic", "operator": "skw"},
    "import": {"format": "skedplus"},
    "map": {"url": ""},
}


def load_app_config() -> dict[str, Any]:
    """Load config from logbook.json, migrating from .env if needed."""
    if not CONFIG_PATH.exists():
        _migrate_from_dotenv()
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            stored = json.load(f)
        return _deep_merge(DEFAULT_CONFIG, stored)
    return _deep_merge(DEFAULT_CONFIG, {})


def save_app_config(config: dict[str, Any]) -> None:
    """Save config to logbook.json."""
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)


def is_configured() -> bool:
    """Return True if Airtable credentials are present."""
    cfg = load_app_config()
    at = cfg.get("airtable", {})
    return bool(at.get("api_key") and at.get("base_id"))


def _migrate_from_dotenv() -> None:
    """One-time migration: if .env exists, copy Airtable keys to logbook.json."""
    env_path = TOOLS_ROOT / ".env"
    if not env_path.exists():
        return
    values: dict[str, str] = {}
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        values[key.strip()] = val.strip().strip('"').strip("'")

    config = _deep_merge(DEFAULT_CONFIG, {})
    if values.get("AIRTABLE_API_KEY"):
        config["airtable"]["api_key"] = values["AIRTABLE_API_KEY"]
    if values.get("AIRTABLE_BASE_ID"):
        config["airtable"]["base_id"] = values["AIRTABLE_BASE_ID"]
    save_app_config(config)


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base, returning a new dict."""
    result = dict(base)
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = val
    return result
