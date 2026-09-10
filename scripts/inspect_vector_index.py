"""Report SQLite-to-Chroma vector-index health without loading the model."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from debate_engine.config import get_settings
from debate_engine.retrieval import VectorIndexConfigurationError, VectorStore

app = typer.Typer(add_completion=False)


@app.command()
def inspect(
    database: Annotated[
        Path | None,
        typer.Option(help="SQLite path. Defaults to the configured database."),
    ] = None,
    include_duplicates: Annotated[
        bool,
        typer.Option(help="Compare against eligibility with all duplicate members."),
    ] = False,
) -> None:
    """Show collection configuration, counts, and stale-vector count."""
    settings = get_settings()
    database_path = database or settings.storage.database_path
    if not database_path.exists():
        typer.echo(f"SQLite database does not exist at {database_path}.", err=True)
        raise typer.Exit(code=1)
    try:
        status = VectorStore(settings).status(
            database=database_path,
            include_duplicate_members=include_duplicates,
        )
    except VectorIndexConfigurationError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(f"Collection: {status.collection_name}")
    typer.echo(f"Vectors: {status.vector_count}")
    typer.echo(f"SQLite chunks: {status.sqlite_chunks}")
    typer.echo(f"Eligible chunks: {status.eligible_chunks}")
    typer.echo(f"Duplicate members skipped: {status.duplicate_members_skipped}")
    typer.echo(f"Stale vectors: {status.stale_vectors}")
    typer.echo(f"Embedding model: {status.model_name}")
    typer.echo(f"Embedding dimension: {status.embedding_dimension}")
    typer.echo(f"Normalized: {status.normalized}")
    typer.echo(f"Embedding schema: {status.embedding_schema_version}")
    typer.echo(f"Chroma path: {status.chroma_path}")


if __name__ == "__main__":
    app()
