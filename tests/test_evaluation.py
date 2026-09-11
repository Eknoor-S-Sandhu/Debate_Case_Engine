"""Milestone 13 workflow, failure boundaries, ranking, and user choice."""

import copy
import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest
from typer.testing import CliRunner

from debate_engine.agents import RoundDirector
from debate_engine.agents.evaluation import EvaluationAgent, select_architecture
from debate_engine.agents.strategy import StrategyAgent
from debate_engine.config import Settings
from debate_engine.schemas.evaluation import RUBRIC, EvaluationResult
from scripts.evaluate_strategies import app
from tests.test_strategy import Provider, add_source, output, packet


@pytest.fixture
def setup(tmp_path):
    settings = Settings(project_root=tmp_path)
    knowledge = packet(settings)
    strategy = StrategyAgent(settings, provider=Provider()).generate(knowledge)
    return settings, knowledge, strategy


def responses():
    critiques, repairs, evaluations = [], [], []
    for i, architecture in enumerate(output()["architectures"], start=1):
        critiques.append(
            {
                "architecture_id": i,
                "findings": [
                    {
                        "criterion": "link_chain_quality",
                        "contention_number": 1,
                        "severity": "high",
                        "weakness": "Service delivery is assumed.",
                        "opponent_response": "Funding need not produce reliable service.",
                        "repair_goal": "State the service-delivery condition explicitly.",
                    }
                ],
            }
        )
        architecture["contentions"][0]["preempts"].append(
            "Benefits depend on implementation producing reliable service."
        )
        repairs.append(
            {
                "architecture_id": i,
                "architecture": architecture,
                "changes": ["Made implementation conditionality explicit."],
                "responses": [
                    {
                        "finding_number": 1,
                        "status": "partially_addressed",
                        "explanation": "Clarified the condition; evidence is still needed.",
                    }
                ],
                "remaining_risks": ["Service improvements still need evidence."],
            }
        )
        evaluations.append(
            {
                "architecture_id": i,
                "scores": {
                    key: {"points": maximum - i, "rationale": "Conditional mechanism."}
                    for key, maximum in RUBRIC.items()
                },
                "tradeoffs": "Clarity improves, implementation remains uncertain.",
            }
        )
    return [{"critiques": critiques}, {"repairs": repairs}, {"evaluations": evaluations}]


class PipelineProvider:
    def __init__(self, values=None, fail_at=None):
        self.values = responses() if values is None else values
        self.calls = []
        self.fail_at = fail_at

    def generate(self, instructions, context, schema):
        index = len(self.calls)
        self.calls.append((instructions, json.loads(context), schema))
        if index == self.fail_at:
            raise RuntimeError("SECRET-provider-body")
        return self.values[index]


def test_full_pipeline_preserves_inputs_and_waits_for_user(setup):
    settings, knowledge, strategy = setup
    before = (knowledge.model_dump_json(), strategy.model_dump_json())
    provider = PipelineProvider()
    result = RoundDirector(settings).evaluate(knowledge, strategy, provider=provider)
    assert result.status == "completed", result.warnings
    assert len(provider.calls) == 3
    assert "RED TEAM" in provider.calls[0][0]
    assert "ONE REPAIR PASS" in provider.calls[1][0]
    assert "SCORE THE REPAIRED" in provider.calls[2][0]
    assert "critiques" in provider.calls[1][1]
    assert "repairs" in provider.calls[2][1]
    assert [r.total for r in result.rankings] == [92, 84, 76]
    assert [r.rank for r in result.rankings] == [1, 2, 3]
    assert result.selected_architecture_id is None
    chosen = select_architecture(result, 3)
    assert chosen.selected_architecture_id == 3
    assert result.selected_architecture_id is None
    assert len(provider.calls) == 3
    assert before == (knowledge.model_dump_json(), strategy.model_dump_json())
    assert EvaluationResult.model_validate_json(chosen.model_dump_json()) == chosen
    for _, _, schema in provider.calls:
        for node in [schema, *schema.get("$defs", {}).values()]:
            if node.get("type") == "object":
                assert set(node["required"]) == set(node["properties"])
                assert node["additionalProperties"] is False


