"""Build the SQLite knowledge base from a local debate archive."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Annotated

import typer

from debate_engine.logging import configure_logging
from debate_engine.pipeline import BuildReport, build_database

app = typer.Typer(add_completion=False, no_args_is_help=True)


def _print_summary(report: BuildReport) -> None:
    typer.echo("Debate knowledge-base build")
    typer.echo(f"Archive: {report.archive_root}")
    typer.echo(f"Database: {report.database_path}")
    typer.echo(f"Mode: {'rebuild' if report.rebuilt else 'upsert'}")
    typer.echo(f"Files discovered: {report.files_discovered}")
    typer.echo(f"Files attempted: {report.files_attempted}")
    typer.echo(f"Unsupported files skipped: {report.unsupported_files_skipped}")
    typer.echo(f"Documents persisted: {report.documents_persisted}")
    typer.echo(f"Chunks persisted: {report.chunks_persisted}")
    typer.echo(f"Documents without chunks: {report.documents_without_chunks}")
    typer.echo(f"Duplicate groups: {report.duplicate_groups_persisted}")
    typer.echo(f"Duplicate members: {report.duplicate_members_persisted}")
    typer.echo(f"Partial parses: {report.partial_parses}")

    counts = report.failure_counts
    typer.echo(f"Parse failures: {counts['parse']}")
    typer.echo(f"Needs OCR: {counts['needs_ocr']}")
    typer.echo(f"Legacy .doc failures: {counts['legacy_doc']}")
    typer.echo(f"Unsupported parses: {counts['unsupported']}")
    typer.echo(f"Structure failures: {counts['structure']}")
    typer.echo(f"Chunking failures: {counts['chunking']}")
    typer.echo(f"Persistence failures: {counts['persistence']}")
    typer.echo(f"Deduplication failures: {counts['deduplication']}")
    typer.echo(f"Elapsed: {report.elapsed_seconds:.2f}s")

    if report.failures:
        typer.echo(f"\nFailures ({len(report.failures)}):")
        for failure in report.failures:
            typer.echo(f"  - [{failure.kind.value}] {failure.path}: {failure.detail}")
        by_kind = Counter(failure.kind.value for failure in report.failures)
        typer.echo(
            "No placeholder text was invented for these files; rerun after fixing them. "
            f"Affected kinds: {', '.join(sorted(by_kind))}."
        )


@app.command()
def build(
    archive: Annotated[
        Path,
        typer.Argument(
            exists=True,
            file_okay=False,
            readable=True,
            resolve_path=True,
            help="Root folder of the debate archive.",
        ),
    ],
    database: Annotated[
        Path | None,
        typer.Option(help="Database path. Defaults to the configured data/indexes location."),
    ] = None,
    rebuild: Annotated[
        bool,
        typer.Option(help="Drop and recreate the database before ingesting."),
    ] = False,
    limit: Annotated[
        int | None,
        typer.Option(min=1, help="Ingest only the first N discovered files."),
    ] = None,
) -> None:
    """Discover, parse, chunk, deduplicate, and persist an archive."""
    configure_logging()
    report = build_database(archive, database=database, rebuild=rebuild, limit=limit)
    _print_summary(report)


if __name__ == "__main__":
    app()
