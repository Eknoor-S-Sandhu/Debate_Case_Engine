"""Codex process boundary, login, failure handling and pipeline contracts."""

import json
import sys
from pathlib import Path

import pytest

from debate_engine.agents.case_writer import CaseWriter
from debate_engine.agents.codex_cli_provider import CodexCLIProvider
from debate_engine.agents.evaluation import EvaluationAgent, select_architecture
from debate_engine.agents.strategy import StrategyAgent
from debate_engine.agents.strategy_provider import (
    StrategyProviderError,
    create_provider,
    inference_ready,
)
from debate_engine.config import ProviderName, Settings
from tests.test_case_writer import case_output, inputs
from tests.test_evaluation import responses
from tests.test_strategy import output, packet


@pytest.fixture
def fake_cli(tmp_path):
    """Real child process with a deterministic CLI protocol; never calls a model."""
    path = tmp_path / "codex test"
    control = tmp_path / "control.json"
    capture = tmp_path / "capture.json"
    control.write_text(json.dumps({"answer": {"status": "ok"}}))
    path.write_text(f"""#!{sys.executable}
import json, os, sys, time
from pathlib import Path
control = Path({str(control)!r})
config = json.loads(control.read_text())
if sys.argv[1:3] == ["login", "status"]:
    print(config.get("login", "Logged in using ChatGPT"), file=sys.stderr)
    sys.exit(config.get("login_exit", 0))
prompt = sys.stdin.read()
record = {{"args":sys.argv, "env":dict(os.environ), "cwd":os.getcwd(), "prompt":prompt}}
Path({str(capture)!r}).write_text(json.dumps(record))
time.sleep(config.get("sleep", 0))
if "queue" in config:
    answer = config["queue"].pop(0)
    control.write_text(json.dumps(config))
else:
    answer = config.get("answer", {{"status":"ok"}})
if not config.get("missing_answer"):
    destination = Path(sys.argv[sys.argv.index("--output-last-message")+1])
    destination.write_text(config.get("raw", json.dumps(answer)))
event = {{"type":"turn.completed", "usage":{{"input_tokens":12, "output_tokens":4}}}}
print(config.get("events", json.dumps(event)))
print(config.get("stderr", ""), file=sys.stderr)
sys.exit(config.get("exit", 0))
""")
    path.chmod(0o700)
    settings = Settings(
        _env_file=None,
        strategy={"provider": "codex_cli", "allow_remote": True},
        codex_cli={"executable": str(path)},
    )
    return settings, control, capture


def test_default_and_legacy_selection():
    assert Settings(_env_file=None).strategy.provider == ProviderName.CODEX_CLI
    assert (
        Settings(_env_file=None, strategy={"api_key": "old", "model": "old"}).strategy.provider
        == ProviderName.OPENAI
    )
    s = Settings(
        _env_file=None, strategy={"provider": "codex_cli", "api_key": "old", "model": "old"}
    )
    assert isinstance(create_provider(s), CodexCLIProvider)
    assert s.codex_cli.model is None


def test_process_boundary_and_cleanup(fake_cli, monkeypatch):
    s, _, capture = fake_cli
    monkeypatch.setenv("OPENAI_API_KEY", "never-forward")
    monkeypatch.setenv("DEBATE_ENGINE_GEMINI__API_KEY", "never-forward")
    monkeypatch.setenv("CODEX_API_KEY", "never-forward")
    monkeypatch.setenv("CODEX_THREAD_ID", "do-not-inherit")
    s.codex_cli.model = "chosen-model"
    p = create_provider(s)
    assert inference_ready(s)
    assert p.generate("instruction", '{"motion":"public"}', {}) == {"status": "ok"}
    recorded = json.loads(capture.read_text())
    assert "never-forward" not in json.dumps(recorded)
    assert "CODEX_THREAD_ID" not in recorded["env"]
    assert "public" in recorded["prompt"] and "public" not in str(recorded["args"])
    assert recorded["args"][-1] == "-"
    assert "chosen-model" in recorded["args"]
    assert "read-only" in recorded["args"] and "--ignore-user-config" in recorded["args"]
    assert 'forced_login_method="chatgpt"' in recorded["args"]
    assert not Path(recorded["cwd"]).exists()
    assert p.last_usage == {"input_tokens": 12, "output_tokens": 4}


