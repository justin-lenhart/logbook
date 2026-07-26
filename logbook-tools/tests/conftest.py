from pathlib import Path

import pytest

# Real SkedPlus exports (operational data, gitignored) live in recorded/ after
# import.  inbox/ is a transient watch folder now — never keep fixtures there.
WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
RECORDED_ACTUAL = WORKSPACE_ROOT / "recorded" / "actual"

E3058E_TXT = RECORDED_ACTUAL / "121807_20260509_E3058E.txt"
E3058E_CSV = RECORDED_ACTUAL / "121807_20260509_E3058E.csv"
E7748_TXT = RECORDED_ACTUAL / "121807_20260508_E7748.txt"
E7748_CSV = RECORDED_ACTUAL / "121807_20260508_E7748.csv"


def _require(path: Path) -> Path:
    if not path.exists():
        pytest.skip(f"local SkedPlus export not present: {path.name}")
    return path


@pytest.fixture
def e3058e_txt() -> Path:
    return _require(E3058E_TXT)


@pytest.fixture
def e3058e_csv() -> Path:
    return _require(E3058E_CSV)


@pytest.fixture
def e7748_txt() -> Path:
    return _require(E7748_TXT)


@pytest.fixture
def e7748_csv() -> Path:
    return _require(E7748_CSV)
