"""Milestone 11 permission, provenance, provider, and adaptation integration tests."""

import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError

import pytest
from pydantic import ValidationError
from streamlit.testing.v1 import AppTest
from typer.testing import CliRunner

from debate_engine.agents import RoundDirector
from debate_engine.agents.judge import JudgeAgent
from debate_engine.agents.research import (
    ResearchAgent,
    ResearchProviderError,
    TavilySearchProvider,
    canonical_url,
    research_queries,
)
from debate_engine.config import Settings
from debate_engine.schemas import RetrievalStatistics
from debate_engine.schemas.adaptation import ResearchPacket, ResearchSource
from debate_engine.schemas.rounds import KnowledgePacket, RoundInput
from scripts.prepare_round import app


@pytest.fixture
def settings(tmp_path):
    return Settings(project_root=tmp_path)


@pytest.mark.parametrize(
    "notes,category",
    [
        ("I am a tech judge. No spreading.", "tech"),
        ("I am a flow judge.", "flow"),
        ("Judge: flay", "flay"),
        ("I'm a fully lay judge.", "fully_lay"),
        ("I am not a tech judge.", None),
        ("I prefer clear examples.", None),
        ("Tech. Fully lay.", None),
        (None, None),
    ],
)
def test_judge_labels_are_conservative(notes, category):
    profile = JudgeAgent().analyze(notes)
    assert profile.category == category
    assert profile.original_notes == notes
    assert profile.guidance


def test_explicit_category_wins_and_specific_preferences_survive():
    profile = JudgeAgent().analyze("Judge: tech. No spreading. No theory.", category="fully_lay")
    assert profile.category == "fully_lay"
    assert profile.classification_source == "explicit"
    assert profile.exclude_theory
    assert "No spreading" in profile.preferences
    assert any("conversational" in line for line in profile.guidance)
    assert profile.warnings


def test_judge_applied_before_retrieval_and_user_overrides_win(settings):
    context = RoundInput(
        motion="Conditionality theory", judge_notes="Judge: tech. No theory. No Ks."
    )
    plan = RoundDirector(settings).plan(context)
    assert plan.retrieval_request.judge_category == "tech"
    assert plan.retrieval_request.include_theory is False
    assert plan.retrieval_request.include_kritiks is False
    assert context.include_theory is None
    context.include_theory = True
    override = RoundDirector(settings).plan(context)
    assert override.retrieval_request.include_theory is True
    assert any("overrides" in warning for warning in override.judge_profile.warnings)


class Provider:
    def __init__(self, rows=None, fail=False):
        self.calls = []
        self.rows = [] if rows is None else rows
        self.fail = fail

    def search(self, query, *, max_results):
        self.calls.append(query)
        if self.fail:
            raise RuntimeError("secret-provider-response")
        return self.rows


def online():
    return RoundInput(motion="THW subsidize transit", prep_rules={"internet_allowed": True})


def source(**overrides):
    values = dict(
        title="Transport statistics", url="https://agency.gov/report", content="Original excerpt."
    )
    values.update(overrides)
    return values


def test_offline_never_calls_provider_even_when_key_configured(settings):
    settings.research.api_key = "unused"
    provider = Provider(fail=True)
    packet = ResearchAgent(settings, provider=provider).run(RoundInput(motion="Transit"))
    assert packet.status == "disabled_by_prep_rules"
    assert not provider.calls and not packet.queries and not packet.sources


def test_no_key_reports_configuration_without_provider_construction(settings, monkeypatch):
    def fail(*args):
        raise AssertionError("Provider should not be instantiated")

    monkeypatch.setattr("debate_engine.agents.research.TavilySearchProvider", fail)
    packet = ResearchAgent(settings).run(online())
    assert packet.status == "missing_credentials"
    assert packet.queries_attempted == 0
    assert packet.warnings


def test_queries_never_include_judge_or_archive_text():
    context = online()
    context.judge_notes = "PRIVATE PARADIGM"
    context.explicit_concepts = ["access to employment"]
    queries = research_queries(context, 3)
    assert len(queries) == 3
    assert all("PRIVATE" not in q for q in queries)
    assert any("access to employment" in q for q in queries)
    assert any(str(context.current_year) in q for q in queries)


