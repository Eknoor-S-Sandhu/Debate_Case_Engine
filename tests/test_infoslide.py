"""Infoslides travel as context without changing historical serialization."""

from debate_engine.agents import RoundDirector
from debate_engine.agents.strategy import build_context
from debate_engine.schemas.rounds import RoundInput
from tests.test_case_writer import inputs


def test_infoslide_reaches_retrieval_and_model_context(tmp_path):
    settings, packet, _, _ = inputs(tmp_path)
    context = packet.plan.round_input.model_copy(
        update={"infoslide": "The region of Lydora has geothermal district heating."}
    )
    context.prep_rules.internet_allowed = False
    plan = RoundDirector(settings).plan(context)
    assert plan.round_input.motion == context.motion
    assert plan.retrieval_request.infoslide == context.infoslide
    assert any("lydora" in q.text.lower() for q in plan.generated_queries)
    packet.plan = plan
    model_context, _ = build_context(packet, settings, "")
    assert model_context["round"]["infoslide"] == context.infoslide
    assert not plan.research_permitted


def test_legacy_round_serialization_omits_missing_infoslide():
    old = RoundInput(motion="THW make public transport free", side="aff")
    dumped = old.model_dump(mode="json")
    assert "infoslide" not in dumped
    assert RoundInput.model_validate(dumped).model_dump(mode="json") == dumped
    assert old.side == "aff"  # Saved formats keep their historical vocabulary.
