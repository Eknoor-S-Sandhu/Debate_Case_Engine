"""Persistence for duplicate groups and their preserved membership lists."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable

from debate_engine.schemas import DuplicateGroup, DuplicateType
from debate_engine.storage.db import (
    DUPLICATE_GROUP_DATA_COLUMNS,
    DUPLICATE_GROUP_KEY_COLUMNS,
    build_upsert_statement,
    count_by_column,
    dump_json,
    enum_value,
    filter_clause,
    limit_clause,
    load_json_list,
    temporary_id_table,
    transaction,
    upsert_parameters,
    utc_timestamp,
)

FILTERABLE_COLUMNS: tuple[str, ...] = ("duplicate_type", "representative_chunk_id")

GROUPABLE_COLUMNS: tuple[str, ...] = ("duplicate_type",)

_COLUMNS = (*DUPLICATE_GROUP_KEY_COLUMNS, *DUPLICATE_GROUP_DATA_COLUMNS)
_SELECT = f"SELECT {', '.join(_COLUMNS)} FROM duplicate_groups"
_UPSERT = build_upsert_statement(
    "duplicate_groups",
    DUPLICATE_GROUP_KEY_COLUMNS,
    DUPLICATE_GROUP_DATA_COLUMNS,
)
_INSERT_MEMBER = (
    "INSERT INTO duplicate_group_members (duplicate_group_id, chunk_id, member_index) "
    "VALUES (?, ?, ?) "
    "ON CONFLICT(duplicate_group_id, chunk_id) DO UPDATE SET member_index = excluded.member_index "
    "WHERE duplicate_group_members.member_index IS NOT excluded.member_index"
)


def _group_parameters(group: DuplicateGroup, timestamp: str) -> tuple[object, ...]:
    values = {
        "duplicate_group_id": group.duplicate_group_id,
        "duplicate_type": group.duplicate_type.value,
        "representative_chunk_id": group.representative_chunk_id,
        "similarity_min": group.similarity_min,
        "similarity_max": group.similarity_max,
        "notes": dump_json(group.notes),
    }
    return upsert_parameters(
        values,
        DUPLICATE_GROUP_KEY_COLUMNS,
        DUPLICATE_GROUP_DATA_COLUMNS,
        timestamp,
    )


def _row_to_group(connection: sqlite3.Connection, row: sqlite3.Row) -> DuplicateGroup:
    return DuplicateGroup(
        duplicate_group_id=row["duplicate_group_id"],
        member_chunk_ids=get_duplicate_members(connection, row["duplicate_group_id"]),
        representative_chunk_id=row["representative_chunk_id"],
        duplicate_type=DuplicateType(row["duplicate_type"]),
        similarity_min=row["similarity_min"],
        similarity_max=row["similarity_max"],
        notes=load_json_list(row["notes"]),
    )


def upsert_duplicate_group(connection: sqlite3.Connection, group: DuplicateGroup) -> None:
    """Insert or update one duplicate group and its membership rows."""
    upsert_duplicate_groups(connection, [group])


def upsert_duplicate_groups(
    connection: sqlite3.Connection,
    groups: Iterable[DuplicateGroup],
) -> int:
    """Insert or update duplicate groups and memberships in one transaction.

    Membership is replaced rather than merged: a member removed from a regrouped
    set must not linger. Every member chunk and the representative must already
    be persisted, since both are enforced foreign keys.
    """
    timestamp = utc_timestamp()
    materialized = list(groups)
    if not materialized:
        return 0
    for group in materialized:
        if group.representative_chunk_id not in group.member_chunk_ids:
            raise ValueError(
                f"representative {group.representative_chunk_id!r} is not a member "
                f"of duplicate group {group.duplicate_group_id!r}"
            )

    with transaction(connection):
        connection.executemany(
            _UPSERT,
            [_group_parameters(group, timestamp) for group in materialized],
        )
        for group in materialized:
            if group.member_chunk_ids:
                placeholders = ", ".join("?" for _ in group.member_chunk_ids)
                connection.execute(
                    "DELETE FROM duplicate_group_members "
                    f"WHERE duplicate_group_id = ? AND chunk_id NOT IN ({placeholders})",
                    (group.duplicate_group_id, *group.member_chunk_ids),
                )
            else:
                connection.execute(
                    "DELETE FROM duplicate_group_members WHERE duplicate_group_id = ?",
                    (group.duplicate_group_id,),
                )
            connection.executemany(
                _INSERT_MEMBER,
                [
                    (group.duplicate_group_id, chunk_id, index)
                    for index, chunk_id in enumerate(group.member_chunk_ids)
                ],
            )
    return len(materialized)


def replace_duplicate_groups(
    connection: sqlite3.Connection,
    groups: Iterable[DuplicateGroup],
) -> int:
    """Make ``groups`` the complete duplicate-group set for the database.

    Duplicate detection is recomputed over every stored chunk, so a group that
    the current pass did not produce is stale and is deleted. Groups that are
    unchanged keep their original ``created_at``.
    """
    materialized = list(groups)
    with transaction(connection):
        with temporary_id_table(
            connection,
            (group.duplicate_group_id for group in materialized),
        ) as staged:
            connection.execute(
                "DELETE FROM duplicate_groups "
                f"WHERE duplicate_group_id NOT IN (SELECT id FROM {staged})"
            )
        upsert_duplicate_groups(connection, materialized)
    return len(materialized)


def get_duplicate_group(
    connection: sqlite3.Connection,
    duplicate_group_id: str,
) -> DuplicateGroup | None:
    """Return one duplicate group with its members, or ``None`` if absent."""
    row = connection.execute(
        f"{_SELECT} WHERE duplicate_group_id = ?",
        (duplicate_group_id,),
    ).fetchone()
    return _row_to_group(connection, row) if row is not None else None


def get_duplicate_members(
    connection: sqlite3.Connection,
    duplicate_group_id: str,
) -> list[str]:
    """Return the member chunk IDs of a group in their original order."""
    rows = connection.execute(
        "SELECT chunk_id FROM duplicate_group_members "
        "WHERE duplicate_group_id = ? ORDER BY member_index, chunk_id",
        (duplicate_group_id,),
    ).fetchall()
    return [row["chunk_id"] for row in rows]


def list_duplicate_groups(
    connection: sqlite3.Connection,
    *,
    duplicate_type: DuplicateType | str | None = None,
    representative_chunk_id: str | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> list[DuplicateGroup]:
    """List duplicate groups in deterministic ID order."""
    filters = {
        "duplicate_type": enum_value(duplicate_type),
        "representative_chunk_id": representative_chunk_id,
    }
    where, parameters = filter_clause(filters, FILTERABLE_COLUMNS)
    tail, tail_parameters = limit_clause(limit, offset)
    rows = connection.execute(
        f"{_SELECT}{where} ORDER BY duplicate_group_id{tail}",
        (*parameters, *tail_parameters),
    ).fetchall()
    return [_row_to_group(connection, row) for row in rows]


def get_duplicate_groups_for_chunk(
    connection: sqlite3.Connection,
    chunk_id: str,
) -> list[DuplicateGroup]:
    """Return every group that contains ``chunk_id`` as a member."""
    rows = connection.execute(
        f"{_SELECT} WHERE duplicate_group_id IN ("
        "SELECT duplicate_group_id FROM duplicate_group_members WHERE chunk_id = ?"
        ") ORDER BY duplicate_group_id",
        (chunk_id,),
    ).fetchall()
    return [_row_to_group(connection, row) for row in rows]


def delete_duplicate_group(connection: sqlite3.Connection, duplicate_group_id: str) -> bool:
    """Delete one group and cascade to its membership rows."""
    with transaction(connection):
        cursor = connection.execute(
            "DELETE FROM duplicate_groups WHERE duplicate_group_id = ?",
            (duplicate_group_id,),
        )
    return cursor.rowcount > 0


def count_duplicate_groups(connection: sqlite3.Connection) -> int:
    """Return the total number of persisted duplicate groups."""
    return int(
        connection.execute("SELECT COUNT(*) AS total FROM duplicate_groups").fetchone()["total"]
    )


def count_duplicate_group_members(connection: sqlite3.Connection) -> int:
    """Return the total number of persisted membership rows."""
    return int(
        connection.execute("SELECT COUNT(*) AS total FROM duplicate_group_members").fetchone()[
            "total"
        ]
    )


def count_duplicate_groups_by(
    connection: sqlite3.Connection,
    column: str = "duplicate_type",
) -> dict[str, int]:
    """Count duplicate groups grouped by one whitelisted column."""
    return count_by_column(connection, "duplicate_groups", column, GROUPABLE_COLUMNS)
