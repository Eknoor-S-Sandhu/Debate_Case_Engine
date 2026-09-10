"""SQLite schema, connections, and transaction helpers for the knowledge base.

Every SQL statement used by the storage layer is defined here so the schema can
be read in one place. Repository modules bind values as parameters and never
interpolate caller input into SQL; the only interpolated names are the column
tuples defined below.

The database holds structured metadata and original text only. Embeddings and
the vector index are a separate, later concern and never touch these tables.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from debate_engine.config import Settings, get_settings
from debate_engine.logging import get_logger

LOGGER = get_logger("storage.db")

SCHEMA_VERSION = 1

FULL_TEXT_TABLE = "chunk_search"

DOCUMENT_KEY_COLUMNS: tuple[str, ...] = ("document_id",)
DOCUMENT_DATA_COLUMNS: tuple[str, ...] = (
    "filename",
    "full_path",
    "source_group",
    "document_type",
    "side",
    "round_type",
    "year",
    "title",
    "raw_text",
    "priority_weight",
)

CHUNK_KEY_COLUMNS: tuple[str, ...] = ("chunk_id",)
CHUNK_DATA_COLUMNS: tuple[str, ...] = (
    "document_id",
    "source_file",
    "source_path",
    "source_group",
    "document_type",
    "section_type",
    "chunk_level",
    "original_heading",
    "argument_heading",
    "parent_heading",
    "heading_path",
    "parent_argument_id",
    "side",
    "round_type",
    "year",
    "text",
    "token_count",
    "freshness",
    "duplicate_group",
    "priority_weight",
    "source_block_indexes",
    "structure_confidence",
    "is_special_masterfile",
    "special_masterfile_name",
)

DUPLICATE_GROUP_KEY_COLUMNS: tuple[str, ...] = ("duplicate_group_id",)
DUPLICATE_GROUP_DATA_COLUMNS: tuple[str, ...] = (
    "duplicate_type",
    "representative_chunk_id",
    "similarity_min",
    "similarity_max",
    "notes",
)

# Deleting a document removes its chunks; deleting a chunk removes its
# duplicate memberships and any group it represents, because a group without
# its elected representative is no longer meaningful. ``parent_argument_id`` is
# cleared rather than cascaded so a submodule outlives an individually deleted
# parent, and it is deferred so a batch may insert children before parents.
SCHEMA_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS schema_meta (
        key   TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS documents (
        document_id     TEXT PRIMARY KEY,
        filename        TEXT NOT NULL,
        full_path       TEXT NOT NULL,
        source_group    TEXT NOT NULL,
        document_type   TEXT NOT NULL,
        side            TEXT NOT NULL,
        round_type      TEXT NOT NULL,
        year            INTEGER,
        title           TEXT,
        raw_text        TEXT NOT NULL DEFAULT '',
        priority_weight REAL NOT NULL DEFAULT 1.0,
        created_at      TEXT NOT NULL,
        updated_at      TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS chunks (
        chunk_id                TEXT PRIMARY KEY,
        document_id             TEXT NOT NULL
                                REFERENCES documents(document_id) ON DELETE CASCADE,
        source_file             TEXT NOT NULL,
        source_path             TEXT NOT NULL,
        source_group            TEXT NOT NULL,
        document_type           TEXT NOT NULL,
        section_type            TEXT NOT NULL,
        chunk_level             TEXT NOT NULL,
        original_heading        TEXT,
        argument_heading        TEXT,
        parent_heading          TEXT,
        heading_path            TEXT NOT NULL DEFAULT '[]',
        parent_argument_id      TEXT
                                REFERENCES chunks(chunk_id) ON DELETE SET NULL
                                DEFERRABLE INITIALLY DEFERRED,
        side                    TEXT NOT NULL,
        round_type              TEXT NOT NULL,
        year                    INTEGER,
        text                    TEXT NOT NULL,
        token_count             INTEGER NOT NULL DEFAULT 0,
        freshness               TEXT NOT NULL,
        duplicate_group         TEXT,
        priority_weight         REAL NOT NULL DEFAULT 1.0,
        source_block_indexes    TEXT NOT NULL DEFAULT '[]',
        structure_confidence    REAL NOT NULL DEFAULT 0.0,
        is_special_masterfile   INTEGER NOT NULL DEFAULT 0,
        special_masterfile_name TEXT,
        created_at              TEXT NOT NULL,
        updated_at              TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS duplicate_groups (
        duplicate_group_id      TEXT PRIMARY KEY,
        duplicate_type          TEXT NOT NULL,
        representative_chunk_id TEXT NOT NULL
                                REFERENCES chunks(chunk_id) ON DELETE CASCADE,
        similarity_min          REAL NOT NULL,
        similarity_max          REAL NOT NULL,
        notes                   TEXT NOT NULL DEFAULT '[]',
        created_at              TEXT NOT NULL,
        updated_at              TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS duplicate_group_members (
        duplicate_group_id TEXT NOT NULL
                           REFERENCES duplicate_groups(duplicate_group_id) ON DELETE CASCADE,
        chunk_id           TEXT NOT NULL
                           REFERENCES chunks(chunk_id) ON DELETE CASCADE,
        member_index       INTEGER NOT NULL,
        PRIMARY KEY (duplicate_group_id, chunk_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_documents_source_group ON documents(source_group)",
    "CREATE INDEX IF NOT EXISTS idx_documents_document_type ON documents(document_type)",
    "CREATE INDEX IF NOT EXISTS idx_documents_year ON documents(year)",
    "CREATE INDEX IF NOT EXISTS idx_chunks_document_id ON chunks(document_id)",
    "CREATE INDEX IF NOT EXISTS idx_chunks_source_group ON chunks(source_group)",
    "CREATE INDEX IF NOT EXISTS idx_chunks_document_type ON chunks(document_type)",
    "CREATE INDEX IF NOT EXISTS idx_chunks_section_type ON chunks(section_type)",
    "CREATE INDEX IF NOT EXISTS idx_chunks_chunk_level ON chunks(chunk_level)",
    "CREATE INDEX IF NOT EXISTS idx_chunks_freshness ON chunks(freshness)",
    "CREATE INDEX IF NOT EXISTS idx_chunks_duplicate_group ON chunks(duplicate_group)",
    "CREATE INDEX IF NOT EXISTS idx_chunks_parent_argument_id ON chunks(parent_argument_id)",
    """
    CREATE INDEX IF NOT EXISTS idx_chunks_special_masterfile
        ON chunks(is_special_masterfile)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_duplicate_group_members_chunk_id
        ON duplicate_group_members(chunk_id)
    """,
    """
    CREATE TRIGGER IF NOT EXISTS duplicate_groups_after_delete
    AFTER DELETE ON duplicate_groups BEGIN
        UPDATE chunks
        SET duplicate_group = NULL
        WHERE duplicate_group = old.duplicate_group_id;
    END
    """,
)

# An external-content FTS5 table keeps chunk text stored exactly once. This is
# a lexical debugging and fallback aid, not the future semantic retrieval path.
FULL_TEXT_STATEMENTS: tuple[str, ...] = (
    f"""
    CREATE VIRTUAL TABLE IF NOT EXISTS {FULL_TEXT_TABLE} USING fts5(
        text,
        content='chunks',
        content_rowid='rowid',
        tokenize='unicode61 remove_diacritics 2'
    )
    """,
    f"""
    CREATE TRIGGER IF NOT EXISTS chunks_after_insert AFTER INSERT ON chunks BEGIN
        INSERT INTO {FULL_TEXT_TABLE}(rowid, text) VALUES (new.rowid, new.text);
    END
    """,
    f"""
    CREATE TRIGGER IF NOT EXISTS chunks_after_delete AFTER DELETE ON chunks BEGIN
        INSERT INTO {FULL_TEXT_TABLE}({FULL_TEXT_TABLE}, rowid, text)
            VALUES ('delete', old.rowid, old.text);
    END
    """,
    f"""
    CREATE TRIGGER IF NOT EXISTS chunks_after_update AFTER UPDATE ON chunks BEGIN
        INSERT INTO {FULL_TEXT_TABLE}({FULL_TEXT_TABLE}, rowid, text)
            VALUES ('delete', old.rowid, old.text);
        INSERT INTO {FULL_TEXT_TABLE}(rowid, text) VALUES (new.rowid, new.text);
    END
    """,
)

_DROP_STATEMENTS: tuple[str, ...] = (
    "DROP TRIGGER IF EXISTS chunks_after_insert",
    "DROP TRIGGER IF EXISTS chunks_after_delete",
    "DROP TRIGGER IF EXISTS chunks_after_update",
    "DROP TRIGGER IF EXISTS duplicate_groups_after_delete",
    f"DROP TABLE IF EXISTS {FULL_TEXT_TABLE}",
    "DROP TABLE IF EXISTS duplicate_group_members",
    "DROP TABLE IF EXISTS duplicate_groups",
    "DROP TABLE IF EXISTS chunks",
    "DROP TABLE IF EXISTS documents",
    "DROP TABLE IF EXISTS schema_meta",
)

# Child rows first so the statements are valid with or without cascades.
_CLEAR_STATEMENTS: tuple[str, ...] = (
    "DELETE FROM duplicate_group_members",
    "DELETE FROM duplicate_groups",
    "DELETE FROM chunks",
    "DELETE FROM documents",
)


def enum_value(value: object) -> object:
    """Return the underlying string of a ``StrEnum`` member, else the value.

    Enums are stored as their string values so the database stays readable and
    queryable from plain ``sqlite3`` sessions.
    """
    return value.value if isinstance(value, StrEnum) else value


def utc_timestamp() -> str:
    """Return the current UTC time as a sortable ISO-8601 string."""
    return datetime.now(UTC).isoformat(timespec="microseconds")


def dump_json(value: object) -> str:
    """Serialize a structured list field deterministically."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=False)


