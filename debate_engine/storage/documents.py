"""Persistence for :class:`DebateDocument` rows."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Sequence

from debate_engine.schemas import DebateDocument, DocumentType, RoundType, Side, SourceGroup
from debate_engine.storage.db import (
    DOCUMENT_DATA_COLUMNS,
    DOCUMENT_KEY_COLUMNS,
    build_upsert_statement,
    count_by_column,
    enum_value,
    filter_clause,
    limit_clause,
    transaction,
    upsert_parameters,
    utc_timestamp,
)

FILTERABLE_COLUMNS: tuple[str, ...] = (
    "source_group",
    "document_type",
    "side",
    "round_type",
    "year",
)

GROUPABLE_COLUMNS: tuple[str, ...] = FILTERABLE_COLUMNS

_SELECT = f"SELECT {', '.join((*DOCUMENT_KEY_COLUMNS, *DOCUMENT_DATA_COLUMNS))} FROM documents"
_UPSERT = build_upsert_statement("documents", DOCUMENT_KEY_COLUMNS, DOCUMENT_DATA_COLUMNS)


def _row_to_document(row: sqlite3.Row) -> DebateDocument:
    return DebateDocument(
        document_id=row["document_id"],
        filename=row["filename"],
        full_path=row["full_path"],
        source_group=SourceGroup(row["source_group"]),
        document_type=DocumentType(row["document_type"]),
        side=Side(row["side"]),
        round_type=RoundType(row["round_type"]),
        year=row["year"],
        title=row["title"],
        raw_text=row["raw_text"],
        priority_weight=row["priority_weight"],
    )


def _document_parameters(document: DebateDocument, timestamp: str) -> tuple[object, ...]:
    values = {
        "document_id": document.document_id,
        "filename": document.filename,
        "full_path": document.full_path,
        "source_group": document.source_group.value,
        "document_type": document.document_type.value,
        "side": document.side.value,
        "round_type": document.round_type.value,
        "year": document.year,
        "title": document.title,
        "raw_text": document.raw_text,
        "priority_weight": document.priority_weight,
    }
    return upsert_parameters(values, DOCUMENT_KEY_COLUMNS, DOCUMENT_DATA_COLUMNS, timestamp)


def upsert_document(connection: sqlite3.Connection, document: DebateDocument) -> None:
    """Insert or update one document, keyed on its deterministic ID."""
    upsert_documents(connection, [document])


def upsert_documents(
    connection: sqlite3.Connection,
    documents: Iterable[DebateDocument],
) -> int:
    """Insert or update a batch of documents atomically.

    Returns the number of documents written. A failure anywhere in the batch
    rolls the whole batch back rather than leaving partial rows behind.
    """
    timestamp = utc_timestamp()
    parameters = [_document_parameters(document, timestamp) for document in documents]
    if not parameters:
        return 0
    with transaction(connection):
        connection.executemany(_UPSERT, parameters)
    return len(parameters)


def get_document(connection: sqlite3.Connection, document_id: str) -> DebateDocument | None:
    """Return one document by ID, or ``None`` when it is not stored."""
    row = connection.execute(
        f"{_SELECT} WHERE document_id = ?",
        (document_id,),
    ).fetchone()
    return _row_to_document(row) if row is not None else None


def list_documents(
    connection: sqlite3.Connection,
    *,
    source_group: SourceGroup | str | None = None,
    document_type: DocumentType | str | None = None,
    side: Side | str | None = None,
    round_type: RoundType | str | None = None,
    year: int | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> list[DebateDocument]:
    """List documents in deterministic filename order, filtered by metadata."""
    filters = {
        "source_group": enum_value(source_group),
        "document_type": enum_value(document_type),
        "side": enum_value(side),
        "round_type": enum_value(round_type),
        "year": year,
    }
    where, parameters = filter_clause(filters, FILTERABLE_COLUMNS)
    tail, tail_parameters = limit_clause(limit, offset)
    rows = connection.execute(
        f"{_SELECT}{where} ORDER BY filename, document_id{tail}",
        (*parameters, *tail_parameters),
    ).fetchall()
    return [_row_to_document(row) for row in rows]


def find_documents_by_filename(
    connection: sqlite3.Connection,
    filename: str,
) -> list[DebateDocument]:
    """Find documents whose filename contains ``filename`` (case-insensitive)."""
    rows = connection.execute(
        f"{_SELECT} WHERE filename LIKE ? ESCAPE '\\' ORDER BY filename, document_id",
        (f"%{_escape_like(filename)}%",),
    ).fetchall()
    return [_row_to_document(row) for row in rows]


def delete_document(connection: sqlite3.Connection, document_id: str) -> bool:
    """Delete one document and cascade to its chunks. Returns whether it existed."""
    with transaction(connection):
        cursor = connection.execute("DELETE FROM documents WHERE document_id = ?", (document_id,))
    return cursor.rowcount > 0


def count_documents(connection: sqlite3.Connection) -> int:
    """Return the total number of persisted documents."""
    return int(connection.execute("SELECT COUNT(*) AS total FROM documents").fetchone()["total"])


def count_documents_by(
    connection: sqlite3.Connection,
    column: str,
    *,
    allowed_columns: Sequence[str] = GROUPABLE_COLUMNS,
) -> dict[str, int]:
    """Count documents grouped by one whitelisted metadata column."""
    return count_by_column(connection, "documents", column, allowed_columns)


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
