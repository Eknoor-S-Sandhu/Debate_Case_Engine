"""Evaluate exported architectures, or select from an existing evaluation offline."""

from pathlib import Path
from typing import Annotated

import typer

from debate_engine.agents.evaluation import EvaluationAgent, select_architecture
from debate_engine.config import ProviderName, get_settings
from debate_engine.schemas.evaluation import RUBRIC, EvaluationResult
from debate_engine.schemas.rounds import KnowledgePacket
from debate_engine.schemas.strategy import StrategyResult

app = typer.Typer(add_completion=False, no_args_is_help=True)


@app.command()
def evaluate(
    packet_file: Path,
    strategy_file: Path,
    provider: Annotated[
        ProviderName | None, typer.Option(help="Inference provider override.")
    ] = None,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Run one Red Team, repair and scoring pass (up to three provider calls)."""
    try:
        packet = KnowledgePacket.model_validate_json(packet_file.read_text())
        strategy = StrategyResult.model_validate_json(strategy_file.read_text())
    except (OSError, ValueError):
        typer.echo("Could not read valid packet and strategy JSON files.", err=True)
        raise typer.Exit(1) from None
    settings = get_settings().model_copy(deep=True)
    if provider is not None:
        settings.strategy.provider = provider
    result = EvaluationAgent(settings).evaluate(packet, strategy)
    if as_json:
        typer.echo(result.model_dump_json(indent=2))
    else:
        typer.echo(f"Evaluation: {result.status} · Stage: {result.stage}")
        for critique in result.critiques:
            typer.echo(f"\nARCHITECTURE {critique.architecture_id} — Red Team")
            for i, finding in enumerate(critique.findings, start=1):
                typer.echo(f"{i}. [{finding.severity}] {finding.weakness}")
                typer.echo(f"Opponent response: {finding.opponent_response}")
                typer.echo(f"Repair goal: {finding.repair_goal}")
        for repair in result.repairs:
            typer.echo(f"\nREPAIRED ARCHITECTURE {repair.architecture_id}")
            for change in repair.changes:
                typer.echo(f"Change: {change}")
            for response in repair.responses:
                typer.echo(
                    f"Finding {response.finding_number}: {response.status} — {response.explanation}"
                )
            for risk in repair.remaining_risks:
                typer.echo(f"Remaining risk: {risk}")
            typer.echo(repair.architecture.model_dump_json(indent=2))
        for row in result.rankings:
            typer.echo(f"\nRank {row.rank}: Architecture {row.architecture_id} — {row.total}/100")
            for key, maximum in RUBRIC.items():
                score = getattr(row.scores, key)
                typer.echo(f"{key}: {score.points}/{maximum} — {score.rationale}")
            typer.echo(f"Tradeoffs: {row.tradeoffs}")
        for warning in result.warnings:
            typer.echo(f"Note: {warning}")
    if result.status != "completed":
        raise typer.Exit(1)


@app.command()
def select(evaluation_file: Path, architecture_id: Annotated[int, typer.Argument(min=1, max=3)]):
    """Record your explicit choice in JSON; makes no network calls."""
    try:
        evaluation = EvaluationResult.model_validate_json(evaluation_file.read_text())
        result = select_architecture(evaluation, architecture_id)
    except (OSError, ValueError):
        typer.echo(
            "Selection requires a valid completed evaluation and architecture ID 1–3.", err=True
        )
        raise typer.Exit(1) from None
    typer.echo(result.model_dump_json(indent=2))


if __name__ == "__main__":
    app()