def test_sources_deduplicate_and_preserve_excerpt_dates_and_provenance(settings):
    provider = Provider(
        [
            source(
                url="https://agency.gov/report?utm_source=test#section", published_date="2024-03-01"
            ),
            source(url="https://agency.gov/report"),
        ]
    )
    packet = ResearchAgent(settings, provider=provider).run(online())
    assert packet.status == "completed"
    assert packet.queries_attempted == 3
    assert len(packet.sources) == 1
    item = packet.sources[0]
    assert item.excerpt == "Original excerpt."
    assert str(item.published_date) == "2024-03-01"
    assert item.retrieved_at.tzinfo is not None
    assert item.verification_status == "unverified_search_excerpt"
    assert any("before the round year" in note for note in item.notes)
    assert ResearchPacket.model_validate_json(packet.model_dump_json()) == packet


def test_failures_are_contained_and_secret_errors_not_exported(settings):
    packet = ResearchAgent(settings, provider=Provider(fail=True)).run(online())
    assert packet.status == "failed"
    assert "secret-provider-response" not in packet.model_dump_json()
    assert packet.queries_completed == 0


def test_partial_empty_and_invalid_responses(settings):
    class Partial(Provider):
        def search(self, query, *, max_results):
            if not self.calls:
                self.calls.append(query)
                raise TimeoutError("timed out")
            return [source(), {"broken": True}, source(url="javascript:alert(1)")]

    packet = ResearchAgent(settings, provider=Partial()).run(online())
    assert packet.status == "partial" and len(packet.sources) == 1
    assert packet.warnings
    assert ResearchAgent(settings, provider=Provider()).run(online()).status == "no_results"


@pytest.mark.parametrize(
    "url", ["javascript:alert(1)", "file:///tmp/a", "https://user:pass@example.org", "bad url"]
)
def test_unsafe_urls_rejected(url):
    with pytest.raises(ValueError):
        canonical_url(url)


def test_budgets_and_missing_dates(settings):
    settings.research.max_queries = 1
    settings.research.results_per_query = 1
    settings.research.max_excerpt_characters = 100
    provider = Provider([source(content="x" * 200), source(url="https://different.org/")])
    packet = ResearchAgent(settings, provider=provider).run(online())
    assert len(provider.calls) == len(packet.sources) == 1
    assert len(packet.sources[0].excerpt) == 100
    assert packet.sources[0].published_date is None
    assert any("date unavailable" in note for note in packet.sources[0].notes)


class Response:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, size):
        return self.body[:size]


def test_tavily_http_contract_and_no_generated_answers(settings, monkeypatch):
    settings = Settings(project_root=settings.project_root, research={"api_key": "test-secret"})
    captured = []

    class Opener:
        def open(self, request, timeout):
            captured.append((request, timeout))
            return Response(json.dumps({"results": [source()]}).encode())

    monkeypatch.setattr("debate_engine.agents.research.build_opener", lambda *args: Opener())
    rows = TavilySearchProvider(settings).search("transit", max_results=4)
    request, timeout = captured[0]
    assert request.full_url == "https://api.tavily.com/search"
    assert request.get_header("Authorization") == "Bearer test-secret"
    payload = json.loads(request.data)
    assert payload["include_answer"] is False
    assert payload["include_raw_content"] is False
    assert payload["max_results"] == 4 and timeout == 10
    assert rows[0]["content"] == "Original excerpt."
    assert "test-secret" not in repr(settings)


@pytest.mark.parametrize("body", [b"bad json", b'{"unexpected": []}', b"x" * 2_000_001])
def test_provider_rejects_bad_or_oversize_responses(settings, monkeypatch, body):
    configured = Settings(project_root=settings.project_root, research={"api_key": "test-secret"})

    class Opener:
        def open(self, *args, **kwargs):
            return Response(body)

    monkeypatch.setattr("debate_engine.agents.research.build_opener", lambda *args: Opener())
    with pytest.raises(ResearchProviderError):
        TavilySearchProvider(configured).search("transit", max_results=4)


