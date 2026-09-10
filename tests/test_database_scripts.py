"""Database build and inspection CLI smoke tests."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from debate_engine.storage import connect, list_chunks, list_documents
from scripts.build_database import app as build_app
from scripts.inspect_db import app as inspect_app

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "duplicates"
RUNNER = CliRunner()


def _build_fixture_database(tmp_path: Path) -> Path:
    database = tmp_path / "inspect.db"
    result = RUNNER.invoke(
        build_app,
        [str(FIXTURE_ROOT), "--database", str(database), "--rebuild"],
    )
    assert result.exit_code == 0, result.stdout
    return database


def test_build_database_cli_reports_required_summary(tmp_path: Path) -> None:
    database = tmp_path / "built.db"

    result = RUNNER.invoke(
        build_app,
        [str(FIXTURE_ROOT), "--database", str(database), "--rebuild"],
    )

    assert result.exit_code == 0
    assert "Mode: rebuild" in result.stdout
    assert "Files discovered: 4" in result.stdout
    assert "Documents persisted: 4" in result.stdout
    assert "Chunks persisted: 4" in result.stdout
    assert "Duplicate groups: 1" in result.stdout
    assert "Parse failures: 0" in result.stdout
    assert "Needs OCR: 0" in result.stdout
    assert "Legacy .doc failures: 0" in result.stdout
    assert f"Database: {database}" in result.stdout
    assert "Elapsed:" in result.stdout


def test_inspect_stats_and_document_commands(tmp_path: Path) -> None:
    database = _build_fixture_database(tmp_path)

    stats = RUNNER.invoke(inspect_app, ["stats", "--database", str(database)])
    documents = RUNNER.invoke(inspect_app, ["documents", "--database", str(database)])

    assert stats.exit_code == 0
    assert "Documents: 4" in stats.stdout
    assert "Chunks: 4" in stats.stdout
    assert "Duplicate groups: 1" in stats.stdout
    assert "Documents by source_group:" in stats.stdout
    assert "Chunks by section_type:" in stats.stdout
    assert documents.exit_code == 0
    assert "Documents listed: 4" in documents.stdout


def test_inspect_one_document_and_chunk(tmp_path: Path) -> None:
    database = _build_fixture_database(tmp_path)
    connection = connect(database)
    try:
        document = list_documents(connection)[0]
        chunk = list_chunks(connection)[0]
    finally:
        connection.close()

    document_result = RUNNER.invoke(
        inspect_app,
        ["document", document.document_id, "--database", str(database)],
    )
    filename_result = RUNNER.invoke(
        inspect_app,
        ["document", document.filename, "--database", str(database)],
    )
    chunk_result = RUNNER.invoke(
        inspect_app,
        ["chunk", chunk.chunk_id, "--database", str(database)],
    )

    assert document_result.exit_code == 0
    assert f"Document: {document.document_id}" in document_result.stdout
    assert "Raw text characters:" in document_result.stdout
    assert filename_result.exit_code == 0
    assert f"Filename: {document.filename}" in filename_result.stdout
    assert chunk_result.exit_code == 0
    assert f"Chunk: {chunk.chunk_id}" in chunk_result.stdout
    assert "Source blocks:" in chunk_result.stdout


def test_inspect_duplicate_group_and_lexical_search(tmp_path: Path) -> None:
    database = _build_fixture_database(tmp_path)
    connection = connect(database)
    try:
        group_id = connection.execute(
            "SELECT duplicate_group_id FROM duplicate_groups LIMIT 1"
        ).fetchone()[0]
    finally:
        connection.close()

    group = RUNNER.invoke(
        inspect_app,
        ["duplicate-group", group_id, "--database", str(database)],
    )
    search = RUNNER.invoke(
        inspect_app,
        ["search", "public transit", "--database", str(database)],
    )

    assert group.exit_code == 0
    assert f"Duplicate group: {group_id}" in group.stdout
    assert "Representative:" in group.stdout
    assert "Members: 3" in group.stdout
    assert search.exit_code == 0
    assert "Matches: 3" in search.stdout
    assert "[Public] [transit]" in search.stdout


def test_inspect_missing_database_is_clear(tmp_path: Path) -> None:
    path = tmp_path / "missing.db"

    result = RUNNER.invoke(inspect_app, ["stats", "--database", str(path)])

    assert result.exit_code == 1
    assert f"No database at {path}" in result.output
    assert not path.exists()
