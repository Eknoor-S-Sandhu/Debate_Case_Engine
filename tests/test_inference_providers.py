"""Provider contracts and complete workflows without credentials or network access."""

import copy
import hashlib
import json
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest
from streamlit.testing.v1 import AppTest
from typer.testing import CliRunner

from debate_engine.agents.case_writer import CaseWriter
from debate_engine.agents.evaluation import EvaluationAgent, fingerprint, select_architecture
from debate_engine.agents.strategy import StrategyAgent
from debate_engine.agents.strategy_provider import (
    StrategyProviderError,
    anthropic_schema,
    create_provider,
    inference_ready,
    provider_settings,
)
from debate_engine.config import ProviderName, Settings
from debate_engine.schemas.strategy import ArchitectureSet, StrategyResult
from scripts.generate_strategies import app
from tests.test_case_writer import case_output
from tests.test_evaluation import responses
from tests.test_strategy import Response, output, packet

PROVIDERS = ["openai", "anthropic", "gemini"]


def configured(name):
    return Settings(
        strategy={"provider": name, "allow_remote": True},
        **{p: {"api_key": f"{p}-secret", "model": f"{p}-test-model"} for p in PROVIDERS},
    )


def envelope(name, value):
    text = json.dumps(value)
    return {
        "openai": {
            "status": "completed",
            "output": [{"type": "message", "content": [{"type": "output_text", "text": text}]}],
        },
        "anthropic": {"stop_reason": "end_turn", "content": [{"type": "text", "text": text}]},
        "gemini": {
            "candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": text}]}}]
        },
    }[name]


def mock_http(monkeypatch, bodies):
    requests = []

    class Opener:
        def open(self, request, timeout):
            i = len(requests)
            requests.append(request)
            value = bodies[i]
            if isinstance(value, Exception):
                raise value
            return Response(value if isinstance(value, bytes) else json.dumps(value).encode())

    monkeypatch.setattr(
        "debate_engine.agents.strategy_provider.build_opener", lambda *args: Opener()
    )
    return requests


@pytest.mark.parametrize("name", PROVIDERS)
def test_provider_request_and_credential_isolation(monkeypatch, name):
    settings = configured(name)
    requests = mock_http(monkeypatch, [envelope(name, output())])
    original = ArchitectureSet.model_json_schema()
    snapshot = copy.deepcopy(original)
    result = create_provider(settings).generate("instructions", "context", original)
    assert result == output() and original == snapshot and len(requests) == 1
    request = requests[0]
    body = json.loads(request.data)
    combined = str(request.headers) + request.data.decode() + request.full_url
    assert f"{name}-secret" in str(request.headers)
    assert "secret" not in request.full_url and "secret" not in request.data.decode()
    for other in set(PROVIDERS) - {name}:
        assert f"{other}-secret" not in combined
    assert "tools" not in body
    if name == "openai":
        assert request.full_url == "https://api.openai.com/v1/responses"
        assert body["store"] is False
        assert body["text"]["format"]["schema"] == original
    elif name == "anthropic":
        assert request.full_url == "https://api.anthropic.com/v1/messages"
        assert request.get_header("Anthropic-version") == "2023-06-01"
        assert body["output_config"]["format"]["schema"] == anthropic_schema(original)
        assert body["system"] == "instructions"
    else:
        assert request.full_url.endswith("/gemini-test-model:generateContent")
        assert body["generationConfig"]["responseJsonSchema"] == anthropic_schema(original)
        assert body["systemInstruction"]["parts"][0]["text"] == "instructions"


@pytest.mark.parametrize("name", PROVIDERS)
def test_full_native_pipeline(monkeypatch, name):
    settings = configured(name)
    values = [output(), *responses(), case_output(), case_output()]
    requests = mock_http(monkeypatch, [envelope(name, value) for value in values])
    knowledge = packet(settings)
    strategy = StrategyAgent(settings).generate(knowledge)
    assert strategy.status == "completed", strategy.warnings
    evaluation = EvaluationAgent(settings).evaluate(knowledge, strategy)
    assert evaluation.status == "completed", evaluation.warnings
    selected = select_architecture(evaluation, 2)
    result = CaseWriter(settings).write(knowledge, strategy, selected)
    assert result.status == "completed", result.warnings
    assert len(requests) == 6
    for stage in (strategy, evaluation, result):
        assert stage.provider == name and stage.model == f"{name}-test-model"
        assert "secret" not in stage.model_dump_json()


def test_explicit_cross_provider_workflow(monkeypatch):
    settings = configured("openai")
    values = [
        envelope("openai", output()),
        *[envelope("anthropic", v) for v in responses()],
        envelope("gemini", case_output()),
        envelope("gemini", case_output()),
    ]
    requests = mock_http(monkeypatch, values)
    knowledge = packet(settings)
    strategy = StrategyAgent(settings).generate(knowledge)
    settings.strategy.provider = ProviderName.ANTHROPIC
    evaluation = EvaluationAgent(settings).evaluate(knowledge, strategy)
    settings.strategy.provider = ProviderName.GEMINI
    result = CaseWriter(settings).write(knowledge, strategy, select_architecture(evaluation, 2))
    assert result.status == "completed", result.warnings
    assert len(requests) == 6 and result.provider == "gemini"


