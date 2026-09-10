"""Archive-to-SQLite ingestion pipeline.

Discovery, parsing, structure detection, chunking, and duplicate detection all
stay in memory. This module is the only place where those stages meet the
persistence layer, so the knowledge base can always be rebuilt from source
files with one command.

No embedding model is loaded and no vector store is touched here.
"""

from __future__ import annotations

import sqlite3
import time
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from debate_engine.config import Settings, get_settings
from debate_engine.ingestion import (
    DiscoveredFile,
    build_debate_document,
    chunk_structured_document,
    detect_duplicates,
    detect_structure,
    discover_files,
    parse_document,
)
from debate_engine.ingestion.parser import DocumentParser, build_parser_registry
from debate_engine.logging import get_logger
from debate_engine.schemas import DebateChunk, ParsedDocument, ParseStatus
from debate_engine.storage import (
    count_duplicate_group_members,
    database_connection,
    initialize_database,
    list_chunks,
    recreate_database,
    replace_chunks_for_document,
    replace_duplicate_groups,
    resolve_database_path,
    transaction,
    update_duplicate_groups,
    upsert_document,
)

LOGGER = get_logger("pipeline")

_BLOCKING_PARSE_STATUSES = frozenset(
    {ParseStatus.FAILED, ParseStatus.UNSUPPORTED, ParseStatus.NEEDS_OCR}
)


class FailureKind(StrEnum):
    """Why one source file did not reach the database."""

    PARSE = "parse"
    NEEDS_OCR = "needs_ocr"
    LEGACY_DOC = "legacy_doc"
    UNSUPPORTED = "unsupported"
    STRUCTURE = "structure"
    CHUNKING = "chunking"
    PERSISTENCE = "persistence"
    DEDUPLICATION = "deduplication"


@dataclass(frozen=True, slots=True)
class BuildFailure:
    """One clearly reported, non-fatal ingestion failure."""

    path: Path
    kind: FailureKind
    detail: str


@dataclass(slots=True)
class BuildReport:
    """Counters and failures from one database build."""

    archive_root: Path
    database_path: Path
    rebuilt: bool = False
    files_discovered: int = 0
    files_attempted: int = 0
    unsupported_files_skipped: int = 0
    documents_persisted: int = 0
    chunks_persisted: int = 0
    documents_without_chunks: int = 0
    duplicate_groups_persisted: int = 0
    duplicate_members_persisted: int = 0
    partial_parses: int = 0
    elapsed_seconds: float = 0.0
    failures: list[BuildFailure] = field(default_factory=list)

    @property
    def failure_counts(self) -> dict[str, int]:
        """Return failure totals keyed by kind, including the zeroed kinds."""
        counts = Counter(failure.kind.value for failure in self.failures)
        return {kind.value: counts.get(kind.value, 0) for kind in FailureKind}

    @property
    def succeeded(self) -> bool:
        """Report whether every attempted file reached the database."""
        return not self.failures


def _record(report: BuildReport, path: Path, kind: FailureKind, detail: str) -> None:
    LOGGER.warning("Skipped %s (%s): %s", path.name, kind.value, detail)
    report.failures.append(BuildFailure(path=path, kind=kind, detail=detail))


def _parse_failure_kind(parsed: ParsedDocument, extension: str) -> FailureKind:
    if parsed.parse_status is ParseStatus.NEEDS_OCR:
        return FailureKind.NEEDS_OCR
    if extension == ".doc":
        return FailureKind.LEGACY_DOC
    if parsed.parse_status is ParseStatus.UNSUPPORTED:
        return FailureKind.UNSUPPORTED
    return FailureKind.PARSE