def test_ties_share_rank_and_keep_original_id_order(setup):
    settings, knowledge, strategy = setup
    values = responses()
    values[2]["evaluations"][1]["scores"] = copy.deepcopy(values[2]["evaluations"][0]["scores"])
    values[2]["evaluations"].reverse()
    result = EvaluationAgent(settings, provider=PipelineProvider(values)).evaluate(
        knowledge, strategy
    )
    assert [r.rank for r in result.rankings] == [1, 1, 3]
    assert [r.architecture_id for r in result.rankings] == [1, 2, 3]


@pytest.mark.parametrize("mutation", ["offline", "incomplete", "wrong_packet", "side", "sources"])
def test_invalid_inputs_never_call_provider(setup, mutation):
    settings, knowledge, strategy = setup
    if mutation == "offline":
        knowledge.plan.round_input.prep_rules.internet_allowed = False
    elif mutation == "incomplete":
        strategy.status = "failed"
    elif mutation == "wrong_packet":
        knowledge.plan.round_input.motion = "Different motion"
    elif mutation == "side":
        knowledge.plan.retrieval_request.side = None
    else:
        strategy.supplied_archive_ids = ["missing"]
    provider = PipelineProvider()
    result = EvaluationAgent(settings, provider=provider).evaluate(knowledge, strategy)
    assert result.status != "completed" and not provider.calls
    with pytest.raises(ValueError):
        select_architecture(result, 1)


def test_missing_configuration_never_calls_provider(setup, monkeypatch):
    settings, knowledge, strategy = setup

    def fail(*args):
        pytest.fail("Must not construct provider")

    monkeypatch.setattr("debate_engine.agents.evaluation.create_provider", fail)
    assert EvaluationAgent(settings).evaluate(knowledge, strategy).status == "not_configured"


@pytest.mark.parametrize("stage", [0, 1, 2])
def test_provider_failure_stops_without_retry_or_selection(setup, stage):
    settings, knowledge, strategy = setup
    provider = PipelineProvider(fail_at=stage)
    result = EvaluationAgent(settings, provider=provider).evaluate(knowledge, strategy)
    assert result.status == "failed"
    assert result.stage == ["red_team", "repair", "scoring"][stage]
    assert len(provider.calls) == stage + 1
    assert not result.rankings and result.selected_architecture_id is None
    assert "SECRET" not in result.model_dump_json()
    assert bool(result.critiques) == (stage >= 1)
    assert bool(result.repairs) == (stage >= 2)
    assert EvaluationResult.model_validate_json(result.model_dump_json()) == result


@pytest.mark.parametrize("stage", [0, 1, 2])
@pytest.mark.parametrize("bad", ["duplicate_id", "missing", "extra", "malformed"])
def test_each_stage_validates_complete_exact_output(setup, stage, bad):
    settings, knowledge, strategy = setup
    values = responses()
    key = ["critiques", "repairs", "evaluations"][stage]
    if bad == "duplicate_id":
        values[stage][key][1]["architecture_id"] = 1
    elif bad == "missing":
        values[stage][key].pop()
    elif bad == "extra":
        values[stage]["selected_architecture_id"] = 1
    else:
        values[stage] = "malformed"
    provider = PipelineProvider(values)
    result = EvaluationAgent(settings, provider=provider).evaluate(knowledge, strategy)
    assert result.status == "invalid_output"
    assert len(provider.calls) == stage + 1 and not result.rankings


