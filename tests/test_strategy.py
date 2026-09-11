"""Milestone 12 generation contracts, source checks, and provider boundaries."""

import copy
import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest
from typer.testing import CliRunner

from debate_engine.agents import RoundDirector
from debate_engine.agents.strategy import StrategyAgent, build_context
from debate_engine.agents.strategy_provider import OpenAIStrategyProvider, StrategyProviderError
from debate_engine.config import Settings
from debate_engine.schemas import DebateChunk, RetrievalCandidate, RetrievalStatistics
from debate_engine.schemas.rounds import KnowledgeItem, KnowledgePacket, RoundInput
from debate_engine.schemas.strategy import ArchitectureSet, StrategyResult
from scripts.generate_strategies import app


@pytest.fixture
def settings(tmp_path):
    return Settings(project_root=tmp_path)


def packet(settings, *, internet=True, round_type="policy"):
    plan = RoundDirector(settings).plan(
        RoundInput(
            motion="THW subsidize public transit",
            side="gov",
            round_type=round_type,
            judge_category="flow",
            prep_rules={"internet_allowed": internet},
        )
    )
    return KnowledgePacket(plan=plan, statistics=RetrievalStatistics())


def output():
    architectures = []
    themes = [
        (
            "Mobility",
            "employment access wages businesses productivity",
            "affordability fares household poverty opportunity",
        ),
        (
            "Health",
            "pollution asthma respiratory disease hospital prevention",
            "exercise walking activity cardiovascular fitness longevity",
        ),
        (
            "Resilience",
            "oil dependency fuel imports volatility energy independence",
            "emergency evacuation redundancy disasters transport security",
        ),
    ]
    for name, first, second in themes:
        contentions = []
        for theme in [first, second]:
            contentions.append(
                dict(
                    title=theme.split()[0],
                    argument_style="substantive",
                    claim=f"Improve {theme}",
                    uniqueness=f"Current barriers affect {theme}",
                    link=f"Transit changes {theme}",
                    internal_link=f"Reliable service supports {theme}",
                    warrants=[f"Mechanism: {theme}"],
                    impacts=[f"Protect {theme}"],
                    preempts=[f"Compare tradeoffs for {theme}"],
                    basis="new_reasoning",
                    archive_chunk_ids=[],
                    research_source_ids=[],
                    quotes=[],
                    assumptions=[f"Assumes expansion affects {theme}"],
                    needs_verification=[],
                )
            )
        architectures.append(
            dict(
                name=name,
                framing=f"Prioritize {first}",
                value=None,
                criterion=None,
                core_mechanism=first,
                route_to_ballot=second,
                differs_from_others=f"Focus on {first}",
                contentions=contentions,
                judge_adaptation="Clear warrants and comparative weighing.",
                why_this_can_win=f"Independent offense from {first}",
                main_vulnerability="Service must improve.",
            )
        )
    return {"architectures": architectures}


class Provider:
    def __init__(self, value=None, fail=False):
        self.value = output() if value is None else value
        self.fail = fail
        self.calls = []

    def generate(self, instructions, context, schema):
        self.calls.append((instructions, json.loads(context), schema))
        if self.fail:
            raise RuntimeError("PRIVATE API KEY")
        return self.value


def test_three_architectures_are_validated_and_unranked(settings):
    provider = Provider()
    result = StrategyAgent(settings, provider=provider).generate(packet(settings))
    assert result.status == "completed", result.warnings
    assert len(result.architectures) == 3 and len(provider.calls) == 1
    assert StrategyResult.model_validate_json(result.model_dump_json()) == result
    assert "rank" not in result.architectures[0].model_dump()
    assert "Do not rank" in provider.calls[0][0]


def test_offline_blocks_even_injected_provider(settings):
    provider = Provider(fail=True)
    result = StrategyAgent(settings, provider=provider).generate(packet(settings, internet=False))
    assert result.status == "disabled_by_prep_rules" and not provider.calls


def test_configuration_missing_does_not_call_network(settings, monkeypatch):
    def fail(*args):
        raise AssertionError("Network provider should not be constructed")

    monkeypatch.setattr("debate_engine.agents.strategy.OpenAIStrategyProvider", fail)
    assert StrategyAgent(settings).generate(packet(settings)).status == "not_configured"