@pytest.mark.parametrize(
    "changes,code",
    [
        ({"login": "Logged in using an API key"}, "cli_login"),
        ({"login_exit": 1}, "cli_login"),
        ({"raw": "not JSON"}, "malformed"),
        ({"answer": []}, "malformed"),
        ({"missing_answer": True}, "malformed"),
        ({"events": "not JSON"}, "malformed"),
        ({"events": json.dumps({"type": "turn.started"})}, "incomplete"),
        ({"exit": 1, "stderr": "You've hit your usage limit PRIVATE"}, "rate_limit_or_quota"),
        (
            {
                "events": json.dumps(
                    {"type": "turn.failed", "error": {"message": "usage_limit PRIVATE"}}
                )
            },
            "rate_limit_or_quota",
        ),
        ({"exit": 2, "stderr": "unexpected argument PRIVATE"}, "cli_incompatible"),
        ({"raw": "x" * 2_000_001}, "malformed"),
    ],
)
def test_failures_do_not_leak_or_accept_partial_output(fake_cli, changes, code):
    s, control, _ = fake_cli
    control.write_text(json.dumps(changes))
    p = create_provider(s)
    with pytest.raises(StrategyProviderError) as failure:
        p.generate("instructions", "{}", {})
    assert failure.value.code == code
    assert "PRIVATE" not in str(failure.value)


def test_timeout_cleans_up(fake_cli):
    s, control, capture = fake_cli
    control.write_text(json.dumps({"sleep": 5}))
    s.codex_cli.timeout_seconds = 0.2
    with pytest.raises(StrategyProviderError) as failure:
        create_provider(s).generate("instructions", "{}", {})
    assert failure.value.code == "timeout"
    assert not Path(json.loads(capture.read_text())["cwd"]).exists()


def test_missing_executable_and_disabled_remote(fake_cli):
    s, _, capture = fake_cli
    s.codex_cli.executable = "/nonexistent/debate-codex"
    assert not inference_ready(s)
    with pytest.raises(StrategyProviderError) as failure:
        create_provider(s).generate("instructions", "{}", {})
    assert failure.value.code == "cli_missing"
    s.codex_cli.allow_remote = False
    with pytest.raises(StrategyProviderError) as failure:
        create_provider(s).generate("instructions", "{}", {})
    assert failure.value.code == "permission"
    assert not capture.exists()


def test_offline_round_never_launches_cli(fake_cli):
    s, _, capture = fake_cli
    assert StrategyAgent(s).generate(packet(s, internet=False)).status == "disabled_by_prep_rules"
    assert not capture.exists()


def test_full_pipeline_and_invalid_output(fake_cli, tmp_path):
    s, control, _ = fake_cli
    _, knowledge, _, _ = inputs(tmp_path)
    final = case_output()
    for contention, chosen in zip(
        final["contentions"], output()["architectures"][0]["contentions"], strict=True
    ):
        contention["title"] = chosen["title"]
    queue = [output(), *responses(), final, final]
    control.write_text(json.dumps({"queue": queue}))
    strategy = StrategyAgent(s).generate(knowledge)
    assert strategy.status == "completed"
    evaluation = EvaluationAgent(s).evaluate(knowledge, strategy)
    assert evaluation.status == "completed"
    selected = select_architecture(evaluation, 1)
    case = CaseWriter(s).write(knowledge, strategy, selected)
    assert case.status == "completed", case.warnings
    for result in [strategy, evaluation, case]:
        assert result.provider == "codex_cli"
        assert result.inference_calls
    assert case.selected_architecture_id == 1
    control.write_text(json.dumps({"answer": {}}))
    rejected = StrategyAgent(s).generate(knowledge)
    assert rejected.status == "invalid_output"
    assert rejected.inference_calls[0].error_code == "validation"