@pytest.mark.parametrize(
    "bad",
    [
        "target",
        "identity",
        "unanswered",
        "duplicate_response",
        "source",
        "quote",
        "duplicates",
        "score",
        "float_score",
    ],
)
def test_semantic_validation(setup, bad):
    settings, knowledge, strategy = setup
    values = responses()
    repair = values[1]["repairs"][0]
    contention = repair["architecture"]["contentions"][0]
    if bad == "target":
        values[0]["critiques"][0]["findings"][0]["contention_number"] = 3
    elif bad == "identity":
        repair["architecture"]["name"] = "Replaced approach"
    elif bad == "unanswered":
        repair["responses"][0]["finding_number"] = 2
    elif bad == "duplicate_response":
        repair["responses"] *= 2
    elif bad == "source":
        contention.update(basis="archive_adaptation", archive_chunk_ids=["invented"])
    elif bad == "quote":
        contention["quotes"] = [{"source_type": "archive", "source_id": "x", "text": "Fake"}]
    elif bad == "duplicates":
        duplicate = copy.deepcopy(repair["architecture"])
        duplicate["name"] = values[1]["repairs"][1]["architecture"]["name"]
        values[1]["repairs"][1]["architecture"] = duplicate
    else:
        values[2]["evaluations"][0]["scores"]["judge_fit"]["points"] = 11 if bad == "score" else 5.5
    provider = PipelineProvider(values)
    result = EvaluationAgent(settings, provider=provider).evaluate(knowledge, strategy)
    assert result.status == "invalid_output" and not result.rankings


def test_input_size_is_checked_before_each_call(setup):
    settings, knowledge, strategy = setup
    settings.strategy.max_input_characters = 1000
    provider = PipelineProvider()
    result = EvaluationAgent(settings, provider=provider).evaluate(knowledge, strategy)
    assert result.status == "invalid_output" and not provider.calls


def test_source_pool_cannot_expand_during_repair(setup):
    settings, knowledge, _ = setup
    add_source(knowledge)
    strategy = StrategyAgent(settings, provider=Provider()).generate(knowledge)
    strategy.supplied_archive_ids = []
    values = responses()
    values[1]["repairs"][0]["architecture"]["contentions"][0].update(
        basis="archive_adaptation", archive_chunk_ids=["archive1"]
    )
    provider = PipelineProvider(values)
    result = EvaluationAgent(settings, provider=provider).evaluate(knowledge, strategy)
    assert provider.calls[0][1]["context"]["archive"] == {}
    assert "PRIVATE/path" not in json.dumps(provider.calls)
    assert result.status == "invalid_output"


@pytest.mark.parametrize("bad", [0, 4, True])
def test_selection_rejects_invalid_ids(setup, bad):
    settings, knowledge, strategy = setup
    result = EvaluationAgent(settings, provider=PipelineProvider()).evaluate(knowledge, strategy)
    with pytest.raises(ValueError):
        select_architecture(result, bad)


def test_cli_evaluates_and_selects_existing_export_without_network(setup, tmp_path, monkeypatch):
    settings, knowledge, strategy = setup
    result = EvaluationAgent(settings, provider=PipelineProvider()).evaluate(knowledge, strategy)
    monkeypatch.setattr(EvaluationAgent, "evaluate", lambda *args: result)
    packet_path, strategy_path, result_path = [
        tmp_path / f"{name}.json" for name in ("p", "s", "r")
    ]
    packet_path.write_text(knowledge.model_dump_json())
    strategy_path.write_text(strategy.model_dump_json())
    runner = CliRunner()
    run = runner.invoke(app, ["evaluate", str(packet_path), str(strategy_path), "--json"])
    assert run.exit_code == 0, run.output
    result_path.write_text(run.output)
    assert EvaluationResult.model_validate_json(run.output).selected_architecture_id is None
    run = runner.invoke(app, ["select", str(result_path), "3"])
    assert run.exit_code == 0
    assert EvaluationResult.model_validate_json(run.output).selected_architecture_id == 3