@pytest.mark.parametrize("count", [0, 1, 2, 4])
def test_exactly_three_required(settings, count):
    value = output()
    value["architectures"] = (value["architectures"] * 2)[:count]
    result = StrategyAgent(settings, provider=Provider(value)).generate(packet(settings))
    assert result.status == "invalid_output" and not result.architectures


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate",
        "no_chain",
        "one_contention",
        "no_preempt",
        "extra_field",
        "unknown_source",
        "no_assumptions",
        "theory",
    ],
)
def test_invalid_output_never_becomes_success(settings, mutation):
    value = output()
    first = value["architectures"][0]
    contention = first["contentions"][0]
    if mutation == "duplicate":
        value["architectures"][1] = copy.deepcopy(first)
        value["architectures"][1]["name"] = "Cosmetic rename"
    elif mutation == "no_chain":
        contention["internal_link"] = None
    elif mutation == "one_contention":
        first["contentions"] = [contention]
    elif mutation == "no_preempt":
        contention["preempts"] = []
    elif mutation == "extra_field":
        first["strategy_score"] = 100
    elif mutation == "unknown_source":
        contention["archive_chunk_ids"] = ["invented"]
        contention["basis"] = "archive_adaptation"
    elif mutation == "no_assumptions":
        contention["assumptions"] = []
    elif mutation == "theory":
        contention["argument_style"] = "theory"
    result = StrategyAgent(settings, provider=Provider(value)).generate(packet(settings))
    assert result.status == "invalid_output", mutation
    assert not result.architectures


def add_source(knowledge, *, text="Exact source excerpt.", **metadata):
    chunk = DebateChunk(
        chunk_id="archive1",
        document_id="doc",
        source_file="private.md",
        source_path="/PRIVATE/path/private.md",
        text=text,
        section_type="impact",
        source_group="personal",
        **metadata,
    )
    knowledge.items[chunk.chunk_id] = KnowledgeItem(
        candidate=RetrievalCandidate(chunk_id=chunk.chunk_id, chunk=chunk),
        category="impacts",
    )


def test_quotes_sources_and_prompt_privacy(settings):
    knowledge = packet(settings)
    add_source(knowledge)
    value = output()
    contention = value["architectures"][0]["contentions"][0]
    contention.update(
        basis="archive_adaptation",
        archive_chunk_ids=["archive1"],
        quotes=[
            {"source_type": "archive", "source_id": "archive1", "text": "Exact source excerpt."}
        ],
    )
    provider = Provider(value)
    original = knowledge.model_dump_json()
    result = StrategyAgent(settings, provider=provider).generate(
        knowledge, preferences="Prioritize clarity"
    )
    assert result.status == "completed"
    assert result.supplied_archive_ids == ["archive1"]
    assert "PRIVATE/path" not in json.dumps(provider.calls[0][1])
    assert knowledge.model_dump_json() == original
    contention["quotes"][0]["text"] = "Invented quote"
    assert (
        StrategyAgent(settings, provider=Provider(value)).generate(knowledge).status
        == "invalid_output"
    )


def test_excerpt_limits_prevent_citing_unseen_text(settings):
    settings.strategy.excerpt_characters = 100
    knowledge = packet(settings)
    add_source(knowledge, text="x" * 101 + "Unseen quote")
    value = output()
    c = value["architectures"][0]["contentions"][0]
    c.update(
        basis="archive_adaptation",
        archive_chunk_ids=["archive1"],
        quotes=[{"source_type": "archive", "source_id": "archive1", "text": "Unseen quote"}],
    )
    result = StrategyAgent(settings, provider=Provider(value)).generate(knowledge)
    assert result.status == "invalid_output"


def test_eligibility_is_rechecked(settings):
    knowledge = packet(settings)
    add_source(knowledge, document_type="theory")
    context, warnings = build_context(knowledge, settings, "")
    assert not context["archive"] and warnings


def test_verification_notes_must_carry_forward(settings):
    knowledge = packet(settings)
    add_source(knowledge)
    knowledge.items["archive1"].verification_notes = ["Stale empirics"]
    value = output()
    c = value["architectures"][0]["contentions"][0]
    c.update(basis="archive_adaptation", archive_chunk_ids=["archive1"])
    assert (
        StrategyAgent(settings, provider=Provider(value)).generate(knowledge).status
        == "invalid_output"
    )
    c["needs_verification"] = ["Update empirics"]
    assert (
        StrategyAgent(settings, provider=Provider(value)).generate(knowledge).status == "completed"
    )


@pytest.mark.parametrize("kind", ["value", "fact"])
def test_value_fact_do_not_require_policy_chain(settings, kind):
    value = output()
    for architecture in value["architectures"]:
        architecture["value"] = "Justice" if kind == "value" else None
        architecture["criterion"] = "Equal access" if kind == "value" else None
        for c in architecture["contentions"]:
            c.update(uniqueness=None, link=None, internal_link=None)
    result = StrategyAgent(settings, provider=Provider(value)).generate(
        packet(settings, round_type=kind)
    )
    assert result.status == "completed", result.warnings


