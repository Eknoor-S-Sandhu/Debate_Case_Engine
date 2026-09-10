"""Synchronize authoritative SQLite chunks into the derived Chroma index."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from debate_engine.config import get_settings
from debate_engine.logging import configure_logging
from debate_engine.retrieval import VectorIndexConfigurationError, VectorStore

app = typer.Typer(add_completion=False)


@app.command()
def build(
    database: Annotated[
        Path | None,
        typer.Option(help="SQLite path. Defaults to the configured database."),
    ] = None,
    rebuild: Annotated[
        bool,
        typer.Option(help="Delete and recreate the Chroma collection first."),
    ] = False,
    batch_size: Annotated[
        int | None,
        typer.Option(min=1, help="Embedding batch size for this run."),
    ] = None,
    include_duplicates: Annotated[
        bool,
        typer.Option(help="Index all duplicate members instead of representatives only."),
    ] = False,
    limit: Annotated[
        int | None,
        typer.Option(min=1, help="Embed at most the first N eligible chunks."),
    ] = None,
) -> None:
    """Build or incrementally synchronize the local vector index."""
    configure_logging()
    settings = get_settings()
    database_path = database or settings.storage.database_path
    if not database_path.exists():
        typer.echo(
            f"SQLite database does not exist at {database_path}. "
            "Run scripts/build_database.py first.",
            err=True,
        )
        raise typer.Exit(code=1)

    store = VectorStore(settings)
    try:
        report = store.sync(
            database=database_path,
            rebuild=rebuild,
            include_duplicate_members=include_duplicates,
            batch_size=batch_size,
            limit=limit,
        )
    except VectorIndexConfigurationError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    typer.echo("Debate vector-index build")
    typer.echo(f"Mode: {'rebuild' if rebuild else 'incremental'}")
    typer.echo(f"SQLite database: {database_path}")
    typer.echo(f"SQLite chunks found: {report.sqlite_chunks_found}")
    typer.echo(f"Eligible chunks: {report.eligible_chunks}")
    typer.echo(f"Duplicate members skipped: {report.duplicate_members_skipped}")
    typer.echo(f"Invalid chunks skipped: {report.invalid_chunks_skipped}")
    typer.echo(f"Vectors already current: {report.vectors_already_current}")
    typer.echo(f"Vectors embedded: {report.vectors_embedded}")
    typer.echo(f"Vectors updated: {report.vectors_updated}")
    typer.echo(f"Stale vectors deleted: {report.stale_vectors_deleted}")
    typer.echo(f"Failed chunks: {report.failed_chunks}")
    typer.echo(f"Embedding model: {settings.embedding_model_name}")
    typer.echo(f"Embedding dimension: {settings.embedding_dimension}")
    typer.echo(f"Normalized embeddings: {settings.vector_index.normalize_embeddings}")
    typer.echo(f"Embedding schema: {settings.vector_index.embedding_text_schema_version}")
    typer.echo(f"Collection: {settings.vector_index.collection_name}")
    typer.echo(f"Chroma path: {settings.vector_index.chroma_path}")
    typer.echo(f"Elapsed: {report.elapsed_seconds:.2f}s")
    if report.failures:
        typer.echo("\nFailures:")
        for failure in report.failures:
            typer.echo(f"  - {', '.join(failure.chunk_ids)}: {failure.detail}")


if __name__ == "__main__":
    app()
