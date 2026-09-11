"""Write a case from the packet, architectures and explicitly selected evaluation."""

from pathlib import Path
from typing import Annotated

import typer

from debate_engine.agents.case_writer import CaseWriter
from debate_engine.schemas.case import SpeechBudget
from debate_engine.schemas.evaluation import EvaluationResult
from debate_engine.schemas.rounds import KnowledgePacket
from debate_engine.schemas.strategy import StrategyResult

app = typer.Typer(add_completion=False, no_args_is_help=True)


@app.command()
def write(
    packet_file: Path,
    strategy_file: Path,
    evaluation_file: Path,
    words_per_minute: Annotated[int, typer.Option(min=80, max=400)] = 150,
    reserve_seconds: Annotated[int, typer.Option(min=0, max=120)] = 30,
    as_json: Annotated[bool, typer.Option("--json")] = False,
):
    try:
        packet = KnowledgePacket.model_validate_json(packet_file.read_text())
        strategy = StrategyResult.model_validate_json(strategy_file.read_text())
        evaluation = EvaluationResult.model_validate_json(evaluation_file.read_text())
    except (OSError, ValueError):
        typer.echo("Could not read valid packet, strategy and evaluation JSON files.", err=True)
        raise typer.Exit(1) from None
    result = CaseWriter().write(
        packet,
        strategy,
        evaluation,
        budget=SpeechBudget(
            words_per_minute=words_per_minute,
            reserve_seconds=reserve_seconds,
        ),
    )
    if as_json:
        typer.echo(result.model_dump_json(indent=2))
    elif result.status == "completed":
        typer.echo(f"Selected strategy score: {result.selected_strategy_score}/100\n")
        typer.echo(result.markdown)
        typer.echo(
            f"\nEstimated speech: {result.word_count}/{result.word_limit} words, "
            f"{result.estimated_seconds / 60:.1f} minutes at {words_per_minute} wpm."
        )
        for warning in result.warnings:
            typer.echo(f"Note: {warning}", err=True)
    else:
        typer.echo(f"Case writing: {result.status} ({result.stage})", err=True)
        for warning in result.warnings:
            typer.echo(warning, err=True)
    if result.status != "completed":
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
