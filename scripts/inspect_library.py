"""Inspect and parse a debate archive without persisting any results."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Annotated

import typer

from debate_engine.ingestion import discover_files, parse_documents
from debate_engine.logging import configure_logging
from debate_engine.schemas import ParseStatus

app = typer.Typer(add_completion=False, no_args_is_help=True)


def _format_counts(counts: Counter[str]) -> str:
    return ", ".join(f"{key}={counts[key]}" for key in sorted(counts)) or "none"


@app.command()
def inspect(
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
    limit: Annotated[
        int | None,
        typer.Option(min=1, help="Parse only the first N discovered files."),
    ] = None,
) -> None:
    """Discover supported documents, parse them, and print an audit summary."""
    configure_logging()
    discovery = discover_files(archive)
    selected_files = discovery.files[:limit] if limit is not None else discovery.files
    parsed = parse_documents(item.path for item in selected_files)

    extension_counts = Counter(item.extension for item in discovery.files)
    source_counts = Counter(item.source_group.value for item in discovery.files)
    status_counts = Counter(item.parse_status.value for item in parsed)
    legacy_doc_failures = sum(
        item.extension == ".doc"
        and result.parse_status in {ParseStatus.FAILED, ParseStatus.UNSUPPORTED}
        for item, result in zip(selected_files, parsed, strict=True)
    )

    typer.echo("Debate library inspection")
    typer.echo(f"Root: {discovery.root}")
    typer.echo(f"Files discovered: {len(discovery.files)}")
    typer.echo(f"Files attempted: {len(selected_files)}")
    typer.echo(f"By extension: {_format_counts(extension_counts)}")
    typer.echo(f"By source_group: {_format_counts(source_counts)}")
    typer.echo(f"Successful parses: {status_counts[ParseStatus.SUCCESS.value]}")
    typer.echo(f"Partial parses: {status_counts[ParseStatus.PARTIAL.value]}")
    typer.echo(f"Failed parses: {status_counts[ParseStatus.FAILED.value]}")
    typer.echo(f"Needs OCR: {status_counts[ParseStatus.NEEDS_OCR.value]}")
    typer.echo(f"Unsupported parses: {status_counts[ParseStatus.UNSUPPORTED.value]}")
    typer.echo(f"Legacy .doc failures: {legacy_doc_failures}")
    typer.echo(f"Unsupported files skipped: {len(discovery.unsupported)}")

    if discovery.unsupported:
        typer.echo("\nUnsupported files:")
        for entry in discovery.unsupported:
            typer.echo(f"  - {entry.relative_path}: {entry.detail}")

    problem_statuses = {
        ParseStatus.PARTIAL,
        ParseStatus.FAILED,
        ParseStatus.UNSUPPORTED,
        ParseStatus.NEEDS_OCR,
    }
    problems = [result for result in parsed if result.parse_status in problem_statuses]
    if problems:
        typer.echo("\nParser warnings:")
        for result in problems:
            summary = result.error_message or "; ".join(result.warnings) or "no details"
            typer.echo(f"  - {result.filename} [{result.parse_status.value}]: {summary}")


if __name__ == "__main__":
    app()
