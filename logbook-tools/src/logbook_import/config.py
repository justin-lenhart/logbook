from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from logbook_import.models import ImportPlan

TOOLS_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE_ROOT = TOOLS_ROOT.parent
INBOX_DIR = WORKSPACE_ROOT / "inbox"
RECORDED_DIR = WORKSPACE_ROOT / "recorded"

PAIRING_FILE_RE = re.compile(
    r"^(?P<prefix>\d+)_(?P<date>\d{8})_(?P<pairing>[A-Z0-9]+)\.(?P<ext>txt|csv)$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PairingFileSet:
    pairing_id: str
    txt_path: Path | None
    csv_path: Path | None


def discover_pairing_file_sets(inbox: Path | None = None) -> tuple[list[PairingFileSet], list[str]]:
    """Group inbox files into txt/csv pairing sets."""
    inbox = inbox or INBOX_DIR
    warnings: list[str] = []
    by_pairing: dict[str, dict[str, Path]] = {}

    if not inbox.is_dir():
        return [], [f"Inbox directory not found: {inbox}"]

    for path in sorted(inbox.iterdir()):
        if not path.is_file():
            continue
        match = PAIRING_FILE_RE.match(path.name)
        if not match:
            warnings.append(f"Ignoring unrelated file: {path.name}")
            continue
        pairing_id = match.group("pairing").upper()
        ext = match.group("ext").lower()
        by_pairing.setdefault(pairing_id, {})[ext] = path

    sets: list[PairingFileSet] = []
    for pairing_id, files in sorted(by_pairing.items()):
        txt_path = files.get("txt")
        csv_path = files.get("csv")
        if txt_path is None:
            warnings.append(f"Skipping {pairing_id}: missing .txt export")
            continue
        if csv_path is None:
            warnings.append(f"Warning: {pairing_id} has no matching .csv export")
        sets.append(PairingFileSet(pairing_id=pairing_id, txt_path=txt_path, csv_path=csv_path))

    return sets, warnings


def move_processed_files(plans: list[ImportPlan], dest_dir: Path) -> list[Path]:
    """Move source files for each plan from inbox to dest_dir. Returns moved paths."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    moved: list[Path] = []
    for plan in plans:
        for src_str in (plan.source_txt, plan.source_csv):
            if not src_str:
                continue
            src = Path(src_str)
            if src.exists():
                shutil.move(str(src), dest_dir / src.name)
                moved.append(dest_dir / src.name)
    return moved
