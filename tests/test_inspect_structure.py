"""Structure-inspection command smoke tests."""

from pathlib import Path

from typer.testing import CliRunner

from scripts.inspect_structure import app

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "structure"


def test_structure_cli_prints_tree_confidence_and_text() -> None:
    result = CliRunner().invoke(
        app,
        [
            str(FIXTURE_ROOT / "claim_warrant_impact.docx"),
            "--show-confidence",
            "--show-text",
        ],
    )

    assert result.exit_code == 0
    assert "Contention 1: Autonomy [contention] confidence=0.98" in result.stdout
    assert "  Claim: [claim] confidence=0.98" in result.stdout
    assert "| Accessible transport expands meaningful choice." in result.stdout


def test_structure_cli_max_depth_hides_deeper_sections() -> None:
    result = CliRunner().invoke(
        app,
        [
            str(FIXTURE_ROOT / "Case File Sandhu.docx"),
            "--max-depth",
            "1",
        ],
    )

    assert result.exit_code == 0
    assert "AD 1: Economic Mobility [advantage]" in result.stdout
    assert "DA 2: Inflation [disadvantage]" in result.stdout
    assert "UQ: [uniqueness]" not in result.stdout
