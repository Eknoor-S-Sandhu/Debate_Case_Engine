"""Generate three architectures from an exported Knowledge Packet."""

from pathlib import Path
from typing import Annotated

import typer

from debate_engine.agents.strategy import StrategyAgent
from debate_engine.schemas.rounds import KnowledgePacket

app = typer.Typer(add_completion=False, no_args_is_help=True)


@app.command()
def generate(
    packet_file: Annotated[Path, typer.Argument(help="Exported Knowledge Packet JSON.")],
    preferences: Annotated[str, typer.Option(help="Optional strategic preferences.")] = "",
    as_json: Annotated[
        bool, typer.Option("--json", help="Print structured strategy output.")
    ] = False,
) -> None:
    try:
        packet = KnowledgePacket.model_validate_json(packet_file.read_text())
    except Exception:
        typer.echo("Could not read a valid Knowledge Packet JSON file.", err=True)
        raise typer.Exit(1) from None
    result = StrategyAgent().generate(packet, preferences=preferences)
    if as_json:
        typer.echo(result.model_dump_json(indent=2))
    else:
        typer.echo(f"Strategy status: {result.status}")
        for number, architecture in enumerate(result.architectures, start=1):
            typer.echo(f"\nARCHITECTURE {number}: {architecture.name}")
            typer.echo(f"Framing: {architecture.framing}")
            if architecture.value:
                typer.echo(f"Value: {architecture.value}; criterion: {architecture.criterion}")
            typer.echo(f"Core mechanism: {architecture.core_mechanism}")
            typer.echo(f"Ballot route: {architecture.route_to_ballot}")
            typer.echo(f"Distinct approach: {architecture.differs_from_others}")
            for contention in architecture.contentions:
                typer.echo(f"\n{contention.title} ({contention.basis})")
                typer.echo(f"Claim: {contention.claim}")
                for label, text in [
                    ("UQ", contention.uniqueness),
                    ("L", contention.link),
                    ("IL", contention.internal_link),
                ]:
                    if text:
                        typer.echo(f"{label}: {text}")
                for label, values in [
                    ("Warrant", contention.warrants),
                    ("Impact", contention.impacts),
                    ("Preempt", contention.preempts),
                    ("Assumption", contention.assumptions),
                    ("Verify", contention.needs_verification),
                ]:
                    for text in values:
                        typer.echo(f"{label}: {text}")
                typer.echo(f"Archive sources: {', '.join(contention.archive_chunk_ids) or 'none'}")
                typer.echo(
                    f"Research sources: {', '.join(contention.research_source_ids) or 'none'}"
                )
                for quote in contention.quotes:
                    typer.echo(f'Quote ({quote.source_type}, {quote.source_id}): "{quote.text}"')
            typer.echo(f"Judge adaptation: {architecture.judge_adaptation}")
            typer.echo(f"Why this can win: {architecture.why_this_can_win}")
            typer.echo(f"Main vulnerability: {architecture.main_vulnerability}")
        for warning in result.warnings:
            typer.echo(f"Note: {warning}")
    if result.status != "completed":
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