def test_failed_provider_is_redacted_and_not_retried(settings):
    provider = Provider(fail=True)
    result = StrategyAgent(settings, provider=provider).generate(packet(settings))
    assert result.status == "failed" and len(provider.calls) == 1
    assert "PRIVATE API KEY" not in result.model_dump_json()


def test_input_limits_do_not_call_provider(settings):
    provider = Provider()
    result = StrategyAgent(settings, provider=provider).generate(
        packet(settings), preferences="x" * 3001
    )
    assert result.status == "invalid_output" and not provider.calls


class Response:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, size):
        return self.body[:size]


def configured(settings):
    return Settings(
        project_root=settings.project_root,
        strategy={
            "allow_remote": True,
            "api_key": "test-secret",
            "model": "configured-test-model",
        },
    )


def test_provider_request_contract(settings, monkeypatch):
    requests = []
    response = {
        "status": "completed",
        "output": [
            {"type": "message", "content": [{"type": "output_text", "text": json.dumps(output())}]}
        ],
    }

    class Opener:
        def open(self, request, timeout):
            requests.append(request)
            return Response(json.dumps(response).encode())

    monkeypatch.setattr(
        "debate_engine.agents.strategy_provider.build_opener", lambda *args: Opener()
    )
    result = OpenAIStrategyProvider(configured(settings)).generate(
        "instructions", "context", ArchitectureSet.model_json_schema()
    )
    assert result == output()
    request = requests[0]
    body = json.loads(request.data)
    assert request.full_url == "https://api.openai.com/v1/responses"
    assert request.get_header("Authorization") == "Bearer test-secret"
    assert body["store"] is False and "tools" not in body
    assert body["text"]["format"]["strict"] is True
    assert body["model"] == "configured-test-model"
    schema = body["text"]["format"]["schema"]
    for node in [schema, *schema["$defs"].values()]:
        if node.get("type") == "object":
            assert set(node["required"]) == set(node["properties"])
            assert node["additionalProperties"] is False


@pytest.mark.parametrize(
    "response",
    [
        {"status": "incomplete", "output": []},
        {"status": "completed", "output": []},
        {"status": "completed", "output": [{"type": "message", "content": [{"type": "refusal"}]}]},
        {
            "status": "completed",
            "output": [
                {"type": "message", "content": [{"type": "output_text", "text": "bad json"}]}
            ],
        },
    ],
)
def test_provider_rejects_incomplete_refused_and_malformed(settings, monkeypatch, response):
    class Opener:
        def open(self, *args, **kwargs):
            return Response(json.dumps(response).encode())

    monkeypatch.setattr(
        "debate_engine.agents.strategy_provider.build_opener", lambda *args: Opener()
    )
    with pytest.raises(StrategyProviderError):
        OpenAIStrategyProvider(configured(settings)).generate("instructions", "context", {})


def test_cli_exports_three_architectures(settings, tmp_path, monkeypatch):
    knowledge = packet(settings)
    result = StrategyAgent(settings, provider=Provider()).generate(knowledge)
    monkeypatch.setattr(StrategyAgent, "generate", lambda *args, **kwargs: result)
    path = tmp_path / "packet.json"
    path.write_text(knowledge.model_dump_json())
    run = CliRunner().invoke(app, [str(path), "--json"])
    assert run.exit_code == 0
    assert len(StrategyResult.model_validate_json(run.output).architectures) == 3
    run = CliRunner().invoke(app, [str(path)])
    assert "ARCHITECTURE 3" in run.output


def test_ui_generation_does_not_repeat_preparation(settings, monkeypatch):
    knowledge = packet(settings)
    calls = []

    def prepare(*args, **kwargs):
        calls.append(1)
        return knowledge

    monkeypatch.setattr(RoundDirector, "prepare", prepare)
    result = StrategyAgent(settings, provider=Provider()).generate(knowledge)
    monkeypatch.setattr(RoundDirector, "strategize", lambda *args, **kwargs: result)
    page = AppTest.from_file(
        str(Path(__file__).resolve().parents[1] / "ui/pages/1_Round_preparation.py")
    ).run()
    page.text_area(key="motion").set_value("Transit")
    page.button[1].click().run()
    page.button(key="generate_strategies").click().run()
    assert not page.exception
    assert calls == [1]
    assert any("Architecture 3" in expander.label for expander in page.expander)
    page.text_area(key="motion").set_value("Different motion")
    page.button[0].click().run()
    assert not any("Architecture 3" in expander.label for expander in page.expander)
