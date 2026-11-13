"""The home server is named in one way, in one place, and nowhere else.

The server was renamed once. Every path, user and address in the repo moved
with it, but the *name* stayed behind in prose for months: docs, module
docstrings and a test fixture all went on naming a box that no longer exists,
which sent at least one reader looking for a machine to SSH into.

A name in prose has nothing checking it, so these tests do the checking:

1. The retired name appears in no tracked file. It is never written whole in
   this module either -- it is built from two halves, so the guard cannot
   match itself and the name does not come back through its own test.
2. Every tailnet address quoted in the docs is the one the code actually
   dials. If the server moves again, ``DEFAULT_GRIST_URL`` and the docs have
   to move together or this fails.

If the server is genuinely renamed, change ``HOST`` / ``DEFAULT_GRIST_URL``
and the docs in the same commit. Do not delete these tests to make a rename
pass.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from logbook_import.config import WORKSPACE_ROOT
from logbook_import.grist_settings import DEFAULT_GRIST_URL

# The host this repo is deployed on, as every systemd unit and path says.
HOST = "crushbox"

# The retired name, assembled so this file never contains it literally.
RETIRED_HOST = "mint" + "box"

# Tailscale hands out addresses in the 100.64/10 carrier-grade NAT range.
# A CIDR range is not a host, so one written with a prefix length is skipped:
# naming the range the tailnet lives in is correct, naming another box's
# address is the mistake this looks for.
TAILNET = re.compile(r"\b100\.\d{1,3}\.\d{1,3}\.\d{1,3}\b(?!/)")

# This file is the one place that has to hold counter-examples -- a wrong
# address, a foreign range -- so the address scan skips it and nothing else.
SELF = Path(__file__).resolve()

# Nothing here is prose a reader follows: lockfiles and sample data.
SKIP_SUFFIXES = {".lock", ".geojson", ".png", ".jpg", ".pdf", ".xlsx"}


def tracked_files() -> list[Path]:
    """Every file git tracks, so untracked scratch work is not scanned."""
    try:
        out = subprocess.run(
            ["git", "-C", str(WORKSPACE_ROOT), "ls-files", "-z"],
            capture_output=True, check=True, timeout=30,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        pytest.skip("git not available")
    names = [n for n in out.decode().split("\0") if n]
    if not names:
        pytest.skip("not a git checkout")
    return [WORKSPACE_ROOT / n for n in names]


def readable_text(path: Path) -> str | None:
    if path.suffix.lower() in SKIP_SUFFIXES or not path.is_file():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def test_the_retired_host_name_is_gone() -> None:
    """THE GUARD: a box that no longer exists must not be named anywhere."""
    offenders: list[str] = []
    for path in tracked_files():
        text = readable_text(path)
        if text is None:
            continue
        for number, line in enumerate(text.splitlines(), 1):
            if RETIRED_HOST in line.lower():
                rel = path.relative_to(WORKSPACE_ROOT)
                offenders.append(f"{rel}:{number}: {line.strip()}")
    assert not offenders, (
        "the retired host name is back in "
        f"{len(offenders)} place(s); the server is '{HOST}':\n"
        + "\n".join(offenders)
    )


def test_this_guard_cannot_match_itself() -> None:
    """The name is built from halves, so the test file is not an offender."""
    own = Path(__file__).read_text(encoding="utf-8")
    assert RETIRED_HOST not in own
    assert HOST in own


def test_the_docs_quote_the_address_the_code_dials() -> None:
    """One tailnet address in the repo: the one ``DEFAULT_GRIST_URL`` names."""
    expected = urlsplit(DEFAULT_GRIST_URL).hostname
    assert expected and TAILNET.fullmatch(expected), DEFAULT_GRIST_URL

    wrong: list[str] = []
    skipped: list[Path] = []
    for path in tracked_files():
        if path.suffix.lower() not in {".md", ".py", ".service", ".path", ".sh"}:
            continue
        if path.resolve() == SELF:
            skipped.append(path)
            continue
        text = readable_text(path)
        if text is None:
            continue
        for number, line in enumerate(text.splitlines(), 1):
            for found in TAILNET.findall(line):
                if found != expected:
                    rel = path.relative_to(WORKSPACE_ROOT)
                    wrong.append(f"{rel}:{number}: {found}")
    # One exclusion, and it is this file. Anything else must be scanned.
    assert len(skipped) == 1, skipped
    assert not wrong, (
        f"these name a tailnet address that is not {expected}; if the server "
        "moved, move DEFAULT_GRIST_URL and the docs together:\n"
        + "\n".join(wrong)
    )


def test_a_cidr_range_is_not_read_as_a_host_address() -> None:
    """Describing the range the tailnet lives in is not naming another box.

    The guard flagged its own comment the moment this file became tracked,
    which is the distinction, not a nuisance: ``100.64.0.0/10`` is the block
    Tailscale allocates from; ``100.64.0.0`` on its own would be a host.
    """
    assert not TAILNET.search("the 100.64.0.0/10 range")
    assert TAILNET.search("ssh 100.64.0.0") is not None
    assert TAILNET.search("http://100.99.1.4:8484") is not None


def test_the_export_service_address_follows_grist() -> None:
    """The button cannot drift onto a different box from the Grist doc."""
    from logbook_import.cli import DEFAULT_SERVICE_HOST

    assert DEFAULT_SERVICE_HOST == urlsplit(DEFAULT_GRIST_URL).hostname


def test_the_deployment_targets_this_host() -> None:
    """Every unit runs as the same user, in that user's checkout."""
    units = sorted((WORKSPACE_ROOT / "deploy" / "systemd").glob("*.service"))
    assert units, "no systemd units found"
    for unit in units:
        text = unit.read_text(encoding="utf-8")
        assert f"User={HOST}" in text, unit.name
        assert f"/home/{HOST}/" in text, unit.name
