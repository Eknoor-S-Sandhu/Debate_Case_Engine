"""Persistence and lexical lookup for :class:`DebateChunk` rows."""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from debate_engine.schemas import (
    ChunkLevel,
    DebateChunk,
    DocumentType,
    Freshness,
    RoundType,
    Side,
    SourceGroup,
)
from debate_engine.storage.db import (
    CHUNK_DATA_COLUMNS,
    CHUNK_KEY_COLUMNS,
    FULL_TEXT_TABLE,
    build_upsert_statement,
    count_by_column,
    dump_json,
    enum_value,
    filter_clause,
    full_text_search_available,
    limit_clause,
    load_json_list,
    temporary_id_table,
    transaction,
    upsert_parameters,
    utc_timestamp,
)

FILTERABLE_COLUMNS: tuple[str, ...] = (
    "document_id",
    "source_group",
    "document_type",
    "section_type",
    "chunk_level",
    "side",
    "round_type",
    "year",
    "freshness",
    "duplicate_group",
    "parent_argument_id",
    "is_special_masterfile",
)

GROUPABLE_COLUMNS: tuple[str, ...] = FILTERABLE_COLUMNS

_COLUMNS = (*CHUNK_KEY_COLUMNS, *CHUNK_DATA_COLUMNS)
_SELECT = f"SELECT {', '.join(_COLUMNS)} FROM chunks"
_UPSERT = build_upsert_statement("chunks", CHUNK_KEY_COLUMNS, CHUNK_DATA_COLUMNS)
_ORDER = "ORDER BY document_id, chunk_level, chunk_id"

_FTS_TOKEN = re.compile(r'"[^"]*"|\S+')
_FTS_UNSAFE = re.compile(r'["*()\-:^]')


class LexicalSearchUnavailableError(RuntimeError):
    """Raised when a database has no FTS5 chunk index to search."""


@dataclass(frozen=True, slots=True)
class LexicalSearchHit:
    """One FTS5 match. ``score`` is BM25, where a lower value ranks better."""

    chunk: DebateChunk
    score: float
    snippet: str


def _row_to_chunk(row: sqlite3.Row) -> DebateChunk:
    return DebateChunk(
        chunk_id=row["chunk_id"],
        document_id=row["document_id"],
        source_file=row["source_file"],
        source_path=row["source_path"],
        source_group=SourceGroup(row["source_group"]),
        document_type=DocumentType(row["document_type"]),
        section_type=row["section_type"],
        chunk_level=ChunkLevel(row["chunk_level"]),
        original_heading=row["original_heading"],
        argument_heading=row["argument_heading"],
        parent_heading=row["parent_heading"],
        heading_path=load_json_list(row["heading_path"]),
        parent_argument_id=row["parent_argument_id"],
        side=Side(row["side"]),
        round_type=RoundType(row["round_type"]),
        year=row["year"],
        text=row["text"],
        token_count=row["token_count"],
        freshness=Freshness(row["freshness"]),
        duplicate_group=row["duplicate_group"],
        priority_weight=row["priority_weight"],
        source_block_indexes=load_json_list(row["source_block_indexes"]),
        structure_confidence=row["structure_confidence"],
        is_special_masterfile=bool(row["is_special_masterfile"]),
        special_masterfile_name=row["special_masterfile_name"],
    )


def _chunk_parameters(chunk: DebateChunk, timestamp: str) -> tuple[object, ...]:
    values = {
        "chunk_id": chunk.chunk_id,
        "document_id": chunk.document_id,
        "source_file": chunk.source_file,
        "source_path": chunk.source_path,
        "source_group": chunk.source_group.value,
        "document_type": chunk.document_type.value,
        "section_type": chunk.section_type,
        "chunk_level": chunk.chunk_level.value,
        "original_heading": chunk.original_heading,
        "argument_heading": chunk.argument_heading,
        "parent_heading": chunk.parent_heading,
        "heading_path": dump_json(chunk.heading_path),
        "parent_argument_id": chunk.parent_argument_id,
        "side": chunk.side.value,
        "round_type": chunk.round_type.value,
        "year": chunk.year,
        "text": chunk.text,
        "token_count": chunk.token_count,
        "freshness": chunk.freshness.value,
        "duplicate_group": chunk.duplicate_group,
        "priority_weight": chunk.priority_weight,
        "source_block_indexes": dump_json(chunk.source_block_indexes),
        "structure_confidence": chunk.structure_confidence,
        "is_special_masterfile": int(chunk.is_special_masterfile),
        "special_masterfile_name": chunk.special_masterfile_name,
    }
    return upsert_parameters(values, CHUNK_KEY_COLUMNS, CHUNK_DATA_COLUMNS, timestamp)


