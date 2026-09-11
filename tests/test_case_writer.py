"""Case writing structure, provenance, timing, CLI and UI integration."""

import copy
import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest
from typer.testing import CliRunner

from debate_engine.agents import RoundDirector
from debate_engine.agents.case_writer import CaseWriter, count_words, render_case
from debate_engine.agents.evaluation import EvaluationAgent, select_architecture
from debate_engine.agents.strategy import StrategyAgent
from debate_engine.config import Settings
from debate_engine.schemas import Side
from debate_engine.schemas.case import CaseResult, SpeechBudget
from scripts.write_case import app
from tests.test_evaluation import PipelineProvider, responses
from tests.test_strategy import Provider, add_source, output, packet


def inputs(tmp_path, *, kind="policy", side="gov", source=False):
    settings = Settings(project_root=tmp_path)
    knowledge = packet(settings, round_type=kind)
    knowledge.plan.retrieval_request.side = Side(side)
    knowledge.plan.round_input.side = Side(side)
    # Round models permit assignment; revalidate enum values before generating.
    knowledge = type(knowledge).model_validate_json(knowledge.model_dump_json())
    if source:
        add_source(knowledge, freshness="stale_empirics")
    original = output()
    values = responses()
    if kind != "policy":
        for a in original["architectures"] + [r["architecture"] for r in values[1]["repairs"]]:
            a["value"] = "Justice" if kind == "value" else None
            a["criterion"] = "Equal access" if kind == "value" else None
            for c in a["contentions"]:
                c.update(uniqueness=None, link=None, internal_link=None)
    strategy = StrategyAgent(settings, provider=Provider(original)).generate(knowledge)
    evaluation = EvaluationAgent(settings, provider=PipelineProvider(values)).evaluate(
        knowledge, strategy
    )
    return settings, knowledge, strategy, select_architecture(evaluation, 2)


def point(text="Clear causal reasoning supports this argument."):
    return dict(
        tagline="Mechanism", text=text, archive_chunk_ids=[], research_source_ids=[], quotes=[]
    )


def case_output(kind="policy", *, long=False):
    contentions = []
    for title in ("pollution", "exercise"):
        contentions.append(
            dict(
                title=title,
                claim="Transit changes health outcomes.",
                uniqueness=[point() for _ in range(3)] if kind == "policy" else [],
                links=[point() for _ in range(2)] if kind == "policy" else [],
                internal_links=[point()] if kind == "policy" else [],
                warrants=[point() for _ in range(3)] if kind != "policy" else [],
                impacts=[point()],
                preempts=[point()],
            )
        )
    if long:
        for c in contentions:
            for points in (c["uniqueness"], c["links"], c["internal_links"], c["impacts"]):
                for p in points:
                    p["text"] = "word " * 160
    return dict(
        weighing_mechanism="Compare expected harms."
        if kind != "fact"
        else "Preponderance of evidence.",
        value="Justice" if kind == "value" else None,
        criterion="Equal access" if kind == "value" else None,
        observations=[point()],
        definitions=[],
        inherency=[],
        solvency=[],
        plan=dict(
            action="Fund transit.",
            actor="Local government",
            enforcement_actor="Transit agency",
            funding="Budget reallocation",
            timeframe="Next budget",
            enforcement="Public audits",
        )
        if kind == "policy"
        else None,
        contentions=contentions,
        assumptions=["Service delivery must improve."],
        needs_verification=[],
    )


class CaseProvider:
    def __init__(self, values=None, fail_at=None):
        self.values = values if values is not None else [case_output(), case_output()]
        self.calls = []
        self.fail_at = fail_at

    def generate(self, instructions, context, schema):
        i = len(self.calls)
        self.calls.append((instructions, json.loads(context), schema))
        if i == self.fail_at:
            raise RuntimeError("PRIVATE provider secret")
        return copy.deepcopy(self.values[i])