@pytest.mark.parametrize("name", PROVIDERS)
@pytest.mark.parametrize("bad", ["truncated", "refused", "missing", "malformed", "not_object"])
def test_bad_responses_rejected_without_fallback(monkeypatch, name, bad):
    value = envelope(name, output())
    if bad == "truncated":
        if name == "openai":
            value["status"] = "incomplete"
        elif name == "anthropic":
            value["stop_reason"] = "max_tokens"
        else:
            value["candidates"][0]["finishReason"] = "MAX_TOKENS"
    elif bad == "refused":
        if name == "openai":
            value["output"][0]["content"] = [{"type": "refusal"}]
        elif name == "anthropic":
            value["stop_reason"] = "refusal"
        else:
            value["promptFeedback"] = {"blockReason": "SAFETY"}
    elif bad == "missing":
        value = {}
    elif bad == "malformed":
        value = b"not json"
    else:
        value = envelope(name, ["unexpected"])
    requests = mock_http(monkeypatch, [value])
    with pytest.raises(StrategyProviderError):
        create_provider(configured(name)).generate("instructions", "context", {})
    assert len(requests) == 1


@pytest.mark.parametrize("name", PROVIDERS)
@pytest.mark.parametrize(
    "error",
    [
        HTTPError("https://private", 401, "SECRET", {}, None),
        URLError("SECRET"),
        TimeoutError("SECRET"),
    ],
)
def test_transport_errors_are_redacted_and_not_retried(monkeypatch, name, error):
    requests = mock_http(monkeypatch, [error])
    with pytest.raises(StrategyProviderError) as caught:
        create_provider(configured(name)).generate("instructions", "context", {})
    assert "SECRET" not in str(caught.value) and len(requests) == 1


@pytest.mark.parametrize("name", PROVIDERS)
def test_oversized_response_rejected(monkeypatch, name):
    requests = mock_http(monkeypatch, [b" " * 2_000_001])
    with pytest.raises(StrategyProviderError, match="size"):
        create_provider(configured(name)).generate("instructions", "context", {})
    assert len(requests) == 1


@pytest.mark.parametrize("name", PROVIDERS)
def test_offline_or_missing_key_makes_no_request(monkeypatch, name):
    requests = mock_http(monkeypatch, [])
    settings = configured(name)
    offline = packet(settings, internet=False)
    assert StrategyAgent(settings).generate(offline).status == "disabled_by_prep_rules"
    getattr(settings, name).api_key = None
    assert not inference_ready(settings)
    assert StrategyAgent(settings).generate(packet(settings)).status == "not_configured"
    assert requests == []


def test_legacy_openai_config_and_explicit_provider_precedence():
    settings = Settings(
        strategy={"api_key": "legacy", "model": "legacy-model", "allow_remote": True}
    )
    assert inference_ready(settings)
    assert provider_settings(settings).model == "legacy-model"
    settings.openai.model = "new-model"
    assert provider_settings(settings).model == "new-model"
    settings.openai.allow_remote = False
    assert not inference_ready(settings)
    settings.strategy.provider = ProviderName.GEMINI
    assert not inference_ready(settings)
    assert provider_settings(settings).api_key is None
    settings.gemini.api_key = "gemini-secret"
    settings.gemini.model = "gemini-model"
    settings.strategy.allow_remote = False
    settings.gemini.allow_remote = True
    assert inference_ready(settings)


def test_env_loads_distinct_credentials_without_exposing_them(tmp_path):
    path = tmp_path / ".env"
    path.write_text(
        "DEBATE_ENGINE_STRATEGY__PROVIDER=gemini\n"
        "DEBATE_ENGINE_GEMINI__ALLOW_REMOTE=true\n"
        "DEBATE_ENGINE_GEMINI__API_KEY=private-test-key\n"
        "DEBATE_ENGINE_GEMINI__MODEL=test-model\n"
    )
    settings = Settings(_env_file=path)
    assert inference_ready(settings)
    assert "private-test-key" not in settings.model_dump_json()
    assert settings.openai.api_key is None


def test_anthropic_schema_constraints_still_enforced_by_agent(monkeypatch):
    settings = configured("anthropic")
    bad = output()
    bad["architectures"].pop()
    mock_http(monkeypatch, [envelope("anthropic", bad)])
    assert StrategyAgent(settings).generate(packet(settings)).status == "invalid_output"
    schema = anthropic_schema(ArchitectureSet.model_json_schema())
    assert "minItems" not in schema["properties"]["architectures"]
    assert "minItems=3" in schema["properties"]["architectures"]["description"]


def test_old_exports_keep_fingerprints(monkeypatch):
    settings = configured("openai")
    knowledge = packet(settings)
    mock_http(monkeypatch, [envelope("openai", output())])
    strategy = StrategyAgent(settings).generate(knowledge)
    old = strategy.model_dump()
    old.pop("provider")
    old_json = json.dumps(old, ensure_ascii=False, separators=(",", ":"))
    restored = StrategyResult.model_validate_json(old_json)
    assert restored.provider is None
    assert fingerprint(restored) == hashlib.sha256(old_json.encode()).hexdigest()


def test_cli_provider_override(monkeypatch, tmp_path):
    settings = configured("openai")
    monkeypatch.setattr("scripts.generate_strategies.get_settings", lambda: settings)
    requests = mock_http(monkeypatch, [envelope("gemini", output())])
    path = tmp_path / "packet.json"
    path.write_text(packet(settings).model_dump_json())
    run = CliRunner().invoke(app, [str(path), "--provider", "gemini", "--json"])
    assert run.exit_code == 0, run.output
    assert StrategyResult.model_validate_json(run.output).provider == "gemini"
    assert len(requests) == 1
    assert settings.strategy.provider == "openai"


def test_ui_switch_is_explicit_and_does_not_call_network(monkeypatch):
    requests = mock_http(monkeypatch, [])
    page = AppTest.from_file(
        str(Path(__file__).resolve().parents[1] / "ui/pages/1_Round_preparation.py")
    ).run()
    page.selectbox(key="inference_provider").set_value(ProviderName.GEMINI).run()
    assert not page.exception and not requests
    assert any("gemini" in c.value for c in page.caption)
