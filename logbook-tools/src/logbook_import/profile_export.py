"""One export run — shared by the CLI and the export service.

``export-profile`` on the command line and the one-click button on the
server must produce the same file and warn about the same problems, so the
run lives here once and neither caller can drift from the other.

Read-only toward Grist: nothing here writes, and there is no ``--commit``
to pass. The finished file is owner-only, and `deliver()` puts a copy in
the Syncthing outbox that carries it to the Mac.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from logbook_import import profile_data as pd
from logbook_import.config import WORKSPACE_ROOT
from logbook_import.profile_render import render_profile
from logbook_import.profiles import PROFILES, Context, load_pilot

# Both default to the repo root, where both are gitignored: exports/ holds
# flight records, pilot.toml the pilot's certificate details.
DEFAULT_EXPORT_DIR = WORKSPACE_ROOT / "exports"
DEFAULT_PILOT_FILE = WORKSPACE_ROOT / "pilot.toml"

# Syncthing may pick a file up the moment it appears, so bytes land under
# this suffix and are renamed into place in one step — never a half-written
# export on the Mac. The outbox's .stignore keeps the temporary name local.
PART_SUFFIX = ".part"


class ExportError(Exception):
    """The export could not be produced (unknown target, or no flights)."""


@dataclass(frozen=True)
class ExportResult:
    target: str
    as_of: date
    path: Path
    delivered: Path | None
    flights: int
    hours: float
    pic: float
    sic: float
    dual: float
    warnings: tuple[str, ...]

    @property
    def summary(self) -> str:
        """The one-line total both callers report."""
        return (f"{self.flights} flights, total {self.hours:.1f} h "
                f"(PIC {self.pic:.1f} / SIC {self.sic:.1f} / "
                f"dual {self.dual:.1f})")


def build_export(
    client,
    target: str,
    *,
    output_dir: Path | None = None,
    as_of: date | None = None,
    pilot_path: Path | None = None,
    include_log: bool = True,
    outbox: Path | None = None,
) -> ExportResult:
    """Render one target and write it to ``output_dir`` (default ``exports/``).

    ``outbox`` additionally delivers a copy for Syncthing to carry. Problems
    that do not stop the export come back as ``warnings`` for the caller to
    report in its own voice; the rest raise ``ExportError``.
    """
    profile = PROFILES.get(target)
    if profile is None:
        raise ExportError(f"Unknown target: {target}")

    report_date = as_of or date.today()
    pilot_file = pilot_path or DEFAULT_PILOT_FILE
    pilot = load_pilot(pilot_file)
    warnings: list[str] = []
    if not pilot.name:
        warnings.append(
            f"no pilot name in {pilot_file} — copy pilot.toml.example to "
            "pilot.toml; the export will have a blank name"
        )

    legs = [leg for leg in pd.load_legs(client) if leg.date <= report_date]
    if not legs:
        raise ExportError("No flights found in Flights table")
    for leg in legs:
        if not leg.category:
            warnings.append(
                f"flight {leg.id} ({leg.date}, {leg.block:.1f} h) has no "
                "Aircraft link — counted in total time but in no "
                "category/class/type"
            )

    html = render_profile(
        profile, legs, Context(as_of=report_date, pilot=pilot),
        include_log=include_log,
    )
    directory = output_dir or DEFAULT_EXPORT_DIR
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = directory / f"logbook-{target}-{report_date.isoformat()}.html"
    path.write_text(html, encoding="utf-8")
    path.chmod(0o600)

    delivered = deliver(path, outbox) if outbox is not None else None
    return ExportResult(
        target=target,
        as_of=report_date,
        path=path,
        delivered=delivered,
        flights=len(legs),
        hours=pd.total(legs),
        pic=pd.total(legs, "pic"),
        sic=pd.total(legs, "sic"),
        dual=pd.total(legs, "dual_received"),
        warnings=tuple(warnings),
    )


def prepare_outbox(outbox: Path) -> Path:
    """Create the Syncthing outbox, owner-only, with its ignore file."""
    outbox.mkdir(parents=True, exist_ok=True, mode=0o700)
    stignore = outbox / ".stignore"
    if not stignore.is_file():
        stignore.write_text(
            "// Half-written exports: a copy lands under *.part and is then\n"
            "// renamed into place. Syncthing should never carry the temporary\n"
            "// name across to the Mac.\n"
            f"*{PART_SUFFIX}\n",
            encoding="utf-8",
        )
    return outbox


def deliver(export: Path, outbox: Path) -> Path:
    """Copy a finished export into the outbox, atomically. Returns the copy."""
    prepare_outbox(outbox)
    final = outbox / export.name
    staged = outbox / f"{export.name}{PART_SUFFIX}"
    staged.write_bytes(export.read_bytes())
    staged.chmod(0o600)
    os.replace(staged, final)
    return final
