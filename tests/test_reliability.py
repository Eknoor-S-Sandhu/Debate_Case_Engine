"""Milestone 16 failures, usage telemetry, selection identity, and benchmark contracts."""

import json
from urllib.error import HTTPError

import pytest
from typer.testing import CliRunner

from debate_engine.agents.case_writer import CaseWriter
from debate_engine.agents.evaluation import EvaluationAgent, fingerprint
from debate_engine.agents.strategy import StrategyAgent
from debate_engine.schemas.rounds import RoundInput
from scripts.benchmark_v1 import CORPUS, app, run_round
from tests.test_case_writer import CaseProvider, case_output, inputs
from tests.test_evaluation import PipelineProvider, responses
from tests.test_inference_providers import configured, envelope, mock_http
from tests.test_strategy import Provider, output, packet


@pytest.mark.parametrize(
    "http,code",
    [
        (400, "invalid_request"),
        (401, "authentication"),
        (403, "permission"),
        (404, "model_unavailable"),
        (429, "rate_limit_or_quota"),
        (503, "server_error"),
    ],
)
def test_actionable_errors_reach_results(monkeypatch, http, code):
    settings = configured("gemini")
    requests = mock_http(monkeypatch, [HTTPError("https://private", http, "PRIVATE KEY", {}, None)])
    result = StrategyAgent(settings).generate(packet(settings))
    assert result.status == "failed"
    assert result.inference_calls[0].error_code == code
    assert result.inference_calls[0].http_status == http
    assert result.inference_calls[0].stage == "strategy"
    assert len(requests) == 1 and "PRIVATE" not in result.model_dump_json()
    assert any("Check" in w or "check" in w or "Try" in w for w in result.warnings)


@pytest.mark.parametrize("provider", ["openai", "anthropic", "gemini"])
def test_usage_and_elapsed_are_captured(monkeypatch, provider):
    settings = configured(provider)
    body = envelope(provider, output())
    body["usageMetadata" if provider == "gemini" else "usage"] = (
        {"promptTokenCount": 100, "candidatesTokenCount": 200, "totalTokenCount": 350}
        if provider == "gemini"
        else {"input_tokens": 100, "output_tokens": 200, "total_tokens": 300}
    )
    mock_http(monkeypatch, [body])
    result = StrategyAgent(settings).generate(packet(settings))
    call = result.inference_calls[0]
    assert (call.input_tokens, call.output_tokens) == (100, 200)
    assert call.elapsed_seconds >= 0 and call.status == "received"


def test_schema_failure_is_distinct_from_provider_failure(monkeypatch):
    settings = configured("gemini")
    bad = output()
    bad["architectures"].pop()
    mock_http(monkeypatch, [envelope("gemini", bad)])
    result = StrategyAgent(settings).generate(packet(settings))
    assert result.inference_calls[0].status == "invalid_output"
    assert result.inference_calls[0].error_code == "validation"


def test_legacy_fingerprint_omits_new_empty_telemetry():
    import hashlib

    from debate_engine.schemas.strategy import StrategyResult

    old = StrategyResult(status="not_configured", packet_fingerprint="p").model_dump(
        exclude={"inference_calls", "provider"}
    )
    encoded = json.dumps(old, separators=(",", ":"), ensure_ascii=False)
    restored = StrategyResult.model_validate_json(encoded)
    assert fingerprint(restored) == hashlib.sha256(encoded.encode()).hexdigest()


@pytest.mark.parametrize("preserve_selection", [True, False])
@pytest.mark.parametrize("scenario", json.loads(CORPUS.read_text()), ids=lambda s: s["id"])
def test_representative_round_contracts(tmp_path, scenario, preserve_selection):
    settings, knowledge, _, _ = inputs(tmp_path, kind=scenario["round_type"], side=scenario["side"])
    original = output()
    repairs = responses()
    if scenario["round_type"] != "policy":
        for a in original["architectures"] + [r["architecture"] for r in repairs[1]["repairs"]]:
            a["value"] = "Justice" if scenario["round_type"] == "value" else None
            a["criterion"] = "Equal access" if scenario["round_type"] == "value" else None
            for c in a["contentions"]:
                c.update(uniqueness=None, link=None, internal_link=None)

    class Director:
        def prepare(self, context):
            assert isinstance(context, RoundInput)
            return knowledge

        def strategize(self, p):
            return StrategyAgent(settings, provider=Provider(original)).generate(p)

        def evaluate(self, p, s):
            return EvaluationAgent(settings, provider=PipelineProvider(repairs)).evaluate(p, s)

        def write_case(self, p, s, e):
            final = case_output(scenario["round_type"])
            for contention, selected in zip(
                final["contentions"], s.architectures[0].contentions, strict=True
            ):
                contention["title"] = selected.title
            result = CaseWriter(settings, provider=CaseProvider([final, final])).write(p, s, e)
            if not preserve_selection:
                result.case.contentions[0].title = "Unexpected replacement"
            return result

    row = run_round(Director(), scenario)
    assert row["status"] == ("completed" if preserve_selection else "invalid_output"), row
    assert row["selection_preserved"] is preserve_selection
    assert row["request_count"] == 6
    assert row["quality_review"] == "pending_human_review"


def test_benchmark_dry_run_never_loads_settings(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "scripts.benchmark_v1.Settings", lambda: pytest.fail("No live setup in dry run")
    )
    result = CliRunner().invoke(app, ["--output", str(tmp_path / "unused")])
    assert result.exit_code == 0 and "12 rounds" in result.output
    assert not (tmp_path / "unused").exists()


@pytest.mark.parametrize(
    "failure",
    json.loads(
        (CORPUS.parents[2] / "tests/fixtures/inference/gemini_live_errors.json").read_text()
    ),
)
def test_live_discovered_errors_remain_actionable(monkeypatch, failure):
    import io

    settings = configured("gemini")
    error = HTTPError(
        "https://generativelanguage.googleapis.com",
        failure["http_status"],
        failure["message"],
        {},
        io.BytesIO(json.dumps({"error": failure}).encode()),
    )
    mock_http(monkeypatch, [error])
    result = StrategyAgent(settings).generate(packet(settings))
    assert result.inference_calls[0].error_code == failure["expected_category"]
    assert failure["message"] not in result.model_dump_json()
