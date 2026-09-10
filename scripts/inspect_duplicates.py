"""Inspect in-memory duplicate groups for one file or a local folder."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from debate_engine.ingestion import (
    chunk_structured_document,
    detect_duplicates,
    detect_structure,
    discover_files,
    parse_document,
)
from debate_engine.logging import configure_logging
from debate_engine.schemas import ChunkingMetadata, DebateChunk

app = typer.Typer(add_completion=False, no_args_is_help=True)


def _chunks_from_file(path: Path, metadata: ChunkingMetadata | None = None) -> list[DebateChunk]:
    parsed = parse_document(path)
    structured = detect_structure(parsed)
    return chunk_structured_document(structured, metadata)


@app.command()
def inspect(
    source: Annotated[
        Path,
        typer.Argument(
            exists=True,
            readable=True,
            resolve_path=True,
            help="A supported debate file or archive folder.",
        ),
    ],
    show_text: Annotated[
        bool,
        typer.Option(help="Print every duplicate member's original text."),
    ] = False,
    only_duplicates: Annotated[
        bool,
        typer.Option(help="Hide singleton chunk summaries."),
    ] = False,
    limit: Annotated[
        int | None,
        typer.Option(min=1, help="Process only the first N discovered files."),
    ] = None,
) -> None:
    """Print deterministic duplicate groups without writing or deleting data."""
    configure_logging()
    chunks: list[DebateChunk] = []

    if source.is_file():
        chunks.extend(_chunks_from_file(source))
        files_processed = 1
    else:
        discovery = discover_files(source)
        selected = discovery.files[:limit] if limit is not None else discovery.files
        for item in selected:
            chunks.extend(
                _chunks_from_file(
                    item.path,
                    ChunkingMetadata(source_group=item.source_group),
                )
            )
        files_processed = len(selected)

    result = detect_duplicates(chunks)
    chunks_by_id = {chunk.chunk_id: chunk for chunk in result.updated_chunks}

    typer.echo(f"Source: {source}")
    typer.echo(f"Files processed: {files_processed}")
    typer.echo(f"Chunks inspected: {result.statistics.total_chunks}")
    typer.echo(f"Duplicate groups: {result.statistics.duplicate_groups}")
    typer.echo(f"Grouped chunks: {result.statistics.grouped_chunks}")
    typer.echo(f"Fuzzy candidates: {result.statistics.candidate_pairs}")
    typer.echo(f"Fuzzy comparisons: {result.statistics.compared_pairs}")

    for group in result.duplicate_groups:
        representative = chunks_by_id[group.representative_chunk_id]
        typer.echo(f"\nDuplicate Group: {group.duplicate_group_id}")
        typer.echo(f"Type: {group.duplicate_type.value}")
        typer.echo(
            "Representative: "
            f"{representative.source_group.value} / {representative.source_file} / "
            f"{representative.chunk_id}"
        )
        typer.echo("Members:")
        for index, member_id in enumerate(group.member_chunk_ids, start=1):
            member = chunks_by_id[member_id]
            typer.echo(f"{index}. {member.source_group.value} / {member.source_file} / {member_id}")
            if show_text:
                for line in member.text.splitlines():
                    typer.echo(f"     | {line}")
        typer.echo(f"Similarity range: {group.similarity_min:.4f}–{group.similarity_max:.4f}")
        for note in group.notes:
            typer.echo(f"Note: {note}")

    if not only_duplicates:
        singleton_chunks = [
            chunk for chunk in result.updated_chunks if chunk.duplicate_group is None
        ]
        if singleton_chunks:
            typer.echo(f"\nSingleton chunks ({len(singleton_chunks)}):")
            for chunk in singleton_chunks:
                typer.echo(f"- {chunk.source_group.value} / {chunk.source_file} / {chunk.chunk_id}")


if __name__ == "__main__":
    app()