def upsert_chunk(connection: sqlite3.Connection, chunk: DebateChunk) -> None:
    """Insert or update one chunk, keyed on its deterministic ID."""
    upsert_chunks(connection, [chunk])


def upsert_chunks(connection: sqlite3.Connection, chunks: Iterable[DebateChunk]) -> int:
    """Insert or update a batch of chunks atomically.

    Argument-level chunks are written first so that a batch containing both an
    argument and its submodules satisfies ``parent_argument_id`` without
    relying on caller ordering.
    """
    timestamp = utc_timestamp()
    ordered = sorted(chunks, key=lambda chunk: chunk.chunk_level is not ChunkLevel.ARGUMENT)
    parameters = [_chunk_parameters(chunk, timestamp) for chunk in ordered]
    if not parameters:
        return 0
    with transaction(connection):
        connection.executemany(_UPSERT, parameters)
    return len(parameters)


def replace_chunks_for_document(
    connection: sqlite3.Connection,
    document_id: str,
    chunks: Iterable[DebateChunk],
) -> int:
    """Make ``chunks`` the complete chunk set for one document.

    Re-ingesting an edited file must not leave chunks behind that its current
    text no longer produces, so anything missing from the new set is deleted in
    the same transaction that writes the new rows.
    """
    materialized = list(chunks)
    with transaction(connection):
        with temporary_id_table(connection, (chunk.chunk_id for chunk in materialized)) as staged:
            connection.execute(
                "DELETE FROM chunks WHERE document_id = ? "
                f"AND chunk_id NOT IN (SELECT id FROM {staged})",
                (document_id,),
            )
        upsert_chunks(connection, materialized)
    return len(materialized)


def update_duplicate_groups(
    connection: sqlite3.Connection,
    chunks: Iterable[DebateChunk],
) -> int:
    """Write recomputed ``duplicate_group`` assignments onto stored chunks.

    Only rows whose assignment actually changed are touched, so repeating a
    build leaves the chunk table byte-identical.
    """
    timestamp = utc_timestamp()
    parameters = [
        (chunk.duplicate_group, timestamp, chunk.chunk_id, chunk.duplicate_group)
        for chunk in chunks
    ]
    with transaction(connection):
        cursor = connection.executemany(
            "UPDATE chunks SET duplicate_group = ?, updated_at = ? "
            "WHERE chunk_id = ? AND duplicate_group IS NOT ?",
            parameters,
        )
    return cursor.rowcount


def get_chunk(connection: sqlite3.Connection, chunk_id: str) -> DebateChunk | None:
    """Return one chunk by ID, or ``None`` when it is not stored."""
    row = connection.execute(f"{_SELECT} WHERE chunk_id = ?", (chunk_id,)).fetchone()
    return _row_to_chunk(row) if row is not None else None


