"""Inspect raw semantic results from the Chroma chunk index."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from debate_engine.config import get_settings
from debate_engine.logging import configure_logging
from debate_engine.retrieval import VectorIndexConfigurationError, VectorStore

app = typer.Typer(add_completion=False, no_args_is_help=True)


@app.command()
def search(
    query: Annotated[str, typer.Argument(help="Semantic query text.")],
    database: Annotated[
        Path | None,
        typer.Option(help="SQLite path. Defaults to the configured database."),
    ] = None,
    top_k: Annotated[int, typer.Option(min=1, help="Maximum result count.")] = 10,
    source_group: Annotated[str | None, typer.Option(help="Exact source_group filter.")] = None,
    document_type: Annotated[str | None, typer.Option(help="Exact document_type filter.")] = None,
    section_type: Annotated[str | None, typer.Option(help="Exact section_type filter.")] = None,
    chunk_level: Annotated[str | None, typer.Option(help="Exact chunk_level filter.")] = None,
    side: Annotated[str | None, typer.Option(help="Exact side filter.")] = None,
    round_type: Annotated[str | None, typer.Option(help="Exact round_type filter.")] = None,
    show_text: Annotated[bool, typer.Option(help="Print hydrated SQLite chunk text.")] = False,
    show_metadata: Annotated[bool, typer.Option(help="Print lightweight Chroma metadata.")] = False,
) -> None:
    """Run raw cosine search without source boosts or retrieval reranking."""
    configure_logging()
    settings = get_settings()
    database_path = database or settings.storage.database_path
    if not database_path.exists():
        typer.echo(f"SQLite database does not exist at {database_path}.", err=True)
        raise typer.Exit(code=1)

    filters = {
        "source_group": source_group,
        "document_type": document_type,
        "section_type": section_type,
        "chunk_level": chunk_level,
        "side": side,
        "round_type": round_type,
    }
    try:
        hits = VectorStore(settings).semantic_search(
            query,
            database=database_path,
            top_k=top_k,
            filters=filters,
            hydrate=True,
        )
    except VectorIndexConfigurationError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(f"Query: {query}")
    typer.echo(f"Results: {len(hits)}")
    for index, hit in enumerate(hits, start=1):
        chunk = hit.chunk
        typer.echo(f"\n{index}. similarity={hit.similarity:.4f} distance={hit.distance:.4f}")
        if chunk is not None:
            typer.echo(f"   Source: {chunk.source_file}")
            typer.echo(f"   Context: {' > '.join(chunk.heading_path) or chunk.section_type}")
        typer.echo(f"   chunk_id={hit.chunk_id}")
        if show_metadata:
            typer.echo(f"   metadata={hit.metadata}")
        if show_text and chunk is not None:
            for line in chunk.text.splitlines():
                typer.echo(f"     | {line}")


if __name__ == "__main__":
    app()