def _ingest_file(
    connection: sqlite3.Connection,
    discovered: DiscoveredFile,
    report: BuildReport,
    *,
    parsers: Mapping[str, DocumentParser],
    settings: Settings,
) -> None:
    """Persist one file's document and chunks, containing its own failures."""
    parsed = parse_document(discovered.path, parsers=parsers)
    if parsed.parse_status in _BLOCKING_PARSE_STATUSES:
        detail = parsed.error_message or "; ".join(parsed.warnings) or "no details"
        _record(report, discovered.path, _parse_failure_kind(parsed, discovered.extension), detail)
        return
    if parsed.parse_status is ParseStatus.PARTIAL:
        report.partial_parses += 1

    try:
        structured = detect_structure(parsed, settings=settings.structure_detection)
    except Exception as exc:
        _record(report, discovered.path, FailureKind.STRUCTURE, f"{type(exc).__name__}: {exc}")
        return

    try:
        document = build_debate_document(
            parsed,
            structured,
            source_group=discovered.source_group,
            settings=settings,
        )
        chunks: list[DebateChunk] = chunk_structured_document(
            structured,
            document,
            settings=settings,
        )
    except Exception as exc:
        _record(report, discovered.path, FailureKind.CHUNKING, f"{type(exc).__name__}: {exc}")
        return

    try:
        with transaction(connection):
            upsert_document(connection, document)
            replace_chunks_for_document(connection, document.document_id, chunks)
    except sqlite3.Error as exc:
        _record(report, discovered.path, FailureKind.PERSISTENCE, f"{type(exc).__name__}: {exc}")
        return

    report.documents_persisted += 1
    report.chunks_persisted += len(chunks)
    if not chunks:
        report.documents_without_chunks += 1
        LOGGER.info("%s produced no chunks; its document row was still stored.", discovered.path)


def _persist_duplicate_groups(
    connection: sqlite3.Connection,
    report: BuildReport,
    *,
    settings: Settings,
) -> None:
    """Recompute duplicate groups over every stored chunk and persist them."""
    try:
        result = detect_duplicates(list_chunks(connection), settings=settings)
        with transaction(connection):
            replace_duplicate_groups(connection, result.duplicate_groups)
            update_duplicate_groups(connection, result.updated_chunks)
        report.duplicate_groups_persisted = len(result.duplicate_groups)
        report.duplicate_members_persisted = count_duplicate_group_members(connection)
    except (sqlite3.Error, ValueError) as exc:
        _record(
            report,
            report.archive_root,
            FailureKind.DEDUPLICATION,
            f"{type(exc).__name__}: {exc}",
        )


def build_database(
    archive: Path,
    *,
    database: Path | None = None,
    rebuild: bool = False,
    limit: int | None = None,
    settings: Settings | None = None,
) -> BuildReport:
    """Build or update the SQLite knowledge base from a local archive folder.

    Each file is persisted in its own transaction so one malformed document
    cannot abort the whole archive. Duplicate detection runs once at the end
    over every stored chunk, which keeps groups consistent across builds.
    """
    configured = settings or get_settings()
    started = time.perf_counter()
    database_path = resolve_database_path(database, settings=configured)

    if rebuild:
        recreate_database(database_path, settings=configured)
    else:
        initialize_database(database_path, settings=configured)

    discovery = discover_files(archive, patterns=configured.source_group_patterns)
    selected = discovery.files[:limit] if limit is not None else discovery.files
    report = BuildReport(
        archive_root=discovery.root,
        database_path=database_path,
        rebuilt=rebuild,
        files_discovered=len(discovery.files),
        files_attempted=len(selected),
        unsupported_files_skipped=len(discovery.unsupported),
    )

    parsers = build_parser_registry()
    with database_connection(database_path, settings=configured) as connection:
        for discovered in selected:
            _ingest_file(connection, discovered, report, parsers=parsers, settings=configured)
        _persist_duplicate_groups(connection, report, settings=configured)

    report.elapsed_seconds = time.perf_counter() - started
    LOGGER.info(
        "Build finished: %d documents, %d chunks, %d duplicate groups, %d failures",
        report.documents_persisted,
        report.chunks_persisted,
        report.duplicate_groups_persisted,
        len(report.failures),
    )
    return report
