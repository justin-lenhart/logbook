"""Smoke tests that the publish flags are wired into the CLI."""

from __future__ import annotations

from click.testing import CliRunner

from logbook_import.cli import main


def test_import_actual_has_update_flags():
    result = CliRunner().invoke(main, ["import-actual", "--help"])
    assert result.exit_code == 0
    assert "--update-map" in result.output
    assert "--update-apps" in result.output
    assert "--update-all" in result.output


def test_export_apps_has_update_flag():
    result = CliRunner().invoke(main, ["export-apps", "--help"])
    assert result.exit_code == 0
    assert "--update" in result.output
