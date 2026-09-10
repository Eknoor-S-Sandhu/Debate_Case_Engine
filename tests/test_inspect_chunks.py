"""Chunk-inspection command smoke tests."""

from pathlib import Path

from typer.testing import CliRunner

from scripts.inspect_chunks import app

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "structure"


def test_chunk_cli_filters_level_and_prints_metadata() -> None:
    result = CliRunner().invoke(
        app,
        [
            str(FIXTURE_ROOT / "Case File Sandhu.docx"),
            "--level",
            "submodule",
            "--show-metadata",
            "--limit",
            "1",
        ],
    )

    assert result.exit_code == 0
    assert "Generated chunks: 10" in result.stdout
    assert "Displayed chunks: 1" in result.stdout
    assert "[SUBMODULE]" in result.stdout
    assert "AD 1: Economic Mobility > UQ:" in result.stdout
    assert "source_group=personal" in result.stdout
    assert "[ARGUMENT]" not in result.stdout


def test_chunk_cli_can_show_original_text() -> None:
    result = CliRunner().invoke(
        app,
        [
            str(FIXTURE_ROOT / "capitalism_kritik.docx"),
            "--level",
            "argument",
            "--show-text",
        ],
    )

    assert result.exit_code == 0
    assert "[ARGUMENT]" in result.stdout
    assert "Capitalism Kritik" in result.stdout
    assert "Growth-first logic reproduces exploitation." in result.stdout
