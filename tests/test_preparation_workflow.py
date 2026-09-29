"""UI session reuse, visible invalidation, and explicit timer start."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

from debate_engine.agents import RoundDirector
from debate_engine.config import Settings
from tests.test_strategy import packet
from ui.workflow import invalidate, remaining_seconds

APP = Path(__file__).resolve().parents[1] / "ui/pages/1_Round_preparation.py"


def test_timer_is_explicit_and_clamped():
    state = {}
    assert remaining_seconds(state, 15, now=10) is None
    state["prep_started"] = 10
    assert remaining_seconds(state, 15, now=70) == 840
    assert remaining_seconds(state, 15, now=950) == 0
    state["round_output"] = object()
    invalidate(state, "round_output")
    assert remaining_seconds(state, 15, now=70) is None


def test_same_round_reuses_packet_and_changed_round_invalidates(tmp_path, monkeypatch):
    settings = Settings(project_root=tmp_path)
    knowledge = packet(settings)
    calls = []

    def prepare(*args):
        calls.append(1)
        return knowledge

    monkeypatch.setattr(RoundDirector, "prepare", prepare)
    page = AppTest.from_file(str(APP)).run()
    assert [tab.label for tab in page.tabs] == [
        "1 · Round setup",
        "2 · Sources",
        "3 · Strategies",
        "4 · Final case",
    ]
    page.text_area(key="motion").set_value("Transit")
    page.button[1].click().run()
    page.button[1].click().run()
    assert calls == [1]
    assert not page.exception
    assert any("Reused" in item.value for item in page.info)
    page.text_area(key="motion").set_value("Different motion")
    page.button[0].click().run()
    assert calls == [1]
    assert any("cleared" in item.value for item in page.info)
    assert page.session_state["round_output"].round_input.motion == "Different motion"


def test_timer_start_needs_side_confirmation_and_persists(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "debate_engine.config.get_settings", lambda: Settings(project_root=tmp_path)
    )
    page = AppTest.from_file(str(APP)).run()
    page.text_area(key="motion").set_value("THW make transit free")
    page.button[0].click().run()
    assert page.button(key="start_prep").disabled
    assert "prep_started" not in page.session_state.filtered_state
    page.selectbox(key="side").set_value("gov")
    page.button[0].click().run()
    assert not page.button(key="start_prep").disabled
    assert "prep_started" not in page.session_state.filtered_state
    page.button(key="start_prep").click().run()
    started = page.session_state["prep_started"]
    page.run()
    assert page.session_state["prep_started"] == started
    page.button[0].click().run()
    assert page.session_state["prep_started"] == started
    page.selectbox(key="side").set_value("opp")
    page.button[0].click().run()
    assert "prep_started" not in page.session_state.filtered_state


def test_checkpoint_matches_packet_by_fingerprint_and_rejects_tampering(tmp_path):
    import json

    import pytest

    from debate_engine.agents.strategy import StrategyAgent
    from tests.test_strategy import Provider
    from ui.workflow import load_checkpoint

    settings = Settings(project_root=tmp_path)
    knowledge = packet(settings)
    strategy = StrategyAgent(settings, provider=Provider()).generate(knowledge)
    (tmp_path / "packet-reviewed.json").write_text(knowledge.model_dump_json())
    (tmp_path / "strategy.json").write_text(strategy.model_dump_json())
    restored = load_checkpoint(tmp_path)
    assert restored["round_output"] == knowledge
    assert restored["strategy_output"] == strategy
    assert "case_output" not in restored
    raw = json.loads((tmp_path / "packet-reviewed.json").read_text())
    raw["plan"]["round_input"]["motion"] = "Tampered motion"
    (tmp_path / "packet-reviewed.json").write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="fingerprint"):
        load_checkpoint(tmp_path)


def test_checkpoint_loads_latest_resumed_evaluation(tmp_path):
    from debate_engine.agents.evaluation import EvaluationAgent
    from debate_engine.agents.strategy import StrategyAgent
    from tests.test_evaluation import PipelineProvider, responses
    from tests.test_strategy import Provider
    from ui.workflow import load_checkpoint

    settings = Settings(project_root=tmp_path)
    knowledge = packet(settings)
    strategy = StrategyAgent(settings, provider=Provider()).generate(knowledge)
    failed = EvaluationAgent(settings, provider=PipelineProvider(fail_at=2)).evaluate(
        knowledge, strategy
    )
    recovered = EvaluationAgent(settings, provider=PipelineProvider([responses()[2]])).evaluate(
        knowledge, strategy, checkpoint=failed
    )
    (tmp_path / "packet.json").write_text(knowledge.model_dump_json())
    (tmp_path / "strategy.json").write_text(strategy.model_dump_json())
    (tmp_path / "evaluation.json").write_text(failed.model_dump_json())
    (tmp_path / "evaluation-resumed-01.json").write_text(recovered.model_dump_json())
    assert load_checkpoint(tmp_path)["evaluation_output"].status == "completed"
    assert load_checkpoint(tmp_path)["evaluation_output"].selected_architecture_id is None
