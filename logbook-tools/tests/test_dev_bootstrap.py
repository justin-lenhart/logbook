import subprocess
import sys
from pathlib import Path


TOOLS_ROOT = Path(__file__).resolve().parents[1]


def test_cli_module_runs_from_source_checkout() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "logbook_import.cli", "--help"],
        cwd=TOOLS_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "import-planned" in result.stdout
    assert "import-actual" in result.stdout
