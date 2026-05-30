from __future__ import annotations

from typing import Any

# Registry of supported import file formats.
# Each entry describes one parser that can be selected in the Settings UI.
# To add a new airline/format:
#   1. Create a parser module under logbook_import/parsers/
#   2. Add an entry here with a unique key, human label, and description.
PARSER_REGISTRY: dict[str, dict[str, Any]] = {
    "skedplus": {
        "label": "SkyWest / SkedPlus",
        "description": (
            "SkedPlus .txt and .csv exports from SkyWest Airlines. "
            "Drop both files for each pairing into your inbox folder."
        ),
        "file_hint": "Example filenames: 1_20260509_E3058E.txt / .csv",
    },
}


def get_parser_choices() -> list[dict[str, str]]:
    """Return list of {key, label, description} dicts for the config UI."""
    return [
        {"key": k, "label": v["label"], "description": v["description"], "file_hint": v.get("file_hint", "")}
        for k, v in PARSER_REGISTRY.items()
    ]