@pytest.mark.parametrize(
    "side,minutes,limit", [("gov", 7, 975), ("aff", 7, 975), ("neg", 8, 1125), ("opp", 8, 1125)]
)
def test_case_uses_user_choice_correct_budget_and_two_passes(tmp_path, side, minutes, limit):
    settings, knowledge, strategy, evaluation = inputs(tmp_path, side=side)
    before = [v.model_dump_json() for v in (knowledge, strategy, evaluation)]
    provider = CaseProvider()
    result = RoundDirector(settings).write_case(knowledge, strategy, evaluation, provider=provider)
    assert result.status == "completed", result.warnings
    assert result.selected_architecture_id == 2 and result.selected_strategy_score == 84
    assert result.speech_minutes == minutes and result.word_limit == limit
    assert result.word_count == count_words(render_case(result.case, knowledge))
    assert result.word_count <= limit
    assert len(provider.calls) == 2
    assert "Stage: DRAFT" in provider.calls[0][0]
    assert "FINAL IMPROVEMENT" in provider.calls[1][0]
    assert provider.calls[0][1]["selected_architecture"]["architecture_id"] == 2
    assert "case" in provider.calls[1][1]
    assert "**UQ:**" in result.markdown and "1. **Mechanism:**" in result.markdown
    assert [v.model_dump_json() for v in (knowledge, strategy, evaluation)] == before
    assert CaseResult.model_validate_json(result.model_dump_json()) == result
    for _, _, schema in provider.calls:
        for node in [schema, *schema["$defs"].values()]:
            if node.get("type") == "object":
                assert set(node["required"]) == set(node["properties"])
                assert node["additionalProperties"] is False


@pytest.mark.parametrize("kind", ["value", "fact"])
def test_exact_nonpolicy_format(tmp_path, kind):
    settings, knowledge, strategy, evaluation = inputs(tmp_path, kind=kind)
    result = CaseWriter(settings, provider=CaseProvider([case_output(kind)] * 2)).write(
        knowledge, strategy, evaluation
    )
    assert result.status == "completed", result.warnings
    for forbidden in ("**Inherency", "**Plan text", "AoA:", "**Solvency", "**UQ"):
        assert forbidden not in result.markdown
    assert "**Warrants:**" in result.markdown
    assert ("**Value Criterion**" if kind == "value" else "Threshold of Truth") in result.markdown


def test_overlong_draft_trims_then_improves(tmp_path):
    settings, knowledge, strategy, evaluation = inputs(tmp_path)
    provider = CaseProvider([case_output(long=True), case_output(), case_output()])
    result = CaseWriter(settings, provider=provider).write(knowledge, strategy, evaluation)
    assert result.status == "completed"
    assert len(provider.calls) == 3
    assert "Stage: TRIM" in provider.calls[1][0]
    assert provider.calls[1][1]["measured_word_count"] > result.word_limit


def test_overlong_final_is_not_published(tmp_path):
    settings, knowledge, strategy, evaluation = inputs(tmp_path)
    provider = CaseProvider([case_output(), case_output(long=True)])
    result = CaseWriter(settings, provider=provider).write(knowledge, strategy, evaluation)
    assert result.status == "over_budget"
    assert result.case is None and result.markdown is None
    assert len(provider.calls) == 2


@pytest.mark.parametrize("mutation", ["offline", "no_choice", "packet", "strategy", "incomplete"])
def test_invalid_input_never_calls_provider(tmp_path, mutation):
    settings, knowledge, strategy, evaluation = inputs(tmp_path)
    if mutation == "offline":
        knowledge.plan.round_input.prep_rules.internet_allowed = False
    elif mutation == "no_choice":
        evaluation.selected_architecture_id = None
    elif mutation == "packet":
        knowledge.plan.round_input.motion = "Different motion"
    elif mutation == "strategy":
        strategy.warnings.append("Changed export")
    else:
        evaluation.status = "failed"
    provider = CaseProvider()
    result = CaseWriter(settings, provider=provider).write(knowledge, strategy, evaluation)
    assert result.status != "completed" and not provider.calls


@pytest.mark.parametrize("stage", [0, 1, 2])
def test_provider_failure_stops_without_leaking_draft_or_secrets(tmp_path, stage):
    settings, knowledge, strategy, evaluation = inputs(tmp_path)
    provider = CaseProvider([case_output(long=True), case_output(), case_output()], fail_at=stage)
    result = CaseWriter(settings, provider=provider).write(knowledge, strategy, evaluation)
    assert result.status == "failed"
    assert len(provider.calls) == stage + 1
    assert result.markdown is None and result.case is None
    assert "PRIVATE" not in result.model_dump_json()


@pytest.mark.parametrize("mutation", ["source", "quote", "title", "count", "plan", "uq", "extra"])
def test_invalid_final_fails_structure_and_source_checks(tmp_path, mutation):
    settings, knowledge, strategy, evaluation = inputs(tmp_path)
    final = case_output()
    if mutation == "source":
        final["contentions"][0]["impacts"][0]["archive_chunk_ids"] = ["made_up"]
    elif mutation == "quote":
        final["contentions"][0]["impacts"][0]["quotes"] = [
            dict(source_type="archive", source_id="made_up", text="Invented quote")
        ]
    elif mutation == "title":
        final["contentions"][0]["title"] = "Unselected argument"
    elif mutation == "count":
        final["contentions"].pop()
    elif mutation == "plan":
        final["plan"] = None
    elif mutation == "uq":
        final["contentions"][0]["uniqueness"] = []
    else:
        final["improvement_report"] = "Not requested"
    provider = CaseProvider([case_output(), final])
    result = CaseWriter(settings, provider=provider).write(knowledge, strategy, evaluation)
    assert result.status == "invalid_output" and result.markdown is None


