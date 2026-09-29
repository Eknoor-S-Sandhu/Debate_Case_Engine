"""Construction metadata provenance, legacy bytes, and generation boundaries."""

import copy
import json

import pytest

from debate_engine.agents.strategy import StrategyAgent
from debate_engine.config import Settings
from debate_engine.schemas.strategy import ArchitectureSet
from tests.test_strategy import Provider, output, packet


def construction():
    return {
        "status_quo_barrier": "Existing fare payments strain essential spending.",
        "proposed_change": "Remove fares for existing journeys.",
        "causal_routes": [{
            "explanation": "Avoided recurring payments leave money for unmet necessities.",
            "warrant_numbers": [1], "archive_chunk_ids": [], "research_source_ids": [],
            "assumptions": ["Households have unmet necessities."],
            "dependencies": ["Financing does not offset savings."],
        }],
        "terminal_outcomes": [{
            "consequence": "Fewer skipped meals.", "problem_population": None,
            "reachable_population": None, "attributable_change": None,
            "severity": "Relief of hunger", "duration": None,
            "evidence_gaps": ["Number of affected households and net savings."],
        }],
        "shared_dependencies": ["Sustainable financing"],
        "surviving_ballot_argument": "Relief survives no mode shift; scale unresolved.",
    }


def test_legacy_nested_json_bytes_unchanged():
    raw = output()
    expected = json.dumps(raw, ensure_ascii=False, separators=(",", ":"))
    assert ArchitectureSet.model_validate(raw).model_dump_json() == expected
    raw["architectures"][0]["contentions"][0]["construction"] = None
    assert ArchitectureSet.model_validate(raw).model_dump_json() == expected


@pytest.mark.parametrize("field,value", [
    ("warrant_numbers", [2]), ("warrant_numbers", [1, 1]),
    ("archive_chunk_ids", ["invented"]), ("research_source_ids", ["invented"]),
])
def test_bad_construction_references_rejected(field, value):
    raw = output()
    c = raw["architectures"][0]["contentions"][0]
    c["construction"] = construction()
    c["construction"]["causal_routes"][0][field] = value
    with pytest.raises(ValueError):
        ArchitectureSet.model_validate(raw)


@pytest.mark.parametrize("kind", ["policy", "value", "fact"])
def test_one_call_generation_with_construction(tmp_path, kind):
    raw = output()
    for a in raw["architectures"]:
        if kind == "value":
            a.update(value="Welfare", criterion="Reduce harm")
        for c in a["contentions"]:
            c["construction"] = copy.deepcopy(construction())
            if kind != "policy":
                c.update(uniqueness=None, link=None, internal_link=None)
                c["construction"]["status_quo_barrier"] = None
    settings = Settings(project_root=tmp_path)
    provider = Provider(raw)
    r = StrategyAgent(settings, provider=provider).generate(packet(settings, round_type=kind))
    assert r.status == "completed", r.warnings
    assert r.prompt_version == "construction-v1-strategy"
    assert len(provider.calls) == 1
    assert all(c.construction for a in r.architectures for c in a.contentions)
    assert "ONE-BASED" in provider.calls[0][0]
    assert "construction" in provider.calls[0][2]["$defs"]["Contention"]["properties"]


def test_legacy_provider_output_warns_without_blocking(tmp_path):
    settings = Settings(project_root=tmp_path)
    r = StrategyAgent(settings, provider=Provider()).generate(packet(settings))
    assert r.status == "completed"
    assert any("Construction analysis is missing" in w for w in r.warnings)


def test_nypdl_rejects_off_motion_metadata(tmp_path):
    settings = Settings(project_root=tmp_path)
    knowledge = packet(settings, internet=False)
    knowledge.plan.round_input.prep_rules.cloud_inference_allowed = True
    raw = output()
    c = raw["architectures"][0]["contentions"][0]
    c["construction"] = construction()
    c["construction"]["surviving_ballot_argument"] = "Vote for us regardless of the motion."
    provider = Provider(raw)
    r = StrategyAgent(settings, provider=provider).generate(knowledge)
    assert r.status == "invalid_output"
