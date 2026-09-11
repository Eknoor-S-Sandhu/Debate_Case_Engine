"""Exercise the real Streamlit form and result rendering without loading BGE."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from debate_engine.config import Settings
from debate_engine.schemas import (
    DebateChunk,
    RetrievalCandidate,
    RetrievalResult,
    RetrievalStatistics,
)

APP = Path(__file__).resolve().parents[1] / "ui" / "app.py"


@pytest.fixture
def tester(tmp_path, monkeypatch):
    database = tmp_path / "debate.db"
    database.touch()
    settings = Settings(project_root=tmp_path)
    settings.storage.database_path = database
    monkeypatch.setattr("debate_engine.config.get_settings", lambda: settings)
    calls = []
    state = {"empty": False, "fail": False}
    chunk = DebateChunk(
        chunk_id="argument",
        document_id="doc",
        source_file="case.md",
        source_path="/archive/case.md",
        text="Public transit connects workers to jobs.",
        chunk_level="argument",
        heading_path=["Employment"],
    )
    child = chunk.model_copy(update={"chunk_id": "child", "text": "Access improves incomes."})

    class FakeRetriever:
        def __init__(self, configured, *, database):
            assert configured is settings
            assert database == settings.storage.database_path

        def retrieve(self, request):
            calls.append(request)
            if state["fail"]:
                raise RuntimeError("Index unavailable")
            candidate = RetrievalCandidate(
                chunk_id="argument",
                chunk=chunk,
                rank=1,
                final_score=0.75,
                parent_argument=chunk,
                related_children=[child],
            )
            return RetrievalResult(
                request=request,
                generated_queries=[],
                full_arguments=[] if state["empty"] else [candidate],
                submodules=[],
                statistics=RetrievalStatistics(),
                warnings=["Semantic search unavailable; lexical results only."],
            )

    monkeypatch.setattr("debate_engine.retrieval.HierarchicalRetriever", FakeRetriever)
    return AppTest.from_file(str(APP)).run(), calls, state, settings


def submit(app, motion="Public transit"):
    app.text_area(key="motion").set_value(motion)
    app.button[0].click().run()
    assert not app.exception


def test_startup_does_not_search(tester):
    app, calls, _, _ = tester
    assert not app.exception
    assert not calls
    assert app.title[0].value == "Debate retrieval tester"


def test_filters_provenance_scores_and_hierarchy(tester):
    app, calls, _, _ = tester
    app.selectbox(key="side").select("aff")
    app.selectbox(key="source").select("personal")
    app.selectbox(key="judge").select("tech")
    app.selectbox(key="theory").select(False)
    app.number_input(key="arguments").set_value(2)
    app.text_area(key="concepts").set_value(" jobs \n wages ")
    submit(app)
    request = calls[0]
    assert request.side.value == "aff"
    assert request.source_group.value == "personal"
    assert request.judge_category.value == "tech"
    assert request.include_theory is False
    assert request.desired_arguments == 2
    assert request.explicit_concepts == ["jobs", "wages"]
    texts = [item.value for item in app.text]
    assert "/archive/case.md" in texts
    assert "Public transit connects workers to jobs." in texts
    assert "Access improves incomes." in texts
    assert any("0.7500" in item.value for item in app.caption)
    assert app.warning
    assert app.json


def test_blank_query_and_zero_counts_do_not_search(tester):
    app, calls, _, _ = tester
    submit(app, "  ")
    assert app.error and not calls
    app.number_input(key="arguments").set_value(0)
    app.number_input(key="modules").set_value(0)
    submit(app)
    assert "at least one" in app.error[0].value
    assert not calls


def test_missing_database_does_not_search(tester):
    app, calls, _, settings = tester
    settings.storage.database_path.unlink()
    submit(app)
    assert "does not exist" in app.error[0].value
    assert not calls
    assert not settings.storage.database_path.exists()


def test_empty_results_and_warnings(tester):
    app, _, state, _ = tester
    state["empty"] = True
    submit(app)
    assert any("No matching material" in info.value for info in app.info)
    assert app.warning


def test_reruns_keep_results_and_failure_clears_them(tester):
    app, calls, state, _ = tester
    submit(app)
    app.run()
    assert len(calls) == 1
    assert any(item.value == "/archive/case.md" for item in app.text)
    state["fail"] = True
    submit(app, "A different motion")
    assert "Index unavailable" in app.error[0].value
    assert not any(item.value == "/archive/case.md" for item in app.text)
