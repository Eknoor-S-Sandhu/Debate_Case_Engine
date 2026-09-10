"""Command-line library inspection smoke test."""

from pathlib import Path

from typer.testing import CliRunner

from scripts.inspect_library import app

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "library"


def test_inspect_library_reports_discovery_and_respects_limit() -> None:
    result = CliRunner().invoke(app, [str(FIXTURE_ROOT), "--limit", "2"])

    assert result.exit_code == 0
    assert "Files discovered: 9" in result.stdout
    assert "Files attempted: 2" in result.stdout
    assert "Unsupported files skipped: 1" in result.stdout
    assert "By extension: .docx=5, .md=1, .pdf=2, .txt=1" in result.stdout
