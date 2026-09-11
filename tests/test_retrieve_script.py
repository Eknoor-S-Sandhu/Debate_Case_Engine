"""Hierarchical retrieval debug CLI smoke test."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from debate_engine.config import Settings
from debate_engine.schemas import (
    ChunkLevel,
    DebateChunk,
    GeneratedQuery,
    QueryFamily,
    RetrievalCandidate,
    RetrievalResult,
    RetrievalStatistics,
    SupportLevel,
)
from scripts.retrieve import app


def test_retrieve_cli_prints_queries_hierarchies_and_scores(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database = tmp_path / "debate.db"
    database.touch()
    settings = Settings(
        project_root=tmp_path,
        storage={"database_path": database},
        vector_index={"chroma_path": tmp_path / "chroma"},
    )
    argument = DebateChunk(
        chunk_id="argument",
        document_id="doc-1",
        source_file="case.md",
        source_path="/fixtures/case.md",
        section_type="contention",
        chunk_level=ChunkLevel.ARGUMENT,
        heading_path=["Contention: Economy"],
        text="Regulation reduces private investment.",
        token_count=5,
    )
    candidate = RetrievalCandidate(
        chunk_id=argument.chunk_id,
        chunk=argument,
        semantic_score=0.8,
        lexical_score=0.5,
        base_score=0.7,
        source_score=0.02,
        final_score=0.72,
        support_score=0.75,
        support_level=SupportLevel.HIGH,
        rank=1,
        reasons=["strong semantic match"],
    )

    class FakeRetriever:
        def __init__(self, configured, *, database):
            assert configured is settings

        def retrieve(self, request):
            return RetrievalResult(
                request=request,
                generated_queries=[
                    GeneratedQuery(
                        family=QueryFamily.FULL_MOTION,
                        text="regulation reduces private investment",
                    )
                ],
                full_arguments=[candidate],
                submodules=[],
                statistics=RetrievalStatistics(semantic_hits=3, merged_candidates=1),
            )

    monkeypatch.setattr("scripts.retrieve.get_settings", lambda: settings)
    monkeypatch.setattr("scripts.retrieve.HierarchicalRetriever", FakeRetriever)

    result = CliRunner().invoke(
        app,
        [
            "THW regulate investment",
            "--side",
            "aff",
            "--judge",
            "tech",
            "--arguments",
            "3",
            "--modules",
            "5",
            "--show-scores",
            "--show-text",
        ],
    )

    assert result.exit_code == 0
    assert "GENERATED QUERIES" in result.output
    assert "[full_motion] regulation reduces private investment" in result.output
    assert "RELATED FULL ARGUMENTS" in result.output
    assert "score=0.7200 support=high" in result.output
    assert "semantic=0.8000" in result.output
    assert "Regulation reduces private investment." in result.output
    assert "REUSABLE SUBMODULES" in result.output
    assert "Semantic hits: 3" in result.output
