from pathlib import Path

import pytest

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
INBOX = WORKSPACE_ROOT / "inbox"

E3058E_TXT = INBOX / "121807_20260509_E3058E.txt"
E3058E_CSV = INBOX / "121807_20260509_E3058E.csv"
E7748_TXT = INBOX / "121807_20260508_E7748.txt"
E7748_CSV = INBOX / "121807_20260508_E7748.csv"


@pytest.fixture
def e3058e_txt() -> Path:
    return E3058E_TXT


@pytest.fixture
def e3058e_csv() -> Path:
    return E3058E_CSV


@pytest.fixture
def e7748_txt() -> Path:
    return E7748_TXT


@pytest.fixture
def e7748_csv() -> Path:
    return E7748_CSV