def list_chunks(
    connection: sqlite3.Connection,
    *,
    document_id: str | None = None,
    source_group: SourceGroup | str | None = None,
    document_type: DocumentType | str | None = None,
    section_type: str | None = None,
    chunk_level: ChunkLevel | str | None = None,
    side: Side | str | None = None,
    round_type: RoundType | str | None = None,
    year: int | None = None,
    freshness: Freshness | str | None = None,
    duplicate_group: str | None = None,
    parent_argument_id: str | None = None,
    is_special_masterfile: bool | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> list[DebateChunk]:
    """List chunks in deterministic order, filtered by persisted metadata."""
    filters = {
        "document_id": document_id,
        "source_group": enum_value(source_group),
        "document_type": enum_value(document_type),
        "section_type": section_type,
        "chunk_level": enum_value(chunk_level),
        "side": enum_value(side),
        "round_type": enum_value(round_type),
        "year": year,
        "freshness": enum_value(freshness),
        "duplicate_group": duplicate_group,
        "parent_argument_id": parent_argument_id,
        "is_special_masterfile": None
        if is_special_masterfile is None
        else int(is_special_masterfile),
    }
    where, parameters = filter_clause(filters, FILTERABLE_COLUMNS)
    tail, tail_parameters = limit_clause(limit, offset)
    rows = connection.execute(
        f"{_SELECT}{where} {_ORDER}{tail}",
        (*parameters, *tail_parameters),
    ).fetchall()
    return [_row_to_chunk(row) for row in rows]


def get_chunks_for_document(
    connection: sqlite3.Connection,
    document_id: str,
) -> list[DebateChunk]:
    """Return every chunk belonging to one document."""
    return list_chunks(connection, document_id=document_id)


def delete_chunk(connection: sqlite3.Connection, chunk_id: str) -> bool:
    """Delete one chunk and its duplicate memberships. Returns whether it existed."""
    with transaction(connection):
        cursor = connection.execute("DELETE FROM chunks WHERE chunk_id = ?", (chunk_id,))
    return cursor.rowcount > 0


def delete_chunks_for_document(connection: sqlite3.Connection, document_id: str) -> int:
    """Delete every chunk of one document, leaving the document row in place."""
    with transaction(connection):
        cursor = connection.execute("DELETE FROM chunks WHERE document_id = ?", (document_id,))
    return cursor.rowcount


def count_chunks(connection: sqlite3.Connection) -> int:
    """Return the total number of persisted chunks."""
    return int(connection.execute("SELECT COUNT(*) AS total FROM chunks").fetchone()["total"])


def count_chunks_by(
    connection: sqlite3.Connection,
    column: str,
    *,
    allowed_columns: Sequence[str] = GROUPABLE_COLUMNS,
) -> dict[str, int]:
    """Count chunks grouped by one whitelisted metadata column."""
    return count_by_column(connection, "chunks", column, allowed_columns)


def build_match_expression(query: str) -> str:
    """Turn a plain query into a conservative FTS5 ``MATCH`` expression.

    Bare terms are quoted and combined with implicit AND so that debate text
    containing hyphens, colons, or parentheses cannot raise an FTS5 syntax
    error. Quoted phrases and trailing ``*`` prefixes are preserved.
    """
    terms: list[str] = []
    for raw_token in _FTS_TOKEN.findall(query):
        if raw_token.startswith('"') and raw_token.endswith('"') and len(raw_token) > 1:
            terms.append(raw_token)
            continue
        prefix = "*" if raw_token.endswith("*") else ""
        cleaned = _FTS_UNSAFE.sub(" ", raw_token).strip()
        if cleaned:
            terms.append(f'"{cleaned}"{prefix}')
    if not terms:
        raise ValueError("lexical search requires at least one searchable term")
    return " AND ".join(terms)


def search_chunks(
    connection: sqlite3.Connection,
    query: str,
    *,
    limit: int = 20,
) -> list[LexicalSearchHit]:
    """Run a lexical FTS5 search over chunk text.

    This is an exact-term debugging and fallback aid. Semantic retrieval is a
    separate layer and is deliberately not implemented here.
    """
    if not full_text_search_available(connection):
        raise LexicalSearchUnavailableError(
            "This database has no FTS5 chunk index. Recreate it with full-text "
            "search enabled to use lexical search."
        )
    rows = connection.execute(
        f"SELECT {', '.join(f'chunks.{column}' for column in _COLUMNS)}, "
        f"bm25({FULL_TEXT_TABLE}) AS score, "
        f"snippet({FULL_TEXT_TABLE}, 0, '[', ']', ' … ', 16) AS snippet "
        f"FROM {FULL_TEXT_TABLE} JOIN chunks ON chunks.rowid = {FULL_TEXT_TABLE}.rowid "
        f"WHERE {FULL_TEXT_TABLE} MATCH ? ORDER BY score, chunks.chunk_id LIMIT ?",
        (build_match_expression(query), limit),
    ).fetchall()
    return [
        LexicalSearchHit(
            chunk=_row_to_chunk(row),
            score=row["score"],
            snippet=row["snippet"],
        )
        for row in rows
    ]