def load_json_list(raw: str | None) -> list:
    """Deserialize a JSON list column, tolerating legacy NULL values."""
    if not raw:
        return []
    value = json.loads(raw)
    if not isinstance(value, list):
        raise ValueError(f"expected a JSON list, found {type(value).__name__}")
    return value


def resolve_database_path(
    path: Path | str | None = None,
    *,
    settings: Settings | None = None,
) -> Path:
    """Resolve an explicit path or fall back to the configured location."""
    if path is not None:
        return Path(path).expanduser()
    return (settings or get_settings()).storage.database_path


def connect(
    path: Path | str | None = None,
    *,
    settings: Settings | None = None,
    create_parents: bool = True,
) -> sqlite3.Connection:
    """Open a connection with foreign keys on and manual transaction control.

    ``isolation_level=None`` disables the implicit transaction handling in
    ``sqlite3`` so that DDL, batch writes, and rollbacks are explicit and
    predictable. Use :func:`transaction` to group statements atomically.
    """
    configured = settings or get_settings()
    resolved = resolve_database_path(path, settings=configured)
    if create_parents and str(resolved) != ":memory:":
        resolved.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(resolved, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute(
        f"PRAGMA busy_timeout = {int(configured.storage.busy_timeout_seconds * 1000)}"
    )
    if str(resolved) != ":memory:":
        connection.execute("PRAGMA journal_mode = WAL")
    return connection


@contextmanager
def database_connection(
    path: Path | str | None = None,
    *,
    settings: Settings | None = None,
) -> Iterator[sqlite3.Connection]:
    """Open a configured connection and always close it."""
    connection = connect(path, settings=settings)
    try:
        yield connection
    finally:
        connection.close()


@contextmanager
def transaction(connection: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Run a batch atomically, rolling back completely on any failure.

    Nesting is a no-op: an already-open transaction is left to its owner so
    unrelated work is never pulled into one long-lived transaction.
    """
    if connection.in_transaction:
        yield connection
        return

    connection.execute("BEGIN IMMEDIATE")
    try:
        yield connection
    except BaseException:
        connection.rollback()
        raise
    else:
        connection.commit()


def foreign_keys_enabled(connection: sqlite3.Connection) -> bool:
    """Report whether this connection enforces foreign keys."""
    return bool(connection.execute("PRAGMA foreign_keys").fetchone()[0])


def supports_full_text_search(connection: sqlite3.Connection) -> bool:
    """Report whether this SQLite build provides the FTS5 extension."""
    try:
        connection.execute("CREATE VIRTUAL TABLE temp.fts5_probe USING fts5(probe)")
    except sqlite3.OperationalError:
        return False
    connection.execute("DROP TABLE temp.fts5_probe")
    return True


def full_text_search_available(connection: sqlite3.Connection) -> bool:
    """Report whether this database actually has the chunk FTS index."""
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (FULL_TEXT_TABLE,),
    ).fetchone()
    return row is not None


def table_names(connection: sqlite3.Connection) -> set[str]:
    """Return every table name in the database."""
    return {
        row["name"]
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }


def index_names(connection: sqlite3.Connection) -> set[str]:
    """Return every explicitly created index name in the database."""
    return {
        row["name"]
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'index'")
        if row["name"] is not None
    }


def schema_version(connection: sqlite3.Connection) -> int:
    """Return the persisted schema version, or ``0`` if uninitialized."""
    if "schema_meta" not in table_names(connection):
        return 0
    row = connection.execute(
        "SELECT value FROM schema_meta WHERE key = 'schema_version'"
    ).fetchone()
    return int(row["value"]) if row is not None else 0


def create_schema(connection: sqlite3.Connection, *, settings: Settings | None = None) -> None:
    """Create tables, indexes, and the optional FTS index if absent."""
    configured = settings or get_settings()
    with transaction(connection):
        for statement in SCHEMA_STATEMENTS:
            connection.execute(statement)
        connection.execute(
            "INSERT INTO schema_meta (key, value) VALUES ('schema_version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (str(SCHEMA_VERSION),),
        )

    if not configured.storage.enable_full_text_search:
        return
    if not supports_full_text_search(connection):
        LOGGER.warning("FTS5 is unavailable in this SQLite build; lexical search is disabled.")
        return
    with transaction(connection):
        for statement in FULL_TEXT_STATEMENTS:
            connection.execute(statement)


def drop_schema(connection: sqlite3.Connection) -> None:
    """Drop every knowledge-base object, leaving an empty database file."""
    with transaction(connection):
        for statement in _DROP_STATEMENTS:
            connection.execute(statement)


def initialize_database(
    path: Path | str | None = None,
    *,
    settings: Settings | None = None,
) -> Path:
    """Create the database and schema if needed and return its path."""
    resolved = resolve_database_path(path, settings=settings)
    with database_connection(resolved, settings=settings) as connection:
        create_schema(connection, settings=settings)
    LOGGER.info("Initialized database at %s", resolved)
    return resolved


def recreate_database(
    path: Path | str | None = None,
    *,
    settings: Settings | None = None,
) -> Path:
    """Drop and rebuild the schema, discarding every persisted row."""
    resolved = resolve_database_path(path, settings=settings)
    with database_connection(resolved, settings=settings) as connection:
        drop_schema(connection)
        create_schema(connection, settings=settings)
    LOGGER.info("Recreated database at %s", resolved)
    return resolved


def clear_database(connection: sqlite3.Connection) -> None:
    """Delete every persisted row atomically, keeping the schema in place."""
    with transaction(connection):
        for statement in _CLEAR_STATEMENTS:
            connection.execute(statement)


def rebuild_full_text_index(connection: sqlite3.Connection) -> bool:
    """Recompute the FTS index from ``chunks``; used for repair, not writes."""
    if not full_text_search_available(connection):
        return False
    with transaction(connection):
        connection.execute(f"INSERT INTO {FULL_TEXT_TABLE}({FULL_TEXT_TABLE}) VALUES ('rebuild')")
    return True


@contextmanager
def temporary_id_table(
    connection: sqlite3.Connection,
    identifiers: Iterable[str],
    *,
    name: str = "incoming_ids",
) -> Iterator[str]:
    """Stage a set of IDs in a temp table for unbounded set comparisons.

    Reconciling "delete everything except these IDs" through a temp table keeps
    the statement independent of SQLite's bound-parameter limit.
    """
    qualified = f"temp.{name}"
    connection.execute(f"DROP TABLE IF EXISTS {qualified}")
    connection.execute(f"CREATE TEMP TABLE {name} (id TEXT PRIMARY KEY)")
    try:
        connection.executemany(
            f"INSERT OR IGNORE INTO {qualified} (id) VALUES (?)",
            [(identifier,) for identifier in identifiers],
        )
        yield qualified
    finally:
        connection.execute(f"DROP TABLE IF EXISTS {qualified}")


def build_upsert_statement(
    table: str,
    key_columns: Sequence[str],
    data_columns: Sequence[str],
) -> str:
    """Build a parameterized upsert that only rewrites genuinely changed rows.

    Restricting ``DO UPDATE`` with a difference check keeps re-ingestion of
    unchanged content a true no-op, including ``updated_at``.
    """
    columns = (*key_columns, *data_columns, "created_at", "updated_at")
    placeholders = ", ".join("?" for _ in columns)
    assignments = ", ".join(
        f"{column} = excluded.{column}" for column in (*data_columns, "updated_at")
    )
    changed = " OR ".join(f"{table}.{column} IS NOT excluded.{column}" for column in data_columns)
    return (
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders}) "
        f"ON CONFLICT({', '.join(key_columns)}) DO UPDATE SET {assignments} "
        f"WHERE {changed}"
    )


def upsert_parameters(
    values: Mapping[str, object],
    key_columns: Sequence[str],
    data_columns: Sequence[str],
    timestamp: str,
) -> tuple[object, ...]:
    """Order a value mapping to match :func:`build_upsert_statement`."""
    ordered = tuple(values[column] for column in (*key_columns, *data_columns))
    return (*ordered, timestamp, timestamp)


def filter_clause(
    filters: Mapping[str, object],
    allowed_columns: Sequence[str],
    *,
    table: str | None = None,
) -> tuple[str, list[object]]:
    """Build a parameterized ``WHERE`` clause from a whitelisted filter map.

    Column names are validated against ``allowed_columns`` so no caller value
    can ever reach the SQL text; the values themselves are always bound.
    """
    conditions: list[str] = []
    parameters: list[object] = []
    prefix = f"{table}." if table else ""
    for column, value in filters.items():
        if value is None:
            continue
        if column not in allowed_columns:
            raise ValueError(f"{column} is not a filterable column")
        conditions.append(f"{prefix}{column} = ?")
        parameters.append(value)
    clause = f" WHERE {' AND '.join(conditions)}" if conditions else ""
    return clause, parameters


def limit_clause(limit: int | None, offset: int = 0) -> tuple[str, list[object]]:
    """Build a parameterized ``LIMIT``/``OFFSET`` clause."""
    if limit is None and not offset:
        return "", []
    # SQLite requires a LIMIT before OFFSET; -1 means "no limit".
    return " LIMIT ? OFFSET ?", [-1 if limit is None else limit, offset]


def count_by_column(
    connection: sqlite3.Connection,
    table: str,
    column: str,
    allowed_columns: Sequence[str],
) -> dict[str, int]:
    """Group-count one whitelisted column, reporting NULL as ``(none)``."""
    if column not in allowed_columns:
        raise ValueError(f"{column} is not a groupable column of {table}")
    rows = connection.execute(
        f"SELECT {column} AS value, COUNT(*) AS total FROM {table} "
        f"GROUP BY {column} ORDER BY total DESC, value"
    ).fetchall()
    return {("(none)" if row["value"] is None else str(row["value"])): row["total"] for row in rows}
