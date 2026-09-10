"""Parse, structure, and preview retrieval chunks without persistence."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from debate_engine.ingestion import (
    chunk_structured_document,
    detect_structure,
    parse_document,
)
from debate_engine.logging import configure_logging
from debate_engine.schemas import ChunkLevel, DebateChunk

app = typer.Typer(add_completion=False, no_args_is_help=True)


def _heading_label(chunk: DebateChunk) -> str:
    if chunk.heading_path:
        return " > ".join(heading.strip() for heading in chunk.heading_path)
    return chunk.original_heading or chunk.source_file


def _print_chunk(
    chunk: DebateChunk,
    *,
    show_text: bool,
    show_metadata: bool,
) -> None:
    typer.echo(f"[{chunk.chunk_level.value.upper()}]")
    typer.echo(_heading_label(chunk))
    typer.echo(f"section_type={chunk.section_type}")
    typer.echo(f"tokens={chunk.token_count}")

    if show_metadata:
        typer.echo(f"chunk_id={chunk.chunk_id}")
        typer.echo(f"document_id={chunk.document_id}")
        typer.echo(f"source_group={chunk.source_group.value}")
        typer.echo(f"document_type={chunk.document_type.value}")
        typer.echo(f"side={chunk.side.value}")
        typer.echo(f"round_type={chunk.round_type.value}")
        typer.echo(f"priority_weight={chunk.priority_weight:.2f}")
        typer.echo(f"source_blocks={chunk.source_block_indexes}")
        typer.echo(f"structure_confidence={chunk.structure_confidence:.2f}")
        typer.echo(f"special_masterfile={chunk.is_special_masterfile}")

    if show_text:
        typer.echo("")
        typer.echo(chunk.text)
    typer.echo("")


@app.command()
def inspect(
    source: Annotated[
        Path,
        typer.Argument(
            exists=True,
            dir_okay=False,
            readable=True,
            resolve_path=True,
            help="A supported debate document.",
        ),
    ],
    level: Annotated[
        ChunkLevel | None,
        typer.Option(help="Show only argument, submodule, or fallback chunks."),
    ] = None,
    show_text: Annotated[
        bool,
        typer.Option(help="Print complete chunk text."),
    ] = False,
    show_metadata: Annotated[
        bool,
        typer.Option(help="Print provenance and classification metadata."),
    ] = False,
    limit: Annotated[
        int | None,
        typer.Option(min=1, help="Print only the first N matching chunks."),
    ] = None,
) -> None:
    """Print deterministic chunks generated from one debate document."""
    configure_logging()
    parsed = parse_document(source)
    structured = detect_structure(parsed)
    chunks = chunk_structured_document(structured)
    selected = [chunk for chunk in chunks if level is None or chunk.chunk_level is level]
    if limit is not None:
        selected = selected[:limit]

    typer.echo(f"Source: {source}")
    typer.echo(f"Parse status: {parsed.parse_status.value}")
    typer.echo(f"Detected sections: {sum(1 for _ in structured.iter_sections())}")
    typer.echo(f"Generated chunks: {len(chunks)}")
    typer.echo(f"Displayed chunks: {len(selected)}")
    typer.echo("")

    if not selected:
        typer.echo("(no matching non-empty chunks)")
        return
    for chunk in selected:
        _print_chunk(
            chunk,
            show_text=show_text,
            show_metadata=show_metadata,
        )


if __name__ == "__main__":
    app()
