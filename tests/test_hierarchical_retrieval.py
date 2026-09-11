"""Synthetic semantic+FTS retrieval pipeline tests."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from debate_engine.config import Settings
from debate_engine.retrieval import HierarchicalRetriever
from debate_engine.retrieval.vector_store import SemanticSearchHit
from debate_engine.schemas import (
    ChunkLevel,
    DebateChunk,
    DebateDocument,
    DocumentType,
    DuplicateGroup,
    DuplicateType,
    Freshness,
    JudgeCategory,
    RetrievalRequest,
    Side,
    SourceGroup,
)
from debate_engine.storage import (
    connect,
    initialize_database,
    update_duplicate_groups,
    upsert_chunks,
    upsert_document,
    upsert_duplicate_group,
)


class FakeSemanticSearcher:
    def __init__(self, scores: dict[str, float]) -> None:
        self.scores = scores
        self.calls: list[tuple[str, int, dict[str, object] | None, bool]] = []

    def semantic_search(
        self,
        query: str,
        *,
        database=None,
        top_k=10,
        filters=None,
        hydrate=True,
    ):
        self.calls.append((query, top_k, filters, hydrate))
        return [
            SemanticSearchHit(
                chunk_id=chunk_id,
                distance=1.0 - similarity,
                similarity=similarity,
                metadata={},
            )
            for chunk_id, similarity in sorted(
                self.scores.items(),
                key=lambda item: (-item[1], item[0]),
            )[:top_k]
        ]


def retrieval_settings(tmp_path: Path, **overrides: object) -> Settings:
    retrieval: dict[str, object] = {
        "semantic_candidate_pool": 30,
        "semantic_candidates_per_query": 20,
        "lexical_candidate_pool": 20,
        "lexical_candidates_per_query": 10,
        "default_argument_results": 4,
        "default_submodule_results": 8,
        "minimum_base_relevance": 0.18,
    }
    retrieval.update(overrides)
    return Settings(
        project_root=tmp_path,
        storage={"database_path": tmp_path / "debate.db"},
        vector_index={"chroma_path": tmp_path / "chroma"},
        retrieval=retrieval,
    )


def make_chunk(chunk_id: str, **overrides: object) -> DebateChunk:
    values: dict[str, object] = {
        "chunk_id": chunk_id,
        "document_id": f"doc-{chunk_id}",
        "source_file": f"{chunk_id}.md",
        "source_path": f"/fixtures/{chunk_id}.md",
        "source_group": SourceGroup.OTHER,
        "document_type": DocumentType.CASE,
        "section_type": "contention",
        "chunk_level": ChunkLevel.ARGUMENT,
        "original_heading": "Economic Growth",
        "argument_heading": "Economic Growth",
        "heading_path": ["Contention", "Economic Growth"],
        "side": Side.UNKNOWN,
        "text": "Regulation reduces private investment and economic growth.",
        "token_count": 8,
        "freshness": Freshness.UNKNOWN,
        "structure_confidence": 0.9,
    }
    values.update(overrides)
    return DebateChunk(**values)  # type: ignore[arg-type]


def persist(connection: sqlite3.Connection, chunks: list[DebateChunk]) -> None:
    documents: dict[str, DebateDocument] = {}
    for chunk in chunks:
        documents[chunk.document_id] = DebateDocument(
            document_id=chunk.document_id,
            filename=chunk.source_file,
            full_path=chunk.source_path,
            source_group=chunk.source_group,
            document_type=chunk.document_type,
            side=chunk.side,
            title=chunk.argument_heading,
            raw_text=chunk.text,
            priority_weight=chunk.priority_weight,
        )
    for document in documents.values():
        upsert_document(connection, document)
    upsert_chunks(connection, chunks)


@pytest.fixture
def database(tmp_path: Path):
    settings = retrieval_settings(tmp_path)
    initialize_database(settings=settings)
    connection = connect(settings=settings)
    try:
        yield settings, connection
    finally:
        connection.close()


def retrieve(
    settings: Settings,
    scores: dict[str, float],
    request: RetrievalRequest,
):
    searcher = FakeSemanticSearcher(scores)
    result = HierarchicalRetriever(
        settings,
        semantic_searcher=searcher,
        database=settings.storage.database_path,
    ).retrieve(request)
    return result, searcher


def test_semantic_and_lexical_candidates_merge_with_score_breakdown(database) -> None:
    settings, connection = database
    argument = make_chunk("argument")
    module = make_chunk(
        "module",
        document_id=argument.document_id,
        source_file=argument.source_file,
        source_path=argument.source_path,
        section_type="internal_link",
        chunk_level=ChunkLevel.SUBMODULE,
        parent_argument_id=argument.chunk_id,
        text="Uncertainty delays capital expenditure through investor confidence.",
    )
    persist(connection, [argument, module])

    result, searcher = retrieve(
        settings,
        {"argument": 0.78, "module": 0.86},
        RetrievalRequest(motion="regulation reduces private investment"),
    )

    assert result.statistics.semantic_hits > 0
    assert result.statistics.lexical_hits > 0
    assert result.statistics.merged_candidates == 2
    assert [candidate.chunk_id for candidate in result.full_arguments] == ["argument"]
    assert [candidate.chunk_id for candidate in result.submodules] == ["module"]
    assert result.submodules[0].semantic_score == pytest.approx(0.86)
    assert result.full_arguments[0].lexical_score > 0
    assert all(not call[3] for call in searcher.calls)


def test_argument_child_and_submodule_parent_are_hydrated(database) -> None:
    settings, connection = database
    parent = make_chunk("parent")
    child = make_chunk(
        "child",
        document_id=parent.document_id,
        source_file=parent.source_file,
        source_path=parent.source_path,
        section_type="internal_link",
        chunk_level=ChunkLevel.SUBMODULE,
        parent_argument_id=parent.chunk_id,
        text="Investor confidence mediates regulation's effect on investment.",
    )
    persist(connection, [parent, child])

    result, _ = retrieve(
        settings,
        {"parent": 0.82, "child": 0.84},
        RetrievalRequest(motion="regulation investment economic growth"),
    )

    assert result.full_arguments[0].related_children[0].chunk_id == "child"
    assert result.submodules[0].parent_argument.chunk_id == "parent"


def test_duplicate_candidates_resolve_to_preferred_representative(database) -> None:
    settings, connection = database
    representative = make_chunk("preferred", duplicate_group="dup-1")
    alternate = make_chunk(
        "alternate",
        document_id="doc-alternate",
        duplicate_group="dup-1",
        source_group=SourceGroup.OTHER,
    )
    persist(connection, [representative, alternate])
    group = DuplicateGroup(
        duplicate_group_id="dup-1",
        member_chunk_ids=["preferred", "alternate"],
        representative_chunk_id="preferred",
        duplicate_type=DuplicateType.EXACT,
        similarity_min=1.0,
        similarity_max=1.0,
    )
    upsert_duplicate_group(connection, group)
    update_duplicate_groups(connection, [representative, alternate])

    result, _ = retrieve(
        settings,
        {"alternate": 0.95, "preferred": 0.80},
        RetrievalRequest(motion="regulation reduces private investment"),
    )

    returned = [candidate.chunk_id for candidate in result.full_arguments]
    assert returned == ["preferred"]
    assert result.statistics.duplicate_candidates_suppressed == 1


def test_submodule_text_identical_to_selected_argument_is_not_repeated(database) -> None:
    settings, connection = database
    parent = make_chunk("parent")
    repeated = make_chunk(
        "repeated",
        document_id=parent.document_id,
        source_file=parent.source_file,
        source_path=parent.source_path,
        chunk_level=ChunkLevel.SUBMODULE,
        section_type="internal_link",
        parent_argument_id=parent.chunk_id,
        text=parent.text,
    )
    persist(connection, [parent, repeated])

    result, _ = retrieve(
        settings,
        {"parent": 0.85, "repeated": 0.84},
        RetrievalRequest(motion="regulation reduces private investment"),
    )

    assert [candidate.chunk_id for candidate in result.full_arguments] == ["parent"]
    assert result.submodules == []
    assert result.statistics.redundant_candidates_suppressed == 1


def test_theory_hierarchy_and_nonpersonal_exclusion_end_to_end(database) -> None:
    settings, connection = database
    theory_file = make_chunk(
        "theory-file",
        source_group=SourceGroup.PERSONAL,
        document_type=DocumentType.MASTERFILE,
        section_type="theory_shell",
        is_special_masterfile=True,
        special_masterfile_name="Theory File - Sandhu",
        text="Conditional advocacies create strategy skew and unfairness.",
    )
    personal = make_chunk(
        "personal-theory",
        source_group=SourceGroup.PERSONAL,
        document_type=DocumentType.THEORY,
        section_type="theory_shell",
        text="Conditionality creates strategy skew.",
    )
    other = make_chunk(
        "other-theory",
        source_group=SourceGroup.OTHER,
        document_type=DocumentType.THEORY,
        section_type="theory_shell",
        text="Conditionality creates strategy skew.",
    )
    persist(connection, [theory_file, personal, other])

    result, _ = retrieve(
        settings,
        {"theory-file": 0.82, "personal-theory": 0.82, "other-theory": 0.95},
        RetrievalRequest(motion="conditional advocacies bad strategy skew"),
    )

    assert [item.chunk_id for item in result.full_arguments] == [
        "theory-file",
        "personal-theory",
    ]
    assert result.statistics.ineligible_candidates == 1


def test_judge_rules_filter_kritiks_end_to_end(database) -> None:
    settings, connection = database
    kritik = make_chunk(
        "kritik",
        source_group=SourceGroup.PERSONAL,
        document_type=DocumentType.KRITIK,
        section_type="kritik",
        text="Capitalism structures exploitation through market ontology.",
    )
    normal = make_chunk(
        "normal",
        source_group=SourceGroup.PERSONAL,
        text="Market concentration reduces worker bargaining power.",
    )
    persist(connection, [kritik, normal])
    scores = {"kritik": 0.90, "normal": 0.75}

    tech, _ = retrieve(
        settings,
        scores,
        RetrievalRequest(
            motion="capitalism kritik market ontology",
            judge_category=JudgeCategory.TECH,
        ),
    )
    lay, _ = retrieve(
        settings,
        scores,
        RetrievalRequest(
            motion="capitalism kritik market ontology",
            judge_category=JudgeCategory.FULLY_LAY,
        ),
    )

    assert "kritik" in [candidate.chunk_id for candidate in tech.full_arguments]
    assert "kritik" not in [candidate.chunk_id for candidate in lay.full_arguments]


def test_highly_relevant_past_case_beats_weak_personal_end_to_end(database) -> None:
    settings, connection = database
    personal = make_chunk(
        "personal",
        source_group=SourceGroup.PERSONAL,
        text="Military deterrence changes alliance credibility.",
        heading_path=["Security"],
    )
    past = make_chunk(
        "past",
        source_group=SourceGroup.PAST_CASE,
        source_file="Mexico GM Corn Case.md",
        text="Mexico allowing genetically modified corn raises agricultural productivity.",
        heading_path=["Mexico", "GM Corn"],
    )
    persist(connection, [personal, past])

    result, _ = retrieve(
        settings,
        {"personal": 0.30, "past": 0.91},
        RetrievalRequest(motion="Mexico should allow genetically modified corn"),
    )

    assert result.full_arguments[0].chunk_id == "past"
    assert result.full_arguments[0].motion_similarity_score > 0


def test_source_filter_is_sent_to_chroma_and_enforced(database) -> None:
    settings, connection = database
    personal = make_chunk("personal", source_group=SourceGroup.PERSONAL)
    other = make_chunk("other", source_group=SourceGroup.OTHER)
    persist(connection, [personal, other])

    result, searcher = retrieve(
        settings,
        {"personal": 0.8, "other": 0.9},
        RetrievalRequest(
            motion="regulation reduces private investment",
            source_group=SourceGroup.PERSONAL,
        ),
    )

    assert [candidate.chunk_id for candidate in result.full_arguments] == ["personal"]
    assert all(call[2] == {"source_group": "personal"} for call in searcher.calls)


def test_graceful_low_result_behavior_returns_fewer_than_requested(database) -> None:
    settings, connection = database
    irrelevant = make_chunk(
        "irrelevant",
        text="Renaissance painting uses perspective and natural pigments.",
        heading_path=["Art History"],
    )
    persist(connection, [irrelevant])

    result, _ = retrieve(
        settings,
        {"irrelevant": 0.05},
        RetrievalRequest(
            motion="Mexico genetically modified corn agriculture",
            desired_arguments=5,
            desired_submodules=20,
        ),
    )

    assert result.full_arguments == []
    assert result.submodules == []
    assert result.statistics.below_relevance_threshold == 1
    assert any("No archive material" in warning for warning in result.warnings)


def test_retrieval_is_deterministic_and_obeys_requested_counts(database) -> None:
    settings, connection = database
    chunks = [
        make_chunk(f"argument-{index}", text=f"Regulation investment mechanism {index}.")
        for index in range(4)
    ]
    persist(connection, chunks)
    request = RetrievalRequest(
        motion="regulation investment mechanism",
        desired_arguments=2,
        desired_submodules=0,
    )
    searcher = FakeSemanticSearcher({chunk.chunk_id: 0.8 for chunk in chunks})
    retriever = HierarchicalRetriever(
        settings,
        semantic_searcher=searcher,
        database=settings.storage.database_path,
    )

    first = retriever.retrieve(request)
    second = retriever.retrieve(request)

    assert [item.chunk_id for item in first.full_arguments] == [
        item.chunk_id for item in second.full_arguments
    ]
    assert len(first.full_arguments) == 2


def test_end_to_end_returns_diverse_arguments_and_modules(database) -> None:
    settings, connection = database
    argument = make_chunk(
        "argument",
        source_group=SourceGroup.PAST_CASE,
        source_file="Regulation Case.md",
    )
    modules = [
        make_chunk(
            "uniqueness",
            document_id=argument.document_id,
            source_file=argument.source_file,
            source_path=argument.source_path,
            chunk_level=ChunkLevel.SUBMODULE,
            section_type="uniqueness",
            parent_argument_id=argument.chunk_id,
            text="Investment is currently declining under regulatory uncertainty.",
            freshness=Freshness.CURRENT,
        ),
        make_chunk(
            "internal-link",
            document_id="doc-master",
            source_file="Case File Sandhu.docx",
            source_path="/fixtures/Case File Sandhu.docx",
            source_group=SourceGroup.PERSONAL,
            document_type=DocumentType.MASTERFILE,
            chunk_level=ChunkLevel.SUBMODULE,
            section_type="internal_link",
            parent_argument_id=None,
            is_special_masterfile=True,
            special_masterfile_name="Case File Sandhu",
            text="Investor uncertainty reduces long-term capital formation.",
        ),
        make_chunk(
            "impact",
            document_id="doc-impact",
            chunk_level=ChunkLevel.SUBMODULE,
            section_type="impact",
            text="Economic collapse increases poverty and reduces human welfare.",
        ),
        make_chunk(
            "second-il",
            document_id="doc-second",
            chunk_level=ChunkLevel.SUBMODULE,
            section_type="internal_link",
            text="Compliance uncertainty lowers long-term capital expenditure.",
        ),
    ]
    persist(connection, [argument, *modules])
    scores = {
        "argument": 0.83,
        "uniqueness": 0.80,
        "internal-link": 0.88,
        "impact": 0.84,
        "second-il": 0.86,
    }

    result, _ = retrieve(
        settings,
        scores,
        RetrievalRequest(
            motion="regulation reduces investment causing economic decline and poverty",
            side=Side.AFF,
            desired_arguments=3,
            desired_submodules=4,
        ),
    )

    assert result.full_arguments[0].chunk_id == "argument"
    returned_types = [candidate.chunk.section_type for candidate in result.submodules[:3]]
    assert "internal_link" in returned_types
    assert "impact" in returned_types
    assert len(set(returned_types)) >= 2
    assert any(candidate.masterfile_score > 0 for candidate in result.submodules)
    assert result.statistics.full_arguments_returned == 1
    assert result.statistics.submodules_returned == 4
