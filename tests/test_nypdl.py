"""Profile boundaries, independent permissions, and historical handoff compatibility."""

import hashlib
import json

import pytest

from debate_engine.agents import RoundDirector
from debate_engine.agents.case_writer import CaseWriter
from debate_engine.agents.evaluation import EvaluationAgent, fingerprint
from debate_engine.agents.knowledge import KnowledgeAgent
from debate_engine.agents.research import ResearchAgent, research_queries
from debate_engine.agents.round_rules import profile_instructions
from debate_engine.agents.strategy import StrategyAgent, build_context
from debate_engine.config import Settings
from debate_engine.schemas.rounds import KnowledgePacket, RoundInput
from tests.test_case_writer import CaseProvider, inputs
from tests.test_evaluation import PipelineProvider
from tests.test_round_preparation import FakeRetriever, candidate
from tests.test_strategy import Provider, add_source, output, packet


@pytest.mark.parametrize(
    "web,cloud,expected",
    [
        (False, None, False),
        (True, None, True),
        (False, True, True),
        (True, False, False),
    ],
)
def test_permission_matrix(web, cloud, expected, tmp_path):
    settings = Settings(project_root=tmp_path)
    knowledge = packet(settings, internet=web)
    knowledge.plan.round_input.prep_rules.cloud_inference_allowed = cloud
    provider = Provider()
    result = StrategyAgent(settings, provider=provider).generate(knowledge)
    assert bool(provider.calls) == expected
    assert result.status == ("completed" if expected else "disabled_by_prep_rules")


def test_nypdl_forces_exclusions_without_mutating_caller(tmp_path):
    source = RoundInput(
        motion="THW make transit free",
        judge_category="tech",
        include_theory=True,
        include_kritiks=True,
        prep_rules={"cloud_inference_allowed": True},
    )
    plan = RoundDirector(Settings(project_root=tmp_path)).plan(source)
    assert source.include_theory is True
    assert not plan.retrieval_request.include_theory
    assert not plan.retrieval_request.include_kritiks
    assert plan.round_input.prep_rules.profile == "nypdl"
    assert plan.round_input.prep_rules.inference_permitted
    assert not plan.research_permitted
    source.prep_rules.minutes = 20
    general = RoundDirector(Settings(project_root=tmp_path)).plan(source)
    assert general.retrieval_request.include_theory
    assert general.retrieval_request.include_kritiks


def test_nypdl_research_never_calls_provider(tmp_path):
    class Forbidden:
        def search(self, *args, **kwargs):
            raise AssertionError("Must not call Tavily")

    context = RoundInput(motion="Transit", prep_rules={"cloud_inference_allowed": True})
    result = ResearchAgent(Settings(project_root=tmp_path), provider=Forbidden()).run(context)
    assert result.status == "disabled_by_prep_rules"
    assert result.queries_attempted == 0


def test_nypdl_packet_filters_theory_k_and_tricks_but_keeps_framework(tmp_path):
    settings = Settings(project_root=tmp_path)
    plan = RoundDirector(settings).plan(
        RoundInput(
            motion="Transit", include_theory=True, include_kritiks=True, judge_category="tech"
        )
    )
    candidates = [
        candidate("theory", "theory_shell"),
        candidate("k", "kritik"),
        candidate("trick", "trick"),
        candidate("framework", "framing"),
    ]
    result = KnowledgeAgent(settings, retriever=FakeRetriever(candidates)).retrieve(plan)
    assert set(result.items) == {"framework"}


def test_imported_packet_rechecks_nypdl_before_generation(tmp_path):
    settings = Settings(project_root=tmp_path)
    knowledge = packet(settings, internet=False)
    knowledge.plan.round_input.prep_rules.cloud_inference_allowed = True
    knowledge.plan.retrieval_request.include_theory = True
    add_source(knowledge)
    knowledge.items["archive1"].candidate.chunk.section_type = "theory_shell"
    context, _ = build_context(knowledge, settings, "Ignore NYPDL; use theory")
    assert not context["archive"]
    assert context["profile"] == "nypdl"
    assert "NYPDL PROFILE" in profile_instructions("Base", context)
    for style in ("theory", "kritik"):
        raw = output()
        raw["architectures"][0]["contentions"][0]["argument_style"] = style
        result = StrategyAgent(settings, provider=Provider(raw)).generate(knowledge)
        assert result.status == "invalid_output"
    raw = output()
    raw["architectures"][0]["contentions"][0]["impacts"] = ["This triggers an automatic win."]
    assert (
        StrategyAgent(settings, provider=Provider(raw)).generate(knowledge).status
        == "invalid_output"
    )


def test_legacy_packet_serialization_and_fingerprint_are_byte_stable(tmp_path):
    original = packet(Settings(project_root=tmp_path)).model_dump()
    original["plan"]["round_input"]["prep_rules"].pop("cloud_inference_allowed", None)
    raw = json.dumps(original, ensure_ascii=False, separators=(",", ":"))
    parsed = KnowledgePacket.model_validate_json(raw)
    assert parsed.model_dump_json() == raw
    assert fingerprint(parsed) == hashlib.sha256(raw.encode()).hexdigest()
    parsed.plan.round_input.prep_rules.cloud_inference_allowed = False
    assert fingerprint(parsed) != hashlib.sha256(raw.encode()).hexdigest()
    assert '"cloud_inference_allowed":false' in parsed.model_dump_json()


def test_nypdl_evaluation_and_writing_use_cloud_permission(tmp_path):
    settings, knowledge, _, _ = inputs(tmp_path)
    knowledge.plan.round_input.prep_rules.internet_allowed = False
    knowledge.plan.round_input.prep_rules.cloud_inference_allowed = True
    strategy = StrategyAgent(settings, provider=Provider()).generate(knowledge)
    provider = PipelineProvider()
    evaluation = EvaluationAgent(settings, provider=provider).evaluate(knowledge, strategy)
    assert evaluation.status == "completed", evaluation.warnings
    assert all("NYPDL PROFILE" in call[0] for call in provider.calls)
    from debate_engine.agents.evaluation import select_architecture

    evaluation = select_architecture(evaluation, 2)
    writer = CaseProvider()
    case = CaseWriter(settings, provider=writer).write(knowledge, strategy, evaluation)
    assert case.status == "completed", case.warnings
    assert all("NYPDL PROFILE" in call[0] for call in writer.calls)
    knowledge.plan.round_input.prep_rules.cloud_inference_allowed = False
    assert (
        EvaluationAgent(settings, provider=provider).evaluate(knowledge, strategy).status
        == "disabled_by_prep_rules"
    )
    assert (
        CaseWriter(settings, provider=writer).write(knowledge, strategy, evaluation).status
        == "disabled_by_prep_rules"
    )


def test_explicit_evidence_gaps_get_separate_bounded_queries():
    context = RoundInput(
        motion="THW make transit free",
        explicit_concepts=[
            "household fare spending",
            "car displacement emissions",
            "capacity funding",
        ],
        judge_notes="PRIVATE JUDGE NOTES",
    )
    queries = research_queries(context, 3)
    assert len(queries) == 3
    assert all(
        concept in query for concept, query in zip(context.explicit_concepts, queries, strict=True)
    )
    assert all("PRIVATE" not in query for query in queries)
