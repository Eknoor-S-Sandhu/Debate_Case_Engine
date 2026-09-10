"""SQLite schema and repository behavior."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from debate_engine.config import Settings
from debate_engine.schemas import (
    ChunkLevel,
    DebateChunk,
    DebateDocument,
    DocumentType,
    DuplicateGroup,
    DuplicateType,
    Freshness,
    RoundType,
    Side,
    SourceGroup,
)
from debate_engine.storage import (
    clear_database,
    connect,
    count_chunks,
    count_documents,
    count_duplicate_group_members,
    count_duplicate_groups,
    create_schema,
    delete_chunk,
    delete_document,
    delete_duplicate_group,
    foreign_keys_enabled,
    full_text_search_available,
    get_chunk,
    get_chunks_for_document,
    get_document,
    get_duplicate_group,
    get_duplicate_members,
    index_names,
    initialize_database,
    list_chunks,
    list_documents,
    recreate_database,
    replace_chunks_for_document,
    search_chunks,
    table_names,
    transaction,
    update_duplicate_groups,
    upsert_chunk,
    upsert_chunks,
    upsert_document,
    upsert_documents,
    upsert_duplicate_group,
    upsert_duplicate_groups,
)


@pytest.fixture
def database(tmp_path: Path) -> tuple[sqlite3.Connection, Path]:
    path = tmp_path / "nested" / "test.db"
    initialize_database(path)
    connection = connect(path)
    yield connection, path
    connection.close()


def make_document(document_id: str = "doc-1", **overrides: object) -> DebateDocument:
    fields: dict[str, object] = {
        "document_id": document_id,
        "filename": f"{document_id}.md",
        "full_path": f"/archive/{document_id}.md",
        "source_group": SourceGroup.PERSONAL,
        "document_type": DocumentType.CASE,
        "side": Side.GOV,
        "round_type": RoundType.POLICY,
        "year": 2025,
        "title": "Transit Case",
        "raw_text": "Public transit expands access to employment.",
        "priority_weight": 1.1,
    }
    fields.update(overrides)
    return DebateDocument(**fields)  # type: ignore[arg-type]


def make_chunk(
    chunk_id: str = "chunk-1",
    document_id: str = "doc-1",
    **overrides: object,
) -> DebateChunk:
    fields: dict[str, object] = {
        "chunk_id": chunk_id,
        "document_id": document_id,
        "source_file": f"{document_id}.md",
        "source_path": f"/archive/{document_id}.md",
        "source_group": SourceGroup.PERSONAL,
        "document_type": DocumentType.CASE,
        "section_type": "advantage",
        "chunk_level": ChunkLevel.ARGUMENT,
        "original_heading": "Access",
        "argument_heading": "Access",
        "heading_path": ["Government", "Access"],
        "side": Side.GOV,
        "round_type": RoundType.POLICY,
        "year": 2025,
        "text": "Public transit expands access to employment.",
        "token_count": 8,
        "freshness": Freshness.CURRENT,
        "priority_weight": 1.1,
        "source_block_indexes": [2, 4, 7],
        "structure_confidence": 0.94,
    }
    fields.update(overrides)
    return DebateChunk(**fields)  # type: ignore[arg-type]


def persist_document_and_chunks(
    connection: sqlite3.Connection,
    document: DebateDocument | None = None,
    chunks: list[DebateChunk] | None = None,
) -> tuple[DebateDocument, list[DebateChunk]]:
    stored_document = document or make_document()
    stored_chunks = chunks or [make_chunk(document_id=stored_document.document_id)]
    upsert_document(connection, stored_document)
    upsert_chunks(connection, stored_chunks)
    return stored_document, stored_chunks


def test_database_initialization_creates_parent_and_expected_tables(tmp_path: Path) -> None:
    path = tmp_path / "deep" / "indexes" / "debate.db"

    assert initialize_database(path) == path

    connection = connect(path)
    try:
        assert {
            "documents",
            "chunks",
            "duplicate_groups",
            "duplicate_group_members",
        } <= table_names(connection)
    finally:
        connection.close()


def test_foreign_keys_are_enabled_on_every_storage_connection(database) -> None:
    connection, _ = database
    assert foreign_keys_enabled(connection)


def test_document_insert_get_and_enum_roundtrip(database) -> None:
    connection, _ = database
    document = make_document()

    upsert_document(connection, document)

    assert get_document(connection, document.document_id) == document
    assert isinstance(get_document(connection, document.document_id).source_group, SourceGroup)


def test_document_upsert_updates_without_duplicate(database) -> None:
    connection, _ = database
    document = make_document()
    upsert_document(connection, document)

    updated = document.model_copy(update={"title": "Updated title", "raw_text": "Updated text"})
    upsert_document(connection, updated)

    assert count_documents(connection) == 1
    assert get_document(connection, document.document_id) == updated


def test_repeated_identical_document_write_is_a_true_noop(database) -> None:
    connection, _ = database
    document = make_document()
    upsert_document(connection, document)
    original = connection.execute(
        "SELECT created_at, updated_at FROM documents WHERE document_id = ?",
        (document.document_id,),
    ).fetchone()

    upsert_document(connection, document)
    repeated = connection.execute(
        "SELECT created_at, updated_at FROM documents WHERE document_id = ?",
        (document.document_id,),
    ).fetchone()

    assert tuple(repeated) == tuple(original)
    assert count_documents(connection) == 1


def test_document_filters_accept_enums_and_strings(database) -> None:
    connection, _ = database
    upsert_documents(
        connection,
        [
            make_document("personal"),
            make_document(
                "other",
                source_group=SourceGroup.OTHER,
                document_type=DocumentType.THEORY,
            ),
        ],
    )

    assert [item.document_id for item in list_documents(connection, source_group="personal")] == [
        "personal"
    ]
    assert [
        item.document_id for item in list_documents(connection, document_type=DocumentType.THEORY)
    ] == ["other"]


def test_chunk_insert_get_and_structured_lists_roundtrip(database) -> None:
    connection, _ = database
    _, chunks = persist_document_and_chunks(connection)

    stored = get_chunk(connection, chunks[0].chunk_id)

    assert stored == chunks[0]
    assert stored.heading_path == ["Government", "Access"]
    assert stored.source_block_indexes == [2, 4, 7]
    assert isinstance(stored.chunk_level, ChunkLevel)
    assert isinstance(stored.freshness, Freshness)


def test_chunk_upsert_updates_without_duplicate(database) -> None:
    connection, _ = database
    _, chunks = persist_document_and_chunks(connection)
    updated = chunks[0].model_copy(
        update={"text": "Updated transit text.", "token_count": 4, "section_type": "impact"}
    )

    upsert_chunk(connection, updated)

    assert count_chunks(connection) == 1
    assert get_chunk(connection, updated.chunk_id) == updated


def test_get_chunks_for_document_and_filters(database) -> None:
    connection, _ = database
    upsert_documents(connection, [make_document("doc-1"), make_document("doc-2")])
    upsert_chunks(
        connection,
        [
            make_chunk("argument", "doc-1"),
            make_chunk(
                "submodule",
                "doc-1",
                chunk_level=ChunkLevel.SUBMODULE,
                section_type="warrant",
                parent_argument_id="argument",
            ),
            make_chunk("other", "doc-2"),
        ],
    )

    assert {item.chunk_id for item in get_chunks_for_document(connection, "doc-1")} == {
        "argument",
        "submodule",
    }
    assert [item.chunk_id for item in list_chunks(connection, section_type="warrant")] == [
        "submodule"
    ]


def test_replace_chunks_removes_stale_rows(database) -> None:
    connection, _ = database
    upsert_document(connection, make_document())
    upsert_chunks(connection, [make_chunk("old"), make_chunk("keep")])

    replace_chunks_for_document(
        connection,
        "doc-1",
        [make_chunk("keep", text="Current text.", token_count=3)],
    )

    assert get_chunk(connection, "old") is None
    assert [item.chunk_id for item in get_chunks_for_document(connection, "doc-1")] == ["keep"]


def test_special_masterfile_and_optional_metadata_roundtrip(database) -> None:
    connection, _ = database
    upsert_document(
        connection,
        make_document(document_type=DocumentType.MASTERFILE, year=None, title=None),
    )
    chunk = make_chunk(
        document_type=DocumentType.MASTERFILE,
        original_heading=None,
        argument_heading=None,
        parent_heading=None,
        parent_argument_id=None,
        year=None,
        duplicate_group=None,
        is_special_masterfile=True,
        special_masterfile_name="Case File Sandhu",
    )

    upsert_chunk(connection, chunk)
    stored = get_chunk(connection, chunk.chunk_id)

    assert stored == chunk
    assert stored.is_special_masterfile
    assert stored.special_masterfile_name == "Case File Sandhu"


def test_unknown_enum_values_roundtrip(database) -> None:
    connection, _ = database
    document = make_document(
        source_group=SourceGroup.OTHER,
        document_type=DocumentType.UNKNOWN,
        side=Side.UNKNOWN,
        round_type=RoundType.UNKNOWN,
    )
    chunk = make_chunk(
        source_group=SourceGroup.OTHER,
        document_type=DocumentType.UNKNOWN,
        side=Side.UNKNOWN,
        round_type=RoundType.UNKNOWN,
        freshness=Freshness.UNKNOWN,
        section_type="author_specific_label",
    )

    persist_document_and_chunks(connection, document, [chunk])

    assert get_document(connection, "doc-1") == document
    assert get_chunk(connection, "chunk-1") == chunk


def test_chunk_foreign_key_rejects_missing_document(database) -> None:
    connection, _ = database
    with pytest.raises(sqlite3.IntegrityError):
        upsert_chunk(connection, make_chunk(document_id="missing"))
    assert count_chunks(connection) == 0


def test_batch_transaction_rolls_back_all_chunks(database) -> None:
    connection, _ = database
    upsert_document(connection, make_document())

    with pytest.raises(sqlite3.IntegrityError):
        upsert_chunks(
            connection,
            [
                make_chunk("valid"),
                make_chunk("invalid", document_id="missing"),
            ],
        )

    assert count_chunks(connection) == 0


def test_parent_argument_integrity_and_child_first_input(database) -> None:
    connection, _ = database
    upsert_document(connection, make_document())
    parent = make_chunk("parent")
    child = make_chunk(
        "child",
        chunk_level=ChunkLevel.SUBMODULE,
        section_type="warrant",
        parent_argument_id="parent",
    )

    upsert_chunks(connection, [child, parent])

    assert get_chunk(connection, "child").parent_argument_id == "parent"


def test_duplicate_group_and_members_roundtrip(database) -> None:
    connection, _ = database
    upsert_documents(connection, [make_document("doc-1"), make_document("doc-2")])
    first = make_chunk("chunk-1", "doc-1")
    second = make_chunk("chunk-2", "doc-2")
    upsert_chunks(connection, [first, second])
    group = DuplicateGroup(
        duplicate_group_id="dup-1",
        member_chunk_ids=["chunk-2", "chunk-1"],
        representative_chunk_id="chunk-1",
        duplicate_type=DuplicateType.NEAR,
        similarity_min=0.94,
        similarity_max=1.0,
        notes=["Originals preserved.", "Structured flag: near."],
    )

    upsert_duplicate_group(connection, group)

    assert get_duplicate_group(connection, "dup-1") == group
    assert get_duplicate_members(connection, "dup-1") == ["chunk-2", "chunk-1"]
    assert count_duplicate_group_members(connection) == 2


def test_duplicate_group_upsert_replaces_members(database) -> None:
    connection, _ = database
    upsert_documents(connection, [make_document("doc-1"), make_document("doc-2")])
    upsert_chunks(connection, [make_chunk("chunk-1", "doc-1"), make_chunk("chunk-2", "doc-2")])
    group = DuplicateGroup(
        duplicate_group_id="dup-1",
        member_chunk_ids=["chunk-1", "chunk-2"],
        representative_chunk_id="chunk-1",
        duplicate_type=DuplicateType.EXACT,
        similarity_min=1.0,
        similarity_max=1.0,
    )
    upsert_duplicate_group(connection, group)

    updated = group.model_copy(update={"member_chunk_ids": ["chunk-1"]})
    upsert_duplicate_group(connection, updated)

    assert count_duplicate_groups(connection) == 1
    assert get_duplicate_members(connection, "dup-1") == ["chunk-1"]


def test_representative_and_members_require_existing_chunks(database) -> None:
    connection, _ = database
    missing_representative = DuplicateGroup(
        duplicate_group_id="bad",
        member_chunk_ids=["missing"],
        representative_chunk_id="missing",
        duplicate_type=DuplicateType.EXACT,
        similarity_min=1.0,
        similarity_max=1.0,
    )
    with pytest.raises(sqlite3.IntegrityError):
        upsert_duplicate_group(connection, missing_representative)

    persist_document_and_chunks(connection)
    missing_member = missing_representative.model_copy(
        update={
            "duplicate_group_id": "bad-member",
            "representative_chunk_id": "chunk-1",
            "member_chunk_ids": ["chunk-1", "missing"],
        }
    )
    with pytest.raises(sqlite3.IntegrityError):
        upsert_duplicate_group(connection, missing_member)

    assert count_duplicate_groups(connection) == 0


def test_representative_must_be_a_member_of_its_group(database) -> None:
    connection, _ = database
    upsert_documents(connection, [make_document("doc-1"), make_document("doc-2")])
    upsert_chunks(connection, [make_chunk("chunk-1", "doc-1"), make_chunk("chunk-2", "doc-2")])
    group = DuplicateGroup(
        duplicate_group_id="bad-representative",
        member_chunk_ids=["chunk-1"],
        representative_chunk_id="chunk-2",
        duplicate_type=DuplicateType.NEAR,
        similarity_min=0.95,
        similarity_max=0.95,
    )

    with pytest.raises(ValueError, match="is not a member"):
        upsert_duplicate_group(connection, group)

    assert count_duplicate_groups(connection) == 0


def test_duplicate_batch_rollback_is_atomic(database) -> None:
    connection, _ = database
    persist_document_and_chunks(connection)
    valid = DuplicateGroup(
        duplicate_group_id="valid",
        member_chunk_ids=["chunk-1"],
        representative_chunk_id="chunk-1",
        duplicate_type=DuplicateType.EXACT,
        similarity_min=1.0,
        similarity_max=1.0,
    )
    invalid = valid.model_copy(
        update={
            "duplicate_group_id": "invalid",
            "representative_chunk_id": "missing",
            "member_chunk_ids": ["missing"],
        }
    )

    with pytest.raises(sqlite3.IntegrityError):
        upsert_duplicate_groups(connection, [valid, invalid])

    assert count_duplicate_groups(connection) == 0


def test_useful_indexes_exist(database) -> None:
    connection, _ = database
    expected = {
        "idx_documents_source_group",
        "idx_documents_document_type",
        "idx_documents_year",
        "idx_chunks_document_id",
        "idx_chunks_source_group",
        "idx_chunks_document_type",
        "idx_chunks_section_type",
        "idx_chunks_chunk_level",
        "idx_chunks_freshness",
        "idx_chunks_duplicate_group",
        "idx_chunks_special_masterfile",
    }
    assert expected <= index_names(connection)


def test_delete_document_cascades_chunks_groups_members_and_fts(database) -> None:
    connection, _ = database
    persist_document_and_chunks(connection)
    group = DuplicateGroup(
        duplicate_group_id="dup-1",
        member_chunk_ids=["chunk-1"],
        representative_chunk_id="chunk-1",
        duplicate_type=DuplicateType.EXACT,
        similarity_min=1.0,
        similarity_max=1.0,
    )
    upsert_duplicate_group(connection, group)

    assert delete_document(connection, "doc-1")

    assert count_documents(connection) == 0
    assert count_chunks(connection) == 0
    assert count_duplicate_groups(connection) == 0
    assert count_duplicate_group_members(connection) == 0
    assert search_chunks(connection, "transit") == []


def test_delete_parent_sets_child_parent_to_null(database) -> None:
    connection, _ = database
    upsert_document(connection, make_document())
    upsert_chunks(
        connection,
        [
            make_chunk("parent"),
            make_chunk(
                "child",
                chunk_level=ChunkLevel.SUBMODULE,
                section_type="warrant",
                parent_argument_id="parent",
            ),
        ],
    )

    delete_chunk(connection, "parent")

    assert get_chunk(connection, "child").parent_argument_id is None


def test_delete_duplicate_group_cascades_members_and_clears_chunk_marker(database) -> None:
    connection, _ = database
    persist_document_and_chunks(connection)
    group = DuplicateGroup(
        duplicate_group_id="dup-1",
        member_chunk_ids=["chunk-1"],
        representative_chunk_id="chunk-1",
        duplicate_type=DuplicateType.EXACT,
        similarity_min=1.0,
        similarity_max=1.0,
    )
    upsert_duplicate_group(connection, group)
    update_duplicate_groups(
        connection,
        [make_chunk(duplicate_group="dup-1")],
    )

    assert delete_duplicate_group(connection, "dup-1")
    assert count_duplicate_group_members(connection) == 0
    assert get_chunk(connection, "chunk-1").duplicate_group is None


def test_fts_lexical_search_stays_synchronized_with_upsert_and_delete(database) -> None:
    connection, _ = database
    assert full_text_search_available(connection)
    document, chunks = persist_document_and_chunks(connection)

    hits = search_chunks(connection, '"public transit"')
    assert [hit.chunk.chunk_id for hit in hits] == ["chunk-1"]
    assert "[Public transit]" in hits[0].snippet

    updated = chunks[0].model_copy(
        update={"text": "Nuclear energy provides reliable baseload power.", "token_count": 7}
    )
    upsert_chunk(connection, updated)
    assert search_chunks(connection, "transit") == []
    assert [hit.chunk.chunk_id for hit in search_chunks(connection, "nuclear energy")] == [
        "chunk-1"
    ]

    delete_document(connection, document.document_id)
    assert search_chunks(connection, "nuclear") == []


def test_fts_can_be_disabled_with_configuration(tmp_path: Path) -> None:
    settings = Settings(
        project_root=tmp_path,
        storage={"database_path": "disabled.db", "enable_full_text_search": False},
    )
    connection = connect(settings=settings)
    try:
        create_schema(connection, settings=settings)
        assert not full_text_search_available(connection)
    finally:
        connection.close()


def test_clear_and_recreate_behavior(database) -> None:
    connection, path = database
    persist_document_and_chunks(connection)
    clear_database(connection)

    assert count_documents(connection) == 0
    assert count_chunks(connection) == 0
    assert {"documents", "chunks"} <= table_names(connection)

    connection.close()
    recreate_database(path)
    rebuilt = connect(path)
    try:
        assert count_documents(rebuilt) == 0
        assert full_text_search_available(rebuilt)
    finally:
        rebuilt.close()


def test_nested_transaction_rolls_back_as_one_unit(database) -> None:
    connection, _ = database

    with pytest.raises(sqlite3.IntegrityError), transaction(connection):
        upsert_document(connection, make_document())
        upsert_chunk(connection, make_chunk(document_id="missing"))

    assert count_documents(connection) == 0
