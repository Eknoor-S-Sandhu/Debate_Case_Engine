"""Inspect the persisted debate knowledge base without modifying it."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated

import typer

from debate_engine.logging import configure_logging
from debate_engine.schemas import DebateChunk
from debate_engine.storage import (
    LexicalSearchUnavailableError,
    count_chunks,
    count_chunks_by,
    count_documents,
    count_documents_by,
    count_duplicate_group_members,
    count_duplicate_groups,
    count_duplicate_groups_by,
    database_connection,
    find_documents_by_filename,
    full_text_search_available,
    get_chunk,
    get_chunks_for_document,
    get_document,
    get_duplicate_group,
    get_duplicate_groups_for_chunk,
    list_documents,
    resolve_database_path,
    schema_version,
    search_chunks,
)

app = typer.Typer(add_completion=False, no_args_is_help=True)

DatabaseOption = Annotated[
    Path | None,
    typer.Option(
        "--database",
        help="Database path. Defaults to the configured data/indexes location.",
    ),
]


@contextmanager
def _open(database: Path | None) -> Iterator[sqlite3.Connection]:
    """Open an existing, initialized database or fail with a clear message."""
    configure_logging()
    path = resolve_database_path(database)
    if not path.exists():
        typer.echo(f"No database at {path}. Run scripts/build_database.py first.", err=True)
        raise typer.Exit(code=1)
    with database_connection(path) as connection:
        if schema_version(connection) == 0:
            typer.echo(f"{path} has no knowledge-base schema.", err=True)
            raise typer.Exit(code=1)
        typer.echo(f"Database: {path}")
        yield connection


def _format_counts(counts: dict[str, int]) -> str:
    return ", ".join(f"{key}={value}" for key, value in sorted(counts.items())) or "none"


def _print_chunk(chunk: DebateChunk, *, show_text: bool) -> None:
    typer.echo(f"  {chunk.chunk_id}")
    typer.echo(f"    level={chunk.chunk_level.value} section_type={chunk.section_type}")
    typer.echo(f"    heading={chunk.original_heading or '(none)'}")
    typer.echo(f"    heading_path={chunk.heading_path}")
    typer.echo(f"    tokens={chunk.token_count} confidence={chunk.structure_confidence:.2f}")
    typer.echo(f"    duplicate_group={chunk.duplicate_group or '(none)'}")
    if show_text:
        for line in chunk.text.splitlines():
            typer.echo(f"      | {line}")


@app.command()
def stats(database: DatabaseOption = None) -> None:
    """Print corpus counts by provenance, type, section, and duplication."""
    with _open(database) as connection:
        typer.echo(f"Schema version: {schema_version(connection)}")
        typer.echo(f"Full-text search: {'yes' if full_text_search_available(connection) else 'no'}")
        typer.echo(f"Documents: {count_documents(connection)}")
        typer.echo(f"Chunks: {count_chunks(connection)}")
        typer.echo(f"Duplicate groups: {count_duplicate_groups(connection)}")
        typer.echo(f"Duplicate members: {count_duplicate_group_members(connection)}")
        document_source_counts = count_documents_by(connection, "source_group")
        typer.echo(f"Documents by source_group: {_format_counts(document_source_counts)}")
        typer.echo(
            f"Documents by document_type: "
            f"{_format_counts(count_documents_by(connection, 'document_type'))}"
        )
        typer.echo(
            f"Chunks by source_group: {_format_counts(count_chunks_by(connection, 'source_group'))}"
        )
        typer.echo(
            f"Chunks by document_type: "
            f"{_format_counts(count_chunks_by(connection, 'document_type'))}"
        )
        typer.echo(
            f"Chunks by section_type: {_format_counts(count_chunks_by(connection, 'section_type'))}"
        )
        typer.echo(
            f"Chunks by chunk_level: {_format_counts(count_chunks_by(connection, 'chunk_level'))}"
        )
        typer.echo(
            f"Duplicate groups by type: {_format_counts(count_duplicate_groups_by(connection))}"
        )


@app.command()
def documents(
    database: DatabaseOption = None,
    source_group: Annotated[
        str | None,
        typer.Option(help="Filter by source_group, for example personal."),
    ] = None,
    document_type: Annotated[
        str | None,
        typer.Option(help="Filter by document_type, for example masterfile."),
    ] = None,
    limit: Annotated[int | None, typer.Option(min=1, help="Show only N documents.")] = 20,
) -> None:
    """List stored documents with their IDs for use in other commands."""
    with _open(database) as connection:
        stored = list_documents(
            connection,
            source_group=source_group,
            document_type=document_type,
            limit=limit,
        )
        typer.echo(f"Documents listed: {len(stored)}")
        for item in stored:
            typer.echo(
                f"  {item.document_id}  {item.source_group.value:<10} "
                f"{item.document_type.value:<11} {item.filename}"
            )


@app.command()
def document(
    identifier: Annotated[str, typer.Argument(help="A document_id or part of a filename.")],
    database: DatabaseOption = None,
    show_text: Annotated[bool, typer.Option(help="Print each chunk's stored text.")] = False,
) -> None:
    """Inspect one document and the chunks stored for it."""
    with _open(database) as connection:
        stored = get_document(connection, identifier)
        if stored is None:
            matches = find_documents_by_filename(connection, identifier)
            if not matches:
                typer.echo(f"No document matches {identifier!r}.", err=True)
                raise typer.Exit(code=1)
            if len(matches) > 1:
                typer.echo(f"{identifier!r} matches {len(matches)} documents:", err=True)
                for match in matches:
                    typer.echo(f"  {match.document_id}  {match.filename}", err=True)
                raise typer.Exit(code=1)
            stored = matches[0]

        typer.echo(f"Document: {stored.document_id}")
        typer.echo(f"Filename: {stored.filename}")
        typer.echo(f"Path: {stored.full_path}")
        typer.echo(f"Title: {stored.title or '(none)'}")
        typer.echo(f"Source group: {stored.source_group.value}")
        typer.echo(f"Document type: {stored.document_type.value}")
        typer.echo(f"Side: {stored.side.value}")
        typer.echo(f"Round type: {stored.round_type.value}")
        typer.echo(f"Year: {stored.year if stored.year is not None else '(unknown)'}")
        typer.echo(f"Priority weight: {stored.priority_weight}")
        typer.echo(f"Raw text characters: {len(stored.raw_text)}")

        chunks = get_chunks_for_document(connection, stored.document_id)
        typer.echo(f"Chunks: {len(chunks)}")
        for chunk in chunks:
            _print_chunk(chunk, show_text=show_text)


@app.command()
def chunk(
    chunk_id: Annotated[str, typer.Argument(help="A stored chunk_id.")],
    database: DatabaseOption = None,
    show_text: Annotated[bool, typer.Option(help="Print the stored chunk text.")] = True,
) -> None:
    """Inspect one chunk and any duplicate group containing it."""
    with _open(database) as connection:
        stored = get_chunk(connection, chunk_id)
        if stored is None:
            typer.echo(f"No chunk with id {chunk_id!r}.", err=True)
            raise typer.Exit(code=1)

        typer.echo(f"Chunk: {stored.chunk_id}")
        typer.echo(f"Document: {stored.document_id}")
        typer.echo(f"Source: {stored.source_group.value} / {stored.source_file}")
        typer.echo(f"Path: {stored.source_path}")
        typer.echo(f"Level: {stored.chunk_level.value}")
        typer.echo(f"Section type: {stored.section_type}")
        typer.echo(f"Original heading: {stored.original_heading or '(none)'}")
        typer.echo(f"Argument heading: {stored.argument_heading or '(none)'}")
        typer.echo(f"Parent heading: {stored.parent_heading or '(none)'}")
        typer.echo(f"Heading path: {stored.heading_path}")
        typer.echo(f"Parent argument: {stored.parent_argument_id or '(none)'}")
        typer.echo(f"Side / round: {stored.side.value} / {stored.round_type.value}")
        typer.echo(f"Freshness: {stored.freshness.value}")
        typer.echo(f"Tokens: {stored.token_count}")
        typer.echo(f"Source blocks: {stored.source_block_indexes}")
        typer.echo(f"Structure confidence: {stored.structure_confidence:.2f}")
        typer.echo(f"Priority weight: {stored.priority_weight}")
        typer.echo(
            "Special masterfile: "
            f"{stored.special_masterfile_name if stored.is_special_masterfile else 'no'}"
        )
        typer.echo(f"Duplicate group: {stored.duplicate_group or '(none)'}")
        for group in get_duplicate_groups_for_chunk(connection, stored.chunk_id):
            typer.echo(
                f"  member of {group.duplicate_group_id} "
                f"({group.duplicate_type.value}, {len(group.member_chunk_ids)} members)"
            )
        if show_text:
            for line in stored.text.splitlines():
                typer.echo(f"  | {line}")


@app.command("duplicate-group")
def duplicate_group(
    duplicate_group_id: Annotated[str, typer.Argument(help="A stored duplicate_group_id.")],
    database: DatabaseOption = None,
    show_text: Annotated[bool, typer.Option(help="Print each member's stored text.")] = False,
) -> None:
    """Inspect one duplicate group and every preserved member."""
    with _open(database) as connection:
        group = get_duplicate_group(connection, duplicate_group_id)
        if group is None:
            typer.echo(f"No duplicate group with id {duplicate_group_id!r}.", err=True)
            raise typer.Exit(code=1)

        typer.echo(f"Duplicate group: {group.duplicate_group_id}")
        typer.echo(f"Type: {group.duplicate_type.value}")
        typer.echo(f"Representative: {group.representative_chunk_id}")
        typer.echo(f"Similarity range: {group.similarity_min:.4f}-{group.similarity_max:.4f}")
        for note in group.notes:
            typer.echo(f"Note: {note}")
        typer.echo(f"Members: {len(group.member_chunk_ids)}")
        for index, member_id in enumerate(group.member_chunk_ids, start=1):
            member = get_chunk(connection, member_id)
            if member is None:
                typer.echo(f"  {index}. {member_id} (missing)")
                continue
            marker = " *representative" if member_id == group.representative_chunk_id else ""
            typer.echo(
                f"  {index}. {member.source_group.value} / {member.source_file} / "
                f"{member_id}{marker}"
            )
            if show_text:
                for line in member.text.splitlines():
                    typer.echo(f"      | {line}")


@app.command()
def search(
    query: Annotated[str, typer.Argument(help="Lexical terms to look for in chunk text.")],
    database: DatabaseOption = None,
    limit: Annotated[int, typer.Option(min=1, help="Maximum number of matches.")] = 10,
    show_text: Annotated[bool, typer.Option(help="Print each match's full text.")] = False,
) -> None:
    """Run an exact-term FTS5 search. This is not semantic retrieval."""
    with _open(database) as connection:
        try:
            hits = search_chunks(connection, query, limit=limit)
        except LexicalSearchUnavailableError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=1) from exc
        except ValueError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=2) from exc

        typer.echo(f"Matches: {len(hits)}")
        for index, hit in enumerate(hits, start=1):
            typer.echo(
                f"  {index}. score={hit.score:.4f} {hit.chunk.source_group.value} / "
                f"{hit.chunk.source_file} / {hit.chunk.chunk_id}"
            )
            typer.echo(f"     {hit.snippet}")
            if show_text:
                for line in hit.chunk.text.splitlines():
                    typer.echo(f"      | {line}")


if __name__ == "__main__":
    app()
