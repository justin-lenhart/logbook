from unittest.mock import MagicMock

from logbook_import.config import discover_pairing_file_sets, move_processed_files


def test_discover_inbox_pairings() -> None:
    sets, warnings = discover_pairing_file_sets()
    pairing_ids = {s.pairing_id for s in sets}
    assert pairing_ids == {"E3058E", "E7748"}
    assert all(s.txt_path is not None for s in sets)
    assert all(s.csv_path is not None for s in sets)
    assert not any("Ignoring" in w for w in warnings)


def test_move_processed_files(tmp_path):
    src_dir = tmp_path / "inbox"
    src_dir.mkdir()
    dest_dir = tmp_path / "recorded" / "actual"

    txt = src_dir / "121807_20260508_E7748.txt"
    csv = src_dir / "121807_20260508_E7748.csv"
    txt.write_text("data")
    csv.write_text("data")

    plan = MagicMock()
    plan.source_txt = str(txt)
    plan.source_csv = str(csv)

    moved = move_processed_files([plan], dest_dir)

    assert len(moved) == 2
    assert (dest_dir / txt.name).exists()
    assert (dest_dir / csv.name).exists()
    assert not txt.exists()
    assert not csv.exists()


def test_move_processed_files_missing_csv(tmp_path):
    src_dir = tmp_path / "inbox"
    src_dir.mkdir()
    dest_dir = tmp_path / "recorded" / "planned"

    txt = src_dir / "121807_20260508_E7748.txt"
    txt.write_text("data")

    plan = MagicMock()
    plan.source_txt = str(txt)
    plan.source_csv = None

    moved = move_processed_files([plan], dest_dir)

    assert len(moved) == 1
    assert (dest_dir / txt.name).exists()