def test_ui_evaluation_selection_and_invalidation(setup, monkeypatch):
    settings, knowledge, strategy = setup
    result = EvaluationAgent(settings, provider=PipelineProvider()).evaluate(knowledge, strategy)
    calls = []
    monkeypatch.setattr(RoundDirector, "prepare", lambda *args: knowledge)
    monkeypatch.setattr(RoundDirector, "strategize", lambda *args, **kwargs: strategy)

    def evaluate(*args):
        calls.append(1)
        return result

    monkeypatch.setattr(RoundDirector, "evaluate", evaluate)
    page = AppTest.from_file(
        str(Path(__file__).resolve().parents[1] / "ui/pages/1_Round_preparation.py")
    ).run()
    page.text_area(key="motion").set_value("Transit")
    page.button[1].click().run()
    page.button(key="generate_strategies").click().run()
    page.button(key="evaluate_strategies").click().run()
    assert not page.exception
    assert any("92/100" in e.label for e in page.expander)
    assert page.session_state["evaluation_output"].selected_architecture_id is None
    page.selectbox(key="architecture_choice").set_value(3).run()
    next(b for b in page.button if b.label == "Confirm architecture choice").click().run()
    assert page.session_state["evaluation_output"].selected_architecture_id == 3
    assert calls == [1]
    page.button(key="generate_strategies").click().run()
    assert not page.exception
    assert not any("92/100" in e.label for e in page.expander)


@pytest.mark.parametrize("kind", ["value", "fact"])
def test_nonpolicy_rounds_evaluate_without_policy_chain(tmp_path, kind):
    settings = Settings(project_root=tmp_path)
    knowledge = packet(settings, round_type=kind)
    original = output()
    values = responses()
    for architecture in original["architectures"] + [
        r["architecture"] for r in values[1]["repairs"]
    ]:
        architecture["value"] = "Justice" if kind == "value" else None
        architecture["criterion"] = "Equal access" if kind == "value" else None
        for contention in architecture["contentions"]:
            contention.update(uniqueness=None, link=None, internal_link=None)
    strategy = StrategyAgent(settings, provider=Provider(original)).generate(knowledge)
    result = EvaluationAgent(settings, provider=PipelineProvider(values)).evaluate(
        knowledge, strategy
    )
    assert result.status == "completed", result.warnings


def test_size_limit_stops_before_later_provider_call(setup):
    settings, knowledge, strategy = setup
    probe = PipelineProvider()
    EvaluationAgent(settings, provider=probe).evaluate(knowledge, strategy)
    sizes = [len(json.dumps(context, ensure_ascii=False)) for _, context, _ in probe.calls]
    assert sizes[0] < sizes[1] < sizes[2]
    settings.strategy.max_input_characters = sizes[1]
    provider = PipelineProvider()
    result = EvaluationAgent(settings, provider=provider).evaluate(knowledge, strategy)
    assert result.status == "invalid_output" and result.stage == "scoring"
    assert len(provider.calls) == 2 and result.repairs and not result.rankings


def test_repair_preserves_source_and_quote_checks(setup):
    settings, knowledge, _ = setup
    add_source(knowledge, freshness="stale_empirics")
    original = output()
    values = responses()
    for architecture in [original["architectures"][0], values[1]["repairs"][0]["architecture"]]:
        architecture["contentions"][0].update(
            basis="archive_adaptation",
            archive_chunk_ids=["archive1"],
            needs_verification=["Check current evidence."],
            quotes=[
                {"source_type": "archive", "source_id": "archive1", "text": "Exact source excerpt."}
            ],
        )
    strategy = StrategyAgent(settings, provider=Provider(original)).generate(knowledge)
    agent = EvaluationAgent(settings, provider=PipelineProvider(values))
    assert agent.evaluate(knowledge, strategy).status == "completed"
    values[1]["repairs"][0]["architecture"]["contentions"][0]["needs_verification"] = []
    agent = EvaluationAgent(settings, provider=PipelineProvider(values))
    assert agent.evaluate(knowledge, strategy).status == "invalid_output"


def test_imported_totals_cannot_override_actual_rubric(setup):
    settings, knowledge, strategy = setup
    result = EvaluationAgent(settings, provider=PipelineProvider()).evaluate(knowledge, strategy)
    exported = result.model_dump()
    exported["rankings"][0]["total"] = 100
    with pytest.raises(ValueError, match="rubric"):
        EvaluationResult.model_validate(exported)