def test_http_errors_redacted(settings, monkeypatch):
    configured = Settings(project_root=settings.project_root, research={"api_key": "test-secret"})

    class Opener:
        def open(self, *args, **kwargs):
            raise HTTPError("https://example.org", 401, "test-secret", {}, None)

    monkeypatch.setattr("debate_engine.agents.research.build_opener", lambda *args: Opener())
    with pytest.raises(ResearchProviderError, match="401") as error:
        TavilySearchProvider(configured).search("transit", max_results=4)
    assert "test-secret" not in str(error.value)


def test_round_integration_uses_judge_then_research(settings, monkeypatch):
    observed = []

    def retrieve(self, plan):
        observed.append(plan.retrieval_request.judge_category)
        return KnowledgePacket(plan=plan, statistics=RetrievalStatistics())

    monkeypatch.setattr("debate_engine.agents.knowledge.KnowledgeAgent.retrieve", retrieve)
    provider = Provider([source()])
    context = online()
    context.judge_notes = "I am a flay judge."
    packet = RoundDirector(settings, research_provider=provider).prepare(context)
    assert observed == ["flay"]
    assert packet.research.status == packet.plan.research_status == "completed"
    assert packet.plan.round_input.judge_category is None
    context.prep_rules.internet_allowed = False
    provider.calls.clear()
    packet = RoundDirector(settings, research_provider=provider).prepare(context)
    assert not provider.calls
    assert packet.research.status == "disabled_by_prep_rules"


def test_research_settings_validate_limits(tmp_path):
    with pytest.raises(ValidationError):
        Settings(project_root=tmp_path, research={"max_queries": 100})


def prepared_packet(settings):
    plan = RoundDirector(settings).plan(online())
    research = ResearchPacket(
        status="completed",
        sources=[
            ResearchSource(
                source_id="source",
                title="Agency report",
                url="https://agency.gov/report",
                excerpt="Original research excerpt",
                retrieved_at=datetime.now(UTC),
            )
        ],
    )
    return KnowledgePacket(plan=plan, statistics=RetrievalStatistics(), research=research)


def test_cli_research_in_json_and_text(settings, monkeypatch, tmp_path):
    packet = prepared_packet(settings)
    monkeypatch.setattr(RoundDirector, "prepare", lambda *args, **kwargs: packet)
    source_file = tmp_path / "round.json"
    source_file.write_text(online().model_dump_json())
    result = CliRunner().invoke(app, [str(source_file)])
    assert result.exit_code == 0 and "https://agency.gov/report" in result.output
    result = CliRunner().invoke(app, [str(source_file), "--json"])
    assert KnowledgePacket.model_validate_json(result.output).research == packet.research


def test_ui_research_and_judge_display(settings, monkeypatch):
    packet = prepared_packet(settings)
    monkeypatch.setattr(RoundDirector, "prepare", lambda *args, **kwargs: packet)
    path = Path(__file__).resolve().parents[1] / "ui/pages/1_Round_preparation.py"
    page = AppTest.from_file(str(path)).run()
    page.text_area(key="motion").set_value("Transit")
    page.button[1].click().run()
    assert not page.exception
    assert any(text.value == "Original research excerpt" for text in page.text)
    assert any(header.value == "Judge adaptation" for header in page.subheader)


@pytest.mark.parametrize(
    "notes",
    [
        "I don't agree with judges who say no theory.",
        "No theory unless there is actual abuse.",
        "No Ks except when well explained.",
    ],
)
def test_quoted_or_conditional_preferences_do_not_force_exclusions(notes):
    profile = JudgeAgent().analyze(notes)
    assert not profile.exclude_theory and not profile.exclude_kritiks


@pytest.mark.parametrize("url", [123, "http://localhost/report", "http://127.0.0.1/report"])
def test_non_public_or_non_string_urls_rejected(url):
    with pytest.raises(ValueError):
        canonical_url(url)


def test_unknown_publication_date_is_not_invented(settings):
    packet = ResearchAgent(settings, provider=Provider([source(published_date="invalid")])).run(
        online()
    )
    assert packet.sources[0].published_date is None


def test_plan_preview_never_calls_research_provider(settings):
    provider = Provider(fail=True)
    plan = RoundDirector(settings, research_provider=provider).plan(online())
    assert plan.research_status == "ready"
    assert not provider.calls
