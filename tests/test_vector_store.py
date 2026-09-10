"""Chroma synchronization and raw semantic search using fake embeddings."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from debate_engine.config import Settings
from debate_engine.pipeline import build_database
from debate_engine.retrieval import (
    VectorIndexConfigurationError,
    VectorStore,
    build_embedding_text,
    build_where_filter,
    embedding_fingerprint,
    select_eligible_chunks,
    vector_metadata,
)
from debate_engine.schemas import (
    ChunkLevel,
    DebateChunk,
    DebateDocument,
    DocumentType,
    DuplicateGroup,
    DuplicateType,
    Side,
    SourceGroup,
)
from debate_engine.storage import (
    connect,
    count_chunks,
    delete_chunk,
    initialize_database,
    list_duplicate_groups,
    update_duplicate_groups,
    upsert_chunks,
    upsert_document,
    upsert_duplicate_group,
)


class FakeEmbeddingService:
    def __init__(self) -> None:
        self.text_batches: list[list[str]] = []
        self.queries: list[str] = []

    @staticmethod
    def _vector(text: str) -> list[float]:
        lowered = text.casefold()
        if "transport" in lowered or "transit" in lowered or "jobs" in lowered:
            return [1.0, 0.0, 0.0]
        if "climate" in lowered or "emissions" in lowered:
            return [0.0, 1.0, 0.0]
        return [0.0, 0.0, 1.0]

    def embed_texts(self, texts):
        materialized = list(texts)
        self.text_batches.append(materialized)
        if any("FAIL EMBEDDING" in text for text in materialized):
            raise RuntimeError("synthetic embedding failure")
        return [self._vector(text) for text in materialized]

    def embed_query(self, text):
        self.queries.append(text)
        return self._vector(text)


def vector_settings(tmp_path: Path, **overrides: object) -> Settings:
    vector_index: dict[str, object] = {
        "chroma_path": tmp_path / "chroma",
        "collection_name": "debate_chunks_test",
        "embedding_batch_size": 2,
    }
    vector_index.update(overrides)
    return Settings(
        project_root=tmp_path,
        embedding_model_name="fake/bge",
        embedding_dimension=3,
        storage={"database_path": tmp_path / "debate.db"},
        vector_index=vector_index,
    )


def make_document(document_id: str = "doc-1", **overrides: object) -> DebateDocument:
    values: dict[str, object] = {
        "document_id": document_id,
        "filename": f"{document_id}.md",
        "full_path": f"/fixtures/{document_id}.md",
        "source_group": SourceGroup.PERSONAL,
        "document_type": DocumentType.CASE,
        "side": Side.GOV,
        "raw_text": "Synthetic debate text.",
    }
    values.update(overrides)
    return DebateDocument(**values)  # type: ignore[arg-type]


def make_chunk(
    chunk_id: str,
    document_id: str = "doc-1",
    text: str = "Public transport connects workers to jobs.",
    **overrides: object,
) -> DebateChunk:
    values: dict[str, object] = {
        "chunk_id": chunk_id,
        "document_id": document_id,
        "source_file": f"{document_id}.md",
        "source_path": f"/fixtures/{document_id}.md",
        "source_group": SourceGroup.PERSONAL,
        "document_type": DocumentType.CASE,
        "section_type": "contention",
        "chunk_level": ChunkLevel.ARGUMENT,
        "original_heading": "Access",
        "argument_heading": "Access",
        "heading_path": ["Contention 1", "Access"],
        "side": Side.GOV,
        "text": text,
        "token_count": len(text.split()),
        "structure_confidence": 0.9,
    }
    values.update(overrides)
    return DebateChunk(**values)  # type: ignore[arg-type]


@pytest.fixture
def vector_database(tmp_path: Path):
    settings = vector_settings(tmp_path)
    initialize_database(settings=settings)
    connection = connect(settings=settings)
    try:
        yield settings, connection
    finally:
        connection.close()


def persist(connection: sqlite3.Connection, chunks: list[DebateChunk]) -> None:
    documents = {
        chunk.document_id: make_document(
            chunk.document_id,
            filename=chunk.source_file,
            full_path=chunk.source_path,
            source_group=chunk.source_group,
            document_type=chunk.document_type,
            side=chunk.side,
        )
        for chunk in chunks
    }
    for document in documents.values():
        upsert_document(connection, document)
    upsert_chunks(connection, chunks)


def make_store(settings: Settings) -> tuple[VectorStore, FakeEmbeddingService]:
    embeddings = FakeEmbeddingService()
    return VectorStore(settings, embedding_service=embeddings), embeddings  # type: ignore[arg-type]


def test_collection_initializes_for_cosine_without_default_embedding(vector_database) -> None:
    settings, _ = vector_database
    store, embeddings = make_store(settings)

    collection = store.initialize_collection()

    assert collection.name == "debate_chunks_test"
    assert collection.count() == 0
    assert collection.configuration["hnsw"]["space"] == "cosine"
    assert collection.configuration["embedding_function"] is None
    assert embeddings.text_batches == []


def test_vector_metadata_is_lightweight_and_scalar() -> None:
    chunk = make_chunk(
        "chunk-1",
        year=None,
        duplicate_group=None,
        is_special_masterfile=True,
    )

    metadata = vector_metadata(chunk, fingerprint="abc")

    assert metadata["chunk_id"] == chunk.chunk_id
    assert metadata["special_masterfile"] is True
    assert metadata["embedding_fingerprint"] == "abc"
    assert "heading_path" not in metadata
    assert "text" not in metadata
    assert "year" not in metadata
    assert all(isinstance(value, str | int | float | bool) for value in metadata.values())


def test_vector_id_equals_chunk_id_and_batches_are_configurable(vector_database) -> None:
    settings, connection = vector_database
    chunks = [make_chunk(f"chunk-{index}") for index in range(5)]
    persist(connection, chunks)
    store, embeddings = make_store(settings)

    report = store.sync(database=settings.storage.database_path, batch_size=2)
    collection = store.initialize_collection()

    assert report.vectors_embedded == 5
    assert [len(batch) for batch in embeddings.text_batches] == [2, 2, 1]
    assert set(collection.get(include=[])["ids"]) == {chunk.chunk_id for chunk in chunks}


def test_representative_only_and_optional_duplicate_member_indexing(vector_database) -> None:
    settings, connection = vector_database
    first = make_chunk("representative", duplicate_group="dup-1")
    second = make_chunk("copy", document_id="doc-2", duplicate_group="dup-1")
    singleton = make_chunk("singleton", document_id="doc-3", text="Climate policy cuts emissions.")
    persist(connection, [first, second, singleton])
    group = DuplicateGroup(
        duplicate_group_id="dup-1",
        member_chunk_ids=["representative", "copy"],
        representative_chunk_id="representative",
        duplicate_type=DuplicateType.EXACT,
        similarity_min=1.0,
        similarity_max=1.0,
    )
    upsert_duplicate_group(connection, group)
    update_duplicate_groups(connection, [first, second, singleton])
    store, _ = make_store(settings)

    default_report = store.sync(database=settings.storage.database_path)

    assert default_report.eligible_chunks == 2
    assert default_report.duplicate_members_skipped == 1
    assert set(store.initialize_collection().get(include=[])["ids"]) == {
        "representative",
        "singleton",
    }

    all_report = store.sync(
        database=settings.storage.database_path,
        include_duplicate_members=True,
    )
    assert all_report.eligible_chunks == 3
    assert all_report.vectors_embedded == 1
    assert set(store.initialize_collection().get(include=[])["ids"]) == {
        "representative",
        "copy",
        "singleton",
    }


def test_incremental_sync_skips_unchanged_vectors(vector_database) -> None:
    settings, connection = vector_database
    persist(connection, [make_chunk("chunk-1"), make_chunk("chunk-2")])
    store, embeddings = make_store(settings)
    store.sync(database=settings.storage.database_path)
    embeddings.text_batches.clear()

    report = store.sync(database=settings.storage.database_path)

    assert report.vectors_already_current == 2
    assert report.vectors_embedded == 0
    assert report.vectors_updated == 0
    assert embeddings.text_batches == []


def test_changed_embedding_text_triggers_update(vector_database) -> None:
    settings, connection = vector_database
    original = make_chunk("chunk-1")
    persist(connection, [original])
    store, embeddings = make_store(settings)
    store.sync(database=settings.storage.database_path)
    before = store.initialize_collection().get(ids=["chunk-1"], include=["metadatas"])
    old_fingerprint = before["metadatas"][0]["embedding_fingerprint"]
    embeddings.text_batches.clear()

    changed = original.model_copy(
        update={"text": "Climate policy reduces industrial emissions.", "token_count": 6}
    )
    upsert_chunks(connection, [changed])
    report = store.sync(database=settings.storage.database_path)
    after = store.initialize_collection().get(ids=["chunk-1"], include=["metadatas"])

    assert report.vectors_updated == 1
    assert report.vectors_embedded == 0
    assert after["metadatas"][0]["embedding_fingerprint"] != old_fingerprint
    assert len(embeddings.text_batches) == 1


def test_deleted_sqlite_chunk_removes_stale_vector(vector_database) -> None:
    settings, connection = vector_database
    persist(connection, [make_chunk("keep"), make_chunk("remove")])
    store, _ = make_store(settings)
    store.sync(database=settings.storage.database_path)

    delete_chunk(connection, "remove")
    assert count_chunks(connection) == 1
    report = store.sync(database=settings.storage.database_path)

    assert report.stale_vectors_deleted == 1
    assert store.initialize_collection().get(include=[])["ids"] == ["keep"]


def test_configuration_mismatch_requires_rebuild(vector_database) -> None:
    settings, connection = vector_database
    persist(connection, [make_chunk("chunk-1")])
    original, _ = make_store(settings)
    original.sync(database=settings.storage.database_path)
    changed_settings = vector_settings(
        settings.project_root,
        embedding_text_schema_version="debate-chunk-v2",
    )
    changed, _ = make_store(changed_settings)

    with pytest.raises(VectorIndexConfigurationError, match="--rebuild"):
        changed.initialize_collection()

    report = changed.sync(database=settings.storage.database_path, rebuild=True)
    assert report.vectors_embedded == 1
    assert changed.initialize_collection().count() == 1


def test_empty_and_invalid_chunks_are_skipped() -> None:
    empty_values = make_chunk("empty").model_dump()
    empty_values["text"] = "   "
    empty = DebateChunk.model_construct(**empty_values)
    valid = make_chunk("valid")

    eligible, duplicates, invalid = select_eligible_chunks(
        [empty, valid],
        representative_ids=set(),
    )

    assert [chunk.chunk_id for chunk in eligible] == ["valid"]
    assert duplicates == 0
    assert invalid == 1


def test_semantic_search_returns_expected_id_and_hydrates_sqlite(vector_database) -> None:
    settings, connection = vector_database
    transport = make_chunk("transport", text="Public transit connects workers to jobs.")
    climate = make_chunk(
        "climate",
        document_id="doc-2",
        text="Carbon pricing reduces climate emissions.",
        source_group=SourceGroup.OTHER,
        section_type="impact",
    )
    persist(connection, [transport, climate])
    store, embeddings = make_store(settings)
    store.sync(database=settings.storage.database_path)

    hits = store.semantic_search(
        "employment and transport",
        database=settings.storage.database_path,
        top_k=2,
    )

    assert [hit.chunk_id for hit in hits][0] == "transport"
    assert hits[0].similarity == pytest.approx(1.0)
    assert hits[0].chunk == transport
    assert embeddings.queries == ["employment and transport"]


def test_metadata_filters_are_isolated_safe_and_applied(vector_database) -> None:
    settings, connection = vector_database
    personal = make_chunk("personal", source_group=SourceGroup.PERSONAL)
    other = make_chunk("other", document_id="doc-2", source_group=SourceGroup.OTHER)
    persist(connection, [personal, other])
    store, _ = make_store(settings)
    store.sync(database=settings.storage.database_path)

    hits = store.semantic_search(
        "transport jobs",
        database=settings.storage.database_path,
        filters={"source_group": SourceGroup.OTHER, "chunk_level": ChunkLevel.ARGUMENT},
    )

    assert [hit.chunk_id for hit in hits] == ["other"]
    assert build_where_filter({"source_group": "personal"}) == {"source_group": {"$eq": "personal"}}
    with pytest.raises(ValueError, match="not a supported"):
        build_where_filter({"priority_weight": "9"})  # type: ignore[dict-item]


def test_index_status_reports_counts_without_embedding(vector_database) -> None:
    settings, connection = vector_database
    persist(connection, [make_chunk("chunk-1"), make_chunk("chunk-2")])
    store, embeddings = make_store(settings)
    store.sync(database=settings.storage.database_path, limit=1)
    embeddings.text_batches.clear()

    status = store.status(database=settings.storage.database_path)

    assert status.vector_count == 1
    assert status.sqlite_chunks == 2
    assert status.eligible_chunks == 2
    assert status.stale_vectors == 0
    assert status.embedding_dimension == 3
    assert status.embedding_schema_version == "debate-chunk-v1"
    assert embeddings.text_batches == []


def test_embedding_batch_failure_is_contained_per_chunk(vector_database) -> None:
    settings, connection = vector_database
    chunks = [
        make_chunk("good-1"),
        make_chunk("bad", text="FAIL EMBEDDING"),
        make_chunk("good-2", text="Climate policy cuts emissions."),
    ]
    persist(connection, chunks)
    store, _ = make_store(settings)

    report = store.sync(database=settings.storage.database_path, batch_size=3)

    assert report.vectors_embedded == 2
    assert report.failed_chunks == 1
    assert report.failures[0].chunk_ids == ("bad",)
    assert set(store.initialize_collection().get(include=[])["ids"]) == {
        "good-1",
        "good-2",
    }


def test_fingerprint_in_metadata_matches_exact_embedding_input(vector_database) -> None:
    settings, connection = vector_database
    chunk = make_chunk("chunk-1")
    persist(connection, [chunk])
    store, _ = make_store(settings)

    store.sync(database=settings.storage.database_path)
    stored = store.initialize_collection().get(ids=["chunk-1"], include=["metadatas"])

    assert stored["metadatas"][0]["embedding_fingerprint"] == embedding_fingerprint(
        build_embedding_text(chunk),
        schema_version=settings.vector_index.embedding_text_schema_version,
    )


def test_end_to_end_synthetic_database_to_chroma_to_query(tmp_path: Path) -> None:
    settings = vector_settings(tmp_path)
    archive = tmp_path / "archive"
    personal = archive / "Personal Debate Files"
    past = archive / "Past Cases"
    personal.mkdir(parents=True)
    past.mkdir(parents=True)
    transport = (
        "# Contention: Access\n\n"
        "Public transport connects isolated workers to regional jobs and opportunity."
    )
    (personal / "access.md").write_text(transport)
    (past / "access copy.md").write_text(transport)
    (archive / "climate.md").write_text(
        "# Contention: Climate\n\nCarbon pricing reduces industrial emissions."
    )
    build_report = build_database(
        archive,
        database=settings.storage.database_path,
        rebuild=True,
        settings=settings,
    )
    store, _ = make_store(settings)

    sync_report = store.sync(database=settings.storage.database_path, rebuild=True)
    hits = store.semantic_search(
        "transport access to jobs",
        database=settings.storage.database_path,
        top_k=2,
    )

    assert build_report.documents_persisted == 3
    assert build_report.duplicate_groups_persisted == 1
    assert sync_report.sqlite_chunks_found == 3
    assert sync_report.eligible_chunks == 2
    assert sync_report.duplicate_members_skipped == 1
    connection = connect(settings=settings)
    try:
        representative_ids = {
            group.representative_chunk_id for group in list_duplicate_groups(connection)
        }
    finally:
        connection.close()
    assert hits[0].chunk_id in representative_ids
    assert "transport" in hits[0].chunk.text.casefold()
