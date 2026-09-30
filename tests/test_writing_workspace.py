"""Writing workspace lifecycle without live research or inference."""

import time

import pytest

from debate_engine.agents import RoundDirector
from debate_engine.schemas.case import CaseResult
from tests.test_case_writer import CaseProvider, inputs
from ui.server import Workspace


def wait(workspace):
    deadline = time.monotonic() + 5
    while workspace.job["status"] == "running" and time.monotonic() < deadline:
        time.sleep(0.01)
    assert workspace.job["status"] != "running"


def test_round_reuse_and_invalidation(tmp_path):
    settings, packet, strategy, evaluation = inputs(tmp_path)
    workspace = Workspace(settings)
    workspace.action("round", packet.plan.round_input.model_dump(mode="json"))
    workspace.outputs = {"packet": packet, "strategy": strategy, "evaluation": evaluation}
    workspace.action("timer", {})
    started = workspace.started
    workspace.action("round", packet.plan.round_input.model_dump(mode="json"))
    assert workspace.outputs["strategy"] == strategy
    assert workspace.started == started
    updated = packet.plan.round_input.model_dump(mode="json")
    updated["motion"] = "Different motion"
    workspace.action("round", updated)
    assert workspace.outputs == {} and workspace.started is None


def test_background_writing_and_historical_load(tmp_path, monkeypatch):
    settings, packet, strategy, evaluation = inputs(tmp_path)
    workspace = Workspace(settings)
    workspace.round = packet.plan.round_input
    workspace.outputs = {"packet": packet, "strategy": strategy, "evaluation": evaluation}
    original = RoundDirector.write_case
    calls = []

    def write(self, *args, **kwargs):
        calls.append(1)
        return original(self, *args, provider=CaseProvider(), **kwargs)

    monkeypatch.setattr(RoundDirector, "write_case", write)
    workspace.action("write", {})
    wait(workspace)
    assert workspace.outputs["case"].status == "completed"
    directory = workspace.run_dir
    before = {p.name: p.read_bytes() for p in directory.glob("*.json")}
    workspace.action("select", {"id": 1})
    assert "case" not in workspace.outputs
    assert directory != workspace.run_dir
    assert before == {p.name: p.read_bytes() for p in directory.glob("*.json")}
    workspace.action("load", {"name": directory.name})
    assert isinstance(workspace.outputs["case"], CaseResult)
    assert workspace.outputs["evaluation"].selected_architecture_id == 2
    assert calls == [1]


def test_permissions_busy_and_path_boundaries(tmp_path):
    settings, packet, strategy, evaluation = inputs(tmp_path)
    workspace = Workspace(settings)
    with pytest.raises(ValueError):
        workspace.action("load", {"name": "../../.env"})
    workspace.round = packet.plan.round_input.model_copy(deep=True)
    workspace.round.prep_rules.cloud_inference_allowed = False
    workspace.outputs = {"packet": packet, "strategy": strategy, "evaluation": evaluation}
    with pytest.raises(ValueError):
        workspace.action("write", {})
    workspace.job = {"status": "running"}
    with pytest.raises(ValueError):
        workspace.action("select", {"id": 1})


def test_failed_request_retains_previous_work(tmp_path, monkeypatch):
    settings, packet, strategy, _ = inputs(tmp_path)
    workspace = Workspace(settings)
    workspace.round = packet.plan.round_input
    workspace.outputs = {"packet": packet, "strategy": strategy}

    def fail(*args, **kwargs):
        raise RuntimeError("secret diagnostic")

    monkeypatch.setattr(RoundDirector, "evaluate", fail)
    workspace.action("evaluate", {})
    wait(workspace)
    assert workspace.outputs["strategy"] == strategy
    assert "secret" not in workspace.notice
    assert workspace.job["status"] == "failed"


def test_invalid_budget_keeps_accepted_case(tmp_path):
    settings, packet, strategy, evaluation = inputs(tmp_path)
    workspace = Workspace(settings)
    workspace.round = packet.plan.round_input
    workspace.outputs = {"packet": packet, "strategy": strategy, "evaluation": evaluation}
    with pytest.raises(ValueError):
        workspace.action("write", {"budget": {"words_per_minute": 0}})
    assert workspace.outputs["evaluation"] == evaluation
