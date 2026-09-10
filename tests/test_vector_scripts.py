"""Vector build, status, and raw-search CLI smoke tests."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from debate_engine.config import Settings
from debate_engine.retrieval import SemanticSearchHit, VectorIndexStatus, VectorSyncReport
from debate_engine.schemas import ChunkLevel, DebateChunk
from scripts.build_vector_index import app as build_app
from scripts.inspect_vector_index import app as inspect_app
from scripts.search_vectors import app as search_app

RUNNER = CliRunner()


def make_settings(tmp_path: Path) -> Settings:
    database = tmp_path / "debate.db"
    database.touch()
    return Settings(
        project_root=tmp_path,
        embedding_model_name="fake/bge",
        embedding_dimension=3,
        storage={"database_path": database},
        vector_index={"chroma_path": tmp_path / "chroma"},
    )


def test_build_vector_index_cli_prints_sync_statistics(tmp_path: Path, monkeypatch) -> None:
    settings = make_settings(tmp_path)
    report = VectorSyncReport(
        sqlite_chunks_found=5,
        eligible_chunks=4,
        duplicate_members_skipped=1,
        vectors_already_current=2,
        vectors_embedded=1,
        vectors_updated=1,
        stale_vectors_deleted=1,
        elapsed_seconds=0.25,
    )

    class FakeStore:
        def __init__(self, configured):
            assert configured is settings

        def sync(self, **kwargs):
            assert kwargs["rebuild"] is True
            return report

    monkeypatch.setattr("scripts.build_vector_index.get_settings", lambda: settings)
    monkeypatch.setattr("scripts.build_vector_index.VectorStore", FakeStore)

    result = RUNNER.invoke(build_app, ["--rebuild", "--batch-size", "2"])

    assert result.exit_code == 0
    assert "SQLite chunks found: 5" in result.output
    assert "Eligible chunks: 4" in result.output
    assert "Duplicate members skipped: 1" in result.output
    assert "Vectors already current: 2" in result.output
    assert "Vectors embedded: 1" in result.output
    assert "Vectors updated: 1" in result.output
    assert "Stale vectors deleted: 1" in result.output


def test_inspect_vector_index_cli_prints_health(tmp_path: Path, monkeypatch) -> None:
    settings = make_settings(tmp_path)
    status = VectorIndexStatus(
        collection_name="debate_chunks",
        vector_count=4,
        sqlite_chunks=5,
        eligible_chunks=4,
        duplicate_members_skipped=1,
        stale_vectors=0,
        model_name="fake/bge",
        embedding_dimension=3,
        normalized=True,
        embedding_schema_version="debate-chunk-v1",
        chroma_path=tmp_path / "chroma",
    )

    class FakeStore:
        def __init__(self, configured):
            assert configured is settings

        def status(self, **kwargs):
            return status

    monkeypatch.setattr("scripts.inspect_vector_index.get_settings", lambda: settings)
    monkeypatch.setattr("scripts.inspect_vector_index.VectorStore", FakeStore)

    result = RUNNER.invoke(inspect_app)

    assert result.exit_code == 0
    assert "Vectors: 4" in result.output
    assert "SQLite chunks: 5" in result.output
    assert "Stale vectors: 0" in result.output
    assert "Embedding schema: debate-chunk-v1" in result.output


def test_search_vectors_cli_prints_raw_hydrated_result(tmp_path: Path, monkeypatch) -> None:
    settings = make_settings(tmp_path)
    chunk = DebateChunk(
        chunk_id="chunk-1",
        document_id="doc-1",
        source_file="access.md",
        source_path="/fixtures/access.md",
        section_type="contention",
        chunk_level=ChunkLevel.ARGUMENT,
        heading_path=["Contention: Access"],
        text="Public transport connects workers to jobs.",
        token_count=7,
    )
    hit = SemanticSearchHit(
        chunk_id=chunk.chunk_id,
        distance=0.08,
        similarity=0.92,
        metadata={"source_group": "other"},
        chunk=chunk,
    )

    class FakeStore:
        def __init__(self, configured):
            assert configured is settings

        def semantic_search(self, query, **kwargs):
            assert query == "transport employment"
            assert kwargs["filters"]["source_group"] == "other"
            return [hit]

    monkeypatch.setattr("scripts.search_vectors.get_settings", lambda: settings)
    monkeypatch.setattr("scripts.search_vectors.VectorStore", FakeStore)

    result = RUNNER.invoke(
        search_app,
        [
            "transport employment",
            "--source-group",
            "other",
            "--show-text",
            "--show-metadata",
        ],
    )

    assert result.exit_code == 0
    assert "similarity=0.9200" in result.output
    assert "Source: access.md" in result.output
    assert "chunk_id=chunk-1" in result.output
    assert "Public transport connects workers to jobs." in result.output