def test_sources_render_and_stale_verification_is_required(tmp_path):
    settings, knowledge, strategy, evaluation = inputs(tmp_path, source=True)
    case = case_output()
    p = case["contentions"][0]["impacts"][0]
    p.update(
        text="Exact source excerpt.",
        archive_chunk_ids=["archive1"],
        quotes=[dict(source_type="archive", source_id="archive1", text="Exact source excerpt.")],
    )
    result = CaseWriter(settings, provider=CaseProvider([case] * 2)).write(
        knowledge, strategy, evaluation
    )
    assert result.status == "invalid_output"
    case["needs_verification"] = ["Verify current evidence."]
    provider = CaseProvider([case] * 2)
    result = CaseWriter(settings, provider=provider).write(knowledge, strategy, evaluation)
    assert result.status == "completed"
    assert "Archive archive1: private.md" in result.markdown
    assert "PRIVATE/path" not in json.dumps(provider.calls)


def test_missing_configuration_and_input_limit(tmp_path):
    settings, knowledge, strategy, evaluation = inputs(tmp_path)
    assert CaseWriter(settings).write(knowledge, strategy, evaluation).status == "not_configured"
    settings.strategy.max_input_characters = 1000
    provider = CaseProvider()
    assert (
        CaseWriter(settings, provider=provider).write(knowledge, strategy, evaluation).status
        == "invalid_output"
    )
    assert not provider.calls


def test_cli_json_and_failure_exit(tmp_path, monkeypatch):
    settings, knowledge, strategy, evaluation = inputs(tmp_path)
    result = CaseWriter(settings, provider=CaseProvider()).write(knowledge, strategy, evaluation)
    monkeypatch.setattr(CaseWriter, "write", lambda *args, **kwargs: result)
    paths = []
    for name, value in zip(
        ("packet", "strategy", "evaluation"), (knowledge, strategy, evaluation), strict=True
    ):
        path = tmp_path / f"{name}.json"
        path.write_text(value.model_dump_json())
        paths.append(str(path))
    run = CliRunner().invoke(app, [*paths, "--json"])
    assert run.exit_code == 0, run.output
    assert CaseResult.model_validate_json(run.output).status == "completed"
    result.status = "over_budget"
    result.case = None
    result.markdown = None
    run = CliRunner().invoke(app, [*paths, "--json"])
    assert run.exit_code == 1


def test_ui_writes_once_and_clears_on_new_selection(tmp_path, monkeypatch):
    settings, knowledge, strategy, evaluation = inputs(tmp_path)
    result = CaseWriter(settings, provider=CaseProvider()).write(knowledge, strategy, evaluation)
    calls = []
    monkeypatch.setattr(RoundDirector, "prepare", lambda *args: knowledge)
    monkeypatch.setattr(RoundDirector, "strategize", lambda *args, **kwargs: strategy)
    monkeypatch.setattr(RoundDirector, "evaluate", lambda *args: evaluation)

    def write(*args, **kwargs):
        calls.append(1)
        return result

    monkeypatch.setattr(RoundDirector, "write_case", write)
    page = AppTest.from_file(
        str(Path(__file__).resolve().parents[1] / "ui/pages/1_Round_preparation.py")
    ).run()
    page.text_area(key="motion").set_value("Transit")
    page.button[1].click().run()
    page.button(key="generate_strategies").click().run()
    page.button(key="evaluate_strategies").click().run()
    page.button(key="write_case").click().run()
    assert not page.exception
    assert any("**UQ:**" in m.value for m in page.markdown)
    page.number_input(key="case_wpm").set_value(160).run()
    assert calls == [1]
    page.selectbox(key="architecture_choice").set_value(3).run()
    next(b for b in page.button if b.label == "Confirm architecture choice").click().run()
    assert not any("**UQ:**" in m.value for m in page.markdown)


def test_budget_validation():
    with pytest.raises(ValueError):
        SpeechBudget(words_per_minute=0)
    with pytest.raises(ValueError):
        SpeechBudget(reserve_seconds=121)
