"""Prepare a round plan or a source-grounded Knowledge Packet."""

from pathlib import Path
from typing import Annotated

import typer

from debate_engine.agents import RoundDirector
from debate_engine.schemas.rounds import RoundInput

app = typer.Typer(add_completion=False, no_args_is_help=True)


@app.command()
def prepare(
    input_file: Annotated[Path, typer.Argument(help="JSON file containing RoundInput.")],
    database: Annotated[
        Path | None, typer.Option(help="Override the SQLite database path.")
    ] = None,
    plan_only: Annotated[
        bool, typer.Option(help="Plan without opening indexes or loading models.")
    ] = False,
    as_json: Annotated[
        bool, typer.Option("--json", help="Print the complete JSON handoff.")
    ] = False,
) -> None:
    try:
        context = RoundInput.model_validate_json(input_file.read_text())
        director = RoundDirector()
        output = (
            director.plan(context) if plan_only else director.prepare(context, database=database)
        )
    except Exception as exc:
        typer.echo(f"Round preparation failed: {exc}", err=True)
        raise typer.Exit(1) from exc
    if as_json:
        typer.echo(output.model_dump_json(indent=2))
        return
    plan = output if plan_only else output.plan
    typer.echo(f"Motion: {plan.round_input.motion}")
    typer.echo(f"Research: {plan.research_status}")
    typer.echo("Retrieval queries:")
    for query in plan.generated_queries:
        typer.echo(f"  [{query.family.value}] {query.text}")
    for note in plan.notes:
        typer.echo(f"Note: {note}")
    if plan_only:
        return
    typer.echo(f"\nKNOWLEDGE PACKET — {len(output.items)} unique chunks")
    for category, ids in output.groups.items():
        if not ids:
            continue
        typer.echo(f"\n{category.value.upper()}")
        for chunk_id in ids:
            item = output.items[chunk_id]
            candidate = item.candidate
            chunk = candidate.chunk
            typer.echo(f"{chunk_id} | {candidate.final_score:.4f} | {chunk.source_path}")
            typer.echo(" > ".join(chunk.heading_path))
            typer.echo(chunk.text)
            for note in item.verification_notes:
                typer.echo(f"  Verify: {note}")
    for warning in output.warnings:
        typer.echo(f"Warning: {warning}")


if __name__ == "__main__":
    app()
