"""Development bootstrap for running the package from a source checkout."""

from __future__ import annotations

from pathlib import Path

__version__ = "0.1.0"

# Python 3.14 no longer seeds venvs with setuptools, so editable installs are
# not always available offline during local development. Make the src/ package
# importable directly when running from the repository root.
_SRC_PACKAGE_DIR = Path(__file__).resolve().parent.parent / "src" / "logbook_import"
if _SRC_PACKAGE_DIR.is_dir():
    __path__.append(str(_SRC_PACKAGE_DIR))
