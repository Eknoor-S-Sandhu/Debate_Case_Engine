"""Duplicate-inspection command smoke tests."""

from pathlib import Path

from typer.testing import CliRunner

from scripts.inspect_duplicates import app

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "duplicates"


def test_duplicate_cli_processes_folder_and_prefers_personal_source() -> None:
    result = CliRunner().invoke(
        app,
        [
            str(FIXTURE_ROOT),
            "--only-duplicates",
            "--show-text",
        ],
    )

    assert result.exit_code == 0
    assert "Files processed: 4" in result.stdout
    assert "Chunks inspected: 4" in result.stdout
    assert "Duplicate groups: 1" in result.stdout
    assert "Type: near" in result.stdout
    assert "Representative: personal / access.md" in result.stdout
    assert "Similarity range: 0.9671–1.0000" in result.stdout
    assert "Singleton chunks" not in result.stdout
    assert "Public transit expands access to employment" in result.stdout


def test_duplicate_cli_limit_applies_to_folder_files() -> None:
    result = CliRunner().invoke(app, [str(FIXTURE_ROOT), "--limit", "2"])

    assert result.exit_code == 0
    assert "Files processed: 2" in result.stdout
