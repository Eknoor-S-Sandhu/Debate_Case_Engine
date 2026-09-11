"""Milestone 10 contracts, local retrieval integration, CLI, and UI tests."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from streamlit.testing.v1 import AppTest
from typer.testing import CliRunner

from debate_engine.agents import KnowledgeAgent, RoundDirector
from debate_engine.agents.knowledge import LocalSemanticSearch, categorize, verification_notes
from debate_engine.config import Settings
from debate_engine.retrieval.embeddings import EmbeddingService
from debate_engine.schemas import (
    DebateChunk,
    DebateDocument,
    RetrievalCandidate,
    RetrievalResult,
    RetrievalStatistics,
)
from debate_engine.schemas.rounds import KnowledgePacket, RoundInput
from debate_engine.storage import connect, initialize_database, upsert_chunks, upsert_document
from scripts.prepare_round import app


@pytest.fixture
def settings(tmp_path):
    return Settings(project_root=tmp_path)


def candidate(chunk_id="c1", section="impact", **overrides):
    data = dict(
        chunk_id=chunk_id,
        document_id="doc",
        source_file="case.md",
        source_path="/archive/case.md",
        text="Transit improves access to employment.",
        section_type=section,
        chunk_level="submodule",
        source_group="personal",
    )
    data.update(overrides)
    chunk = DebateChunk(**data)
    return RetrievalCandidate(chunk_id=chunk_id, chunk=chunk, final_score=0.8, rank=1)


class FakeRetriever:
    def __init__(self, candidates):
        self.candidates = candidates
        self.calls = []

    def retrieve(self, request):
        self.calls.append(request)
        return RetrievalResult(
            request=request,
            generated_queries=[],
            full_arguments=[],
            submodules=self.candidates,
            statistics=RetrievalStatistics(),
        )


@pytest.mark.parametrize(
    "motion,expected",
    [
        ("THW subsidize transit", "policy"),
        ("This House Would subsidize transit", "policy"),
        ("THR celebrity politics", "value"),
        ("THP public ownership", "value"),
        ("THBT democracy is best", None),
    ],
)
def test_conservative_round_inference(settings, motion, expected):
    plan = RoundDirector(settings).plan(RoundInput(motion=motion))
    assert plan.retrieval_request.round_type == expected
    assert plan.research_permitted is False
    assert plan.research_status == "disabled_by_prep_rules"
    assert plan.generated_queries


def test_explicit_context_and_top_k_are_preserved(settings):
    context = RoundInput(
        motion="THW subsidize transit",
        round_type="fact",
        judge_category="fully_lay",
        judge_notes="Prefer clear examples",
        side="opp",
        include_theory=False,
        include_kritiks=True,
        desired_top_k=3,
        prep_rules={"minutes": 20, "internet_allowed": True},
    )
    snapshot = context.model_dump()
    plan = RoundDirector(settings).plan(context)
    assert plan.retrieval_request.round_type == "fact"
    assert plan.retrieval_request.desired_top_k == 3
    assert plan.retrieval_request.desired_arguments is None
    assert plan.retrieval_request.judge_notes == context.judge_notes
    assert plan.retrieval_request.include_theory is False
    assert plan.retrieval_request.include_kritiks is True
    assert plan.research_status == "permitted_but_not_implemented"
    assert context.model_dump() == snapshot


@pytest.mark.parametrize(
    "fields",
    [
        {"motion": " "},
        {"motion": "x", "prep_rules": {"minutes": 0}},
        {"motion": "x", "unknown_field": True},
    ],
)
def test_invalid_rounds_rejected(fields):
    with pytest.raises(ValidationError):
        RoundInput(**fields)


def test_zero_result_request_rejected(settings):
    with pytest.raises(ValueError, match="at least one"):
        RoundDirector(settings).plan(
            RoundInput(motion="x", desired_arguments=0, desired_submodules=0)
        )


def test_packet_preserves_text_deduplicates_and_roundtrips(settings):
    original = candidate(text="Original wording.\nExact spacing preserved.")
    original.related_children = [candidate("child").chunk]
    backend = FakeRetriever([original, original])
    plan = RoundDirector(settings).plan(RoundInput(motion="THW expand transit"))
    packet = KnowledgeAgent(settings, retriever=backend).retrieve(plan)
    assert len(backend.calls) == 1
    assert packet.groups["impacts"] == ["c1"]
    assert packet.items["c1"].candidate.chunk == original.chunk
    assert not packet.items["c1"].candidate.related_children
    assert original.related_children
    assert packet.coverage_gaps
    assert KnowledgePacket.model_validate_json(packet.model_dump_json()) == packet


@pytest.mark.parametrize(
    "section,category",
    [
        ("uniqueness", "uniqueness"),
        ("internal_link", "internal_links"),
        ("link", "links"),
        ("impact", "impacts"),
        ("warrant", "warrants"),
        ("solvency", "solvency"),
        ("answer", "preempts"),
        ("framing", "frameworks"),
        ("unrecognized", "other_modules"),
        ("theory_shell", "theory_k_options"),
    ],
)
def test_functional_categories(section, category):
    assert categorize(candidate(section=section)) == category


def test_argument_category_does_not_claim_full_case():
    assert categorize(candidate(chunk_level="argument")) == "related_arguments"


def test_staleness_flags_do_not_rewrite_original():
    stale = candidate(section="uniqueness", year=2014, freshness="stale_empirics")
    assert len(verification_notes(stale, 2026)) >= 2
    assert stale.chunk.freshness == "stale_empirics"
    theory = candidate(section="theory_shell", year=2014, freshness="evergreen")
    assert not any("year" in n or "outdated" in n for n in verification_notes(theory, 2026))
    undated = candidate(section="empirics")
    assert any("undated" in n for n in verification_notes(undated, 2026))


def test_packet_rechecks_eligibility(settings):
    backend = FakeRetriever(
        [
            candidate("theory", "theory_shell", source_group="other"),
            candidate("k", "kritik"),
        ]
    )
    plan = RoundDirector(settings).plan(RoundInput(motion="Transit", include_theory=True))
    packet = KnowledgeAgent(settings, retriever=backend).retrieve(plan)
    assert not packet.items
    assert any("non-personal theory" in w for w in packet.warnings)


def test_mismatched_chunk_ids_rejected(settings):
    wrong = candidate()
    wrong.chunk_id = "wrong"
    with pytest.raises(ValueError, match="IDs disagree"):
        KnowledgeAgent(settings, retriever=FakeRetriever([wrong])).retrieve(
            RoundDirector(settings).plan(RoundInput(motion="Transit"))
        )


def test_missing_database_does_not_create_it(settings):
    with pytest.raises(FileNotFoundError):
        RoundDirector(settings).prepare(RoundInput(motion="Transit"))
    assert not settings.storage.database_path.exists()


def test_cache_only_embeddings_never_attempt_download(settings):
    attempts = []

    def factory(*args, **kwargs):
        attempts.append(kwargs["local_files_only"])
        raise OSError("Cache missing")

    service = EmbeddingService(settings, model_factory=factory, allow_download=False)
    with pytest.raises(RuntimeError, match="local cache"):
        service.embed_query("transit")
    assert attempts == [True]


def test_absent_vector_index_does_not_create_it(settings):
    search = LocalSemanticSearch(settings)
    with pytest.raises(RuntimeError, match="Vector index missing"):
        search.semantic_search("transit")
    assert not settings.vector_index.chroma_path.exists()


def test_real_sqlite_fts_round_to_packet_without_network(settings, monkeypatch):
    def no_network_client(*args, **kwargs):
        raise AssertionError("Absent vector index must not instantiate Chroma")

    monkeypatch.setattr("chromadb.PersistentClient", no_network_client)
    initialize_database(settings=settings)
    chunk = candidate(section="impact").chunk
    connection = connect(settings=settings)
    try:
        upsert_document(
            connection,
            DebateDocument(
                document_id="doc",
                filename="case.md",
                full_path="/archive/case.md",
            ),
        )
        upsert_chunks(connection, [chunk])
    finally:
        connection.close()
    packet = RoundDirector(settings).prepare(RoundInput(motion="Transit employment"))
    assert packet.statistics.lexical_hits > 0
    assert packet.statistics.semantic_hits == 0
    assert packet.items["c1"].candidate.chunk.text == chunk.text
    assert any("Vector index missing" in warning for warning in packet.warnings)
    assert not settings.vector_index.chroma_path.exists()


def test_cli_plan_json_does_not_need_database(tmp_path):
    source = tmp_path / "round.json"
    source.write_text(json.dumps({"motion": "THW subsidize transit"}))
    result = CliRunner().invoke(app, [str(source), "--plan-only", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["retrieval_request"]["round_type"] == "policy"
    source.write_text('{"motion":""}')
    assert CliRunner().invoke(app, [str(source)]).exit_code == 1


def test_round_ui_plan_and_invalid_input(settings, monkeypatch):
    monkeypatch.setattr("debate_engine.agents.director.get_settings", lambda: settings)
    path = Path(__file__).resolve().parents[1] / "ui/pages/1_Round_preparation.py"
    page = AppTest.from_file(str(path)).run()
    assert not page.exception
    page.text_area(key="motion").set_value("THW subsidize transit")
    page.button[0].click().run()
    assert not page.exception and page.json
    assert not settings.storage.database_path.exists()
    page.text_area(key="motion").set_value(" ")
    page.button[0].click().run()
    assert page.error and not page.json


def test_round_ui_packet_renders_provenance(settings, monkeypatch):
    plan = RoundDirector(settings).plan(RoundInput(motion="Transit"))
    packet = KnowledgeAgent(settings, retriever=FakeRetriever([candidate()])).retrieve(plan)
    monkeypatch.setattr(RoundDirector, "prepare", lambda *args, **kwargs: packet)
    path = Path(__file__).resolve().parents[1] / "ui/pages/1_Round_preparation.py"
    page = AppTest.from_file(str(path)).run()
    page.text_area(key="motion").set_value("Transit")
    page.button[1].click().run()
    assert not page.exception
    assert any(text.value == "/archive/case.md" for text in page.text)
    assert any(text.value == "Transit improves access to employment." for text in page.text)


def test_empty_packet_remains_empty(settings):
    plan = RoundDirector(settings).plan(RoundInput(motion="Unknown subject"))
    packet = KnowledgeAgent(settings, retriever=FakeRetriever([])).retrieve(plan)
    assert not packet.items
    assert all(not ids for ids in packet.groups.values())
    assert any("No eligible archive" in warning for warning in packet.warnings)


def test_backend_errors_are_not_disguised_as_success(settings):
    class BrokenRetriever:
        def retrieve(self, request):
            raise RuntimeError("Broken database")

    with pytest.raises(RuntimeError, match="Broken database"):
        KnowledgeAgent(settings, retriever=BrokenRetriever()).retrieve(
            RoundDirector(settings).plan(RoundInput(motion="Transit"))
        )


def test_cross_round_result_rejected(settings):
    class WrongRetriever(FakeRetriever):
        def retrieve(self, request):
            request.motion = "Different motion"
            return super().retrieve(request)

    plan = RoundDirector(settings).plan(RoundInput(motion="Transit"))
    with pytest.raises(ValueError, match="different round"):
        KnowledgeAgent(settings, retriever=WrongRetriever([])).retrieve(plan)
    assert plan.retrieval_request.motion == "Transit"


def test_absent_collection_not_created(settings, monkeypatch):
    settings.vector_index.chroma_path.mkdir(parents=True)
    (settings.vector_index.chroma_path / "chroma.sqlite3").touch()

    class Client:
        def list_collections(self):
            return []

    def factory(**kwargs):
        assert kwargs["settings"].anonymized_telemetry is False
        return Client()

    monkeypatch.setattr("chromadb.PersistentClient", factory)
    with pytest.raises(RuntimeError, match="collection missing"):
        LocalSemanticSearch(settings).semantic_search("Transit")


def test_local_semantic_search_uses_cache_only_and_stops_retrying(settings, monkeypatch):
    settings.vector_index.chroma_path.mkdir(parents=True)
    (settings.vector_index.chroma_path / "chroma.sqlite3").touch()

    class Client:
        def list_collections(self):
            return [settings.vector_index.collection_name]

    monkeypatch.setattr("chromadb.PersistentClient", lambda **kwargs: Client())
    calls = []

    class Store:
        def __init__(self, configured, *, client, embedding_service):
            assert not embedding_service.allow_download

        def semantic_search(self, query, **kwargs):
            calls.append(query)
            raise RuntimeError("Model cache missing")

    monkeypatch.setattr("debate_engine.agents.knowledge.VectorStore", Store)
    search = LocalSemanticSearch(settings)
    for query in ["Transit", "Jobs"]:
        with pytest.raises(RuntimeError, match="Model cache missing"):
            search.semantic_search(query)
    assert calls == ["Transit"]


def test_cli_packet_json_is_complete(tmp_path, settings, monkeypatch):
    context = RoundInput(motion="Transit")
    packet = KnowledgeAgent(settings, retriever=FakeRetriever([candidate()])).retrieve(
        RoundDirector(settings).plan(context)
    )
    monkeypatch.setattr(RoundDirector, "prepare", lambda *args, **kwargs: packet)
    source = tmp_path / "round.json"
    source.write_text(context.model_dump_json())
    result = CliRunner().invoke(app, [str(source), "--json"])
    assert result.exit_code == 0, result.output
    assert KnowledgePacket.model_validate_json(result.output) == packet
