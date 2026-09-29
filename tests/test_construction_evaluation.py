"""Construction evaluation contracts and warning behavior, without live inference."""

import json
from pathlib import Path

from streamlit.testing.v1 import AppTest

from debate_engine.agents import RoundDirector
from debate_engine.agents.evaluation import EvaluationAgent, select_architecture
from debate_engine.agents.strategy import StrategyAgent
from debate_engine.config import Settings
from debate_engine.schemas.evaluation import Finding
from tests.test_evaluation import PipelineProvider, responses
from tests.test_strategy import Provider, packet
from ui.workflow import unresolved_findings


def test_legacy_finding_serialization_and_strict_schema():
    raw = responses()[0]["critiques"][0]["findings"][0]
    assert Finding.model_validate(raw).model_dump_json() == json.dumps(raw, separators=(",", ":"))
    schema = Finding.model_json_schema()
    assert set(schema["required"]) == set(schema["properties"])


def evaluated(tmp_path):
    settings = Settings(project_root=tmp_path)
    knowledge = packet(settings)
    strategy = StrategyAgent(settings, provider=Provider()).generate(knowledge)
    values = responses()
    for c in values[0]["critiques"]:
        c["findings"][0]["gap_kind"] = "central_mechanism"
    provider = PipelineProvider(values)
    result = EvaluationAgent(settings, provider=provider).evaluate(knowledge, strategy)
    return knowledge, strategy, result, provider


def test_evaluation_contract_and_warning_join(tmp_path):
    _, _, result, provider = evaluated(tmp_path)
    assert result.status == "completed"
    assert result.prompt_version == "construction-v1-evaluation"
    assert len(provider.calls) == 3
    assert "exact missing connection" in provider.calls[0][0]
    assert "cannot mark a missing causal premise addressed" in provider.calls[1][0]
    assert "sound qualitative warrants" in provider.calls[2][0]
    result.critiques.reverse()
    result.repairs.reverse()
    finding, response = unresolved_findings(result, 1)[0]
    assert finding.gap_kind == "central_mechanism"
    assert response.status == "partially_addressed"
    assert select_architecture(result, 1).selected_architecture_id == 1
    response.status = "addressed"
    assert unresolved_findings(result, 1) == []
    response.status = "unresolved"
    finding.gap_kind = "numerical_precision"
    assert unresolved_findings(result, 1)[0][0].gap_kind == "numerical_precision"
    finding.severity = "low"
    assert unresolved_findings(result, 1) == []


def test_ui_risks_do_not_block_selection_or_reruns(tmp_path, monkeypatch):
    knowledge, strategy, result, _ = evaluated(tmp_path)
    monkeypatch.setattr(RoundDirector, "prepare", lambda *args: knowledge)
    monkeypatch.setattr(RoundDirector, "strategize", lambda *args, **kwargs: strategy)
    calls = []

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
    assert any("central mechanism" in w.value for w in page.warning)
    page.selectbox(key="architecture_choice").set_value(1).run()
    next(b for b in page.button if b.label == "Confirm architecture choice").click().run()
    page.run()
    assert not page.exception
    assert page.session_state["evaluation_output"].selected_architecture_id == 1
    assert calls == [1]
