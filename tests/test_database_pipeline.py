"""End-to-end archive ingestion into a temporary SQLite database."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from debate_engine.pipeline import FailureKind, build_database
from debate_engine.storage import (
    connect,
    count_chunks,
    count_documents,
    count_duplicate_groups,
    get_document,
    list_chunks,
    list_documents,
    search_chunks,
)

FIXTURE_ROOT = Path(__file__).parent / "fixtures"


def test_synthetic_parse_structure_chunk_dedupe_database_pipeline(tmp_path: Path) -> None:
    archive = tmp_path / "archive"
    personal = archive / "Personal Debate Files"
    collected = archive / "Past Cases"
    personal.mkdir(parents=True)
    collected.mkdir(parents=True)
    text = (
        "# Advantage: Access\n\n"
        "Public transit expands access to employment for low-income residents "
        "by connecting isolated neighborhoods to regional job centers."
    )
    (personal / "access.md").write_text(text)
    (collected / "access copy.md").write_text(text)
    (archive / "unrelated.csv").write_text("not,supported")
    database = tmp_path / "indexes" / "synthetic.db"

    report = build_database(archive, database=database, rebuild=True)

    assert report.files_discovered == 2
    assert report.unsupported_files_skipped == 1
    assert report.documents_persisted == 2
    assert report.chunks_persisted >= 2
    assert report.duplicate_groups_persisted >= 1
    assert not report.failures

    connection = connect(database)
    try:
        assert count_documents(connection) == 2
        assert count_chunks(connection) == report.chunks_persisted
        assert count_duplicate_groups(connection) == report.duplicate_groups_persisted
        assert {item.source_group.value for item in list_documents(connection)} == {
            "personal",
            "past_case",
        }
        assert any(chunk.duplicate_group for chunk in list_chunks(connection))
        assert search_chunks(connection, '"public transit"')
    finally:
        connection.close()


def test_pipeline_is_idempotent_and_rebuild_clears_old_rows(tmp_path: Path) -> None:
    archive = tmp_path / "archive"
    archive.mkdir()
    source = archive / "case.md"
    source.write_text("# Contention: Access\n\nTransit connects workers to jobs.")
    database = tmp_path / "debate.db"

    first = build_database(archive, database=database)
    second = build_database(archive, database=database)

    connection = connect(database)
    try:
        assert (
            count_documents(connection) == first.documents_persisted == second.documents_persisted
        )
        assert count_chunks(connection) == first.chunks_persisted == second.chunks_persisted
        document_id = list_documents(connection)[0].document_id
        assert get_document(connection, document_id).raw_text == source.read_text()
    finally:
        connection.close()

    source.unlink()
    empty_rebuild = build_database(archive, database=database, rebuild=True)
    connection = connect(database)
    try:
        assert empty_rebuild.documents_persisted == 0
        assert count_documents(connection) == 0
        assert count_chunks(connection) == 0
    finally:
        connection.close()


def test_default_upsert_preserves_documents_not_in_current_archive(tmp_path: Path) -> None:
    first_archive = tmp_path / "first"
    second_archive = tmp_path / "second"
    first_archive.mkdir()
    second_archive.mkdir()
    (first_archive / "first.md").write_text("First archive argument with enough useful text.")
    (second_archive / "second.md").write_text("Second archive argument with different useful text.")
    database = tmp_path / "debate.db"

    build_database(first_archive, database=database)
    build_database(second_archive, database=database)

    connection = connect(database)
    try:
        assert {document.filename for document in list_documents(connection)} == {
            "first.md",
            "second.md",
        }
    finally:
        connection.close()


def test_bad_document_is_reported_without_aborting_archive(tmp_path: Path) -> None:
    database = tmp_path / "library.db"

    report = build_database(FIXTURE_ROOT / "library", database=database, rebuild=True)

    assert report.files_discovered == 9
    assert report.documents_persisted > 0
    assert report.chunks_persisted > 0
    assert any(failure.kind is FailureKind.PARSE for failure in report.failures)
    assert any(failure.kind is FailureKind.NEEDS_OCR for failure in report.failures)
    assert any(failure.path.name == "malformed.docx" for failure in report.failures)
    assert any(failure.path.name == "empty_scan.pdf" for failure in report.failures)

    connection = connect(database)
    try:
        assert count_documents(connection) == report.documents_persisted
        raw_texts = [
            row["raw_text"] for row in connection.execute("SELECT raw_text FROM documents")
        ]
        assert all("placeholder" not in text.casefold() for text in raw_texts)
    finally:
        connection.close()


def test_document_and_each_file_persistence_are_atomic(tmp_path: Path, monkeypatch) -> None:
    archive = tmp_path / "archive"
    archive.mkdir()
    (archive / "first.md").write_text("First valid argument about public transport access.")
    (archive / "second.md").write_text("Second valid argument about economic investment.")
    database = tmp_path / "debate.db"

    import debate_engine.pipeline as pipeline

    real_replace = pipeline.replace_chunks_for_document
    calls = 0

    def fail_second(connection, document_id, chunks):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise sqlite3.IntegrityError("synthetic write failure")
        return real_replace(connection, document_id, chunks)

    monkeypatch.setattr(pipeline, "replace_chunks_for_document", fail_second)
    report = build_database(archive, database=database, rebuild=True)

    assert report.documents_persisted == 1
    assert [failure.kind for failure in report.failures] == [FailureKind.PERSISTENCE]
    connection = connect(database)
    try:
        assert count_documents(connection) == 1
        assert count_chunks(connection) == report.chunks_persisted
    finally:
        connection.close()
