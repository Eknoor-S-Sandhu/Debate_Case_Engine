"""Writer handoffs preserve mapped routes and review context through optional trim.

Scripted outputs test transport/validation, not live semantic model quality.
"""

import copy

import pytest

from debate_engine.agents.case_writer import CaseWriter, count_words, render_case
from debate_engine.schemas.case import CaseDocument
from debate_engine.schemas.evaluation import EvaluationResult
from tests.test_case_writer import CaseProvider, case_output, inputs
from tests.test_construction import construction


@pytest.mark.parametrize("trim", [False, True])
def test_construction_and_critique_survive_all_writer_stages(tmp_path, trim):
    settings, knowledge, strategy, evaluation = inputs(tmp_path, source=True)
    raw = evaluation.model_dump()
    selected = next(r for r in raw["repairs"] if r["architecture_id"] == 2)
    c = selected["architecture"]["contentions"][0]
    c["construction"] = construction()
    c["construction"]["proposed_change"] = "Reduce pollution exposure through displaced driving."
    c["construction"]["causal_routes"][0]["explanation"] = (
        "Displaced driving reduces exposure; illness reduction requires exposure evidence."
    )
    c["construction"]["terminal_outcomes"][0]["consequence"] = "Fewer respiratory illnesses."
    evaluation = EvaluationResult.model_validate(raw)
    before = [x.model_dump_json() for x in (knowledge, strategy, evaluation)]
    final = case_output()
    final["weighing_mechanism"] = "Net Benefits"
    final["observations"] = []
    final["needs_verification"] = ["Verify exposure change and number of people reached."]
    final["contentions"][0]["internal_links"][0]["text"] = (
        "Displaced driving reduces exposure; illness reduction requires exposure evidence."
    )
    final["contentions"][0]["impacts"][0].update(
        text="Exact source excerpt.", archive_chunk_ids=["archive1"],
        quotes=[dict(source_type="archive", source_id="archive1", text="Exact source excerpt.")],
    )
    values = [copy.deepcopy(final), copy.deepcopy(final)]
    if trim:
        long = copy.deepcopy(final)
        for point in long["contentions"][1]["uniqueness"]:
            point["text"] = "word " * 400
        values.insert(0, long)
    provider = CaseProvider(values)
    result = CaseWriter(settings, provider=provider).write(knowledge, strategy, evaluation)
    assert result.status == "completed", result.warnings
    assert result.prompt_version == "construction-v1-writer"
    assert len(provider.calls) == (3 if trim else 2)
    for instructions, data, _ in provider.calls:
        assert data["selected_architecture"] == selected
        assert data["selected_critique"]["architecture_id"] == 2
        assert "missing effect size is different from a missing mechanism" in instructions
        assert "Preempts must defend" in instructions
    for i in range(1, len(provider.calls)):
        assert provider.calls[i][1]["case"] == CaseDocument.model_validate(
            values[i - 1]
        ).model_dump(mode="json")
    speech = render_case(result.case, knowledge)
    assert "**Weighing Mechanism**: Net Benefits" in speech
    assert "**UQ:**" in speech and "**IMPX:**" in speech
    assert "construction" not in speech and "Preparation notes" not in speech
    assert final["needs_verification"][0] in result.markdown
    assert "Archive archive1" in result.markdown
    assert result.word_count == count_words(speech) <= result.word_limit
    assert [x.model_dump_json() for x in (knowledge, strategy, evaluation)] == before
