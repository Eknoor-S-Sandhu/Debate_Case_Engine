"""Eligibility, hierarchy, freshness, and diversity scoring tests."""

from __future__ import annotations

import pytest

from debate_engine.config import Settings
from debate_engine.retrieval import (
    CandidateSignals,
    candidate_is_eligible,
    diversify_candidates,
    infer_query_intents,
    score_candidate,
)
from debate_engine.schemas import (
    ChunkLevel,
    DebateChunk,
    DocumentType,
    Freshness,
    JudgeCategory,
    RetrievalRequest,
    SourceGroup,
)


def make_chunk(chunk_id: str, **overrides: object) -> DebateChunk:
    values: dict[str, object] = {
        "chunk_id": chunk_id,
        "document_id": f"doc-{chunk_id}",
        "source_file": f"{chunk_id}.md",
        "source_path": f"/archive/{chunk_id}.md",
        "source_group": SourceGroup.OTHER,
        "document_type": DocumentType.CASE,
        "section_type": "internal_link",
        "chunk_level": ChunkLevel.SUBMODULE,
        "original_heading": "Investor Confidence",
        "argument_heading": "Economy",
        "heading_path": ["Economy", "Investor Confidence"],
        "text": "Regulatory uncertainty reduces private investment and economic growth.",
        "token_count": 9,
        "freshness": Freshness.UNKNOWN,
        "structure_confidence": 0.9,
    }
    values.update(overrides)
    return DebateChunk(**values)  # type: ignore[arg-type]


def score(
    chunk: DebateChunk,
    request: RetrievalRequest,
    *,
    semantic: float = 0.8,
    lexical: float = 0.3,
    settings: Settings | None = None,
):
    return score_candidate(
        chunk,
        CandidateSignals(
            semantic_score=semantic,
            lexical_score=lexical,
            semantic_query_matches=2,
            lexical_query_matches=1,
        ),
        request,
        infer_query_intents(request),
        settings=settings,
    )


def test_personal_beats_other_modestly_at_equal_relevance() -> None:
    request = RetrievalRequest(motion="regulation reduces private investment")
    personal = score(make_chunk("personal", source_group=SourceGroup.PERSONAL), request)
    other = score(make_chunk("other", source_group=SourceGroup.OTHER), request)

    assert personal.final_score > other.final_score
    assert personal.final_score - other.final_score < 0.10
    assert personal.base_score == other.base_score


def test_relevance_dominates_source_priority() -> None:
    request = RetrievalRequest(motion="Mexico genetically modified corn agriculture")
    weak_personal = score(
        make_chunk(
            "personal",
            source_group=SourceGroup.PERSONAL,
            text="Nuclear deterrence changes alliance credibility.",
            heading_path=["Security"],
        ),
        request,
        semantic=0.28,
        lexical=0.0,
    )
    strong_past = score(
        make_chunk(
            "past",
            source_group=SourceGroup.PAST_CASE,
            text="Allowing genetically modified corn raises Mexican agricultural productivity.",
            heading_path=["Mexico GM Maize"],
        ),
        request,
        semantic=0.88,
        lexical=0.8,
    )

    assert strong_past.final_score > weak_personal.final_score


def test_case_file_sandhu_gets_relevance_gated_masterfile_priority() -> None:
    request = RetrievalRequest(motion="regulation reduces private investment")
    masterfile = score(
        make_chunk(
            "master",
            source_group=SourceGroup.PERSONAL,
            document_type=DocumentType.MASTERFILE,
            is_special_masterfile=True,
            special_masterfile_name="Case File Sandhu",
        ),
        request,
    )
    ordinary = score(
        make_chunk("ordinary", source_group=SourceGroup.PERSONAL),
        request,
    )
    irrelevant_request = RetrievalRequest(motion="museum art curation")
    irrelevant_master = score(masterfile.chunk, irrelevant_request, semantic=0.3, lexical=0.0)

    assert masterfile.masterfile_score > 0
    assert masterfile.final_score > ordinary.final_score
    assert irrelevant_master.masterfile_score == 0


def test_topic_specific_past_case_can_outrank_generic_case_file() -> None:
    request = RetrievalRequest(
        motion="Mexico should allow cultivation of genetically modified corn"
    )
    generic_master = score(
        make_chunk(
            "master",
            source_group=SourceGroup.PERSONAL,
            document_type=DocumentType.MASTERFILE,
            is_special_masterfile=True,
            special_masterfile_name="Case File Sandhu",
            text="Regulation can reduce investment by increasing uncertainty.",
        ),
        request,
        semantic=0.62,
        lexical=0.1,
    )
    specific_past = score(
        make_chunk(
            "past",
            source_group=SourceGroup.PAST_CASE,
            source_file="Mexico GM Maize Case.md",
            argument_heading="GM Corn Agriculture",
            heading_path=["Mexico", "GM Maize"],
            text="Mexico allowing GM corn cultivation improves agricultural yields.",
        ),
        request,
        semantic=0.90,
        lexical=0.8,
    )

    assert specific_past.motion_similarity_score > 0
    assert specific_past.final_score > generic_master.final_score


def test_theory_file_hierarchy_and_nonpersonal_theory_exclusion() -> None:
    request = RetrievalRequest(motion="Conditional advocacies cause strategy skew")
    intents = infer_query_intents(request)
    theory_file = make_chunk(
        "theory-file",
        source_group=SourceGroup.PERSONAL,
        document_type=DocumentType.MASTERFILE,
        section_type="theory_shell",
        is_special_masterfile=True,
        special_masterfile_name="Theory File - Sandhu",
        text="Conditional advocacies create strategy skew.",
    )
    personal = make_chunk(
        "personal-theory",
        source_group=SourceGroup.PERSONAL,
        document_type=DocumentType.THEORY,
        section_type="theory_shell",
        text="Conditionality creates strategy skew.",
    )
    nonpersonal = make_chunk(
        "other-theory",
        source_group=SourceGroup.OTHER,
        document_type=DocumentType.THEORY,
        section_type="theory_shell",
    )

    assert candidate_is_eligible(theory_file, request, intents)[0]
    assert not candidate_is_eligible(nonpersonal, request, intents)[0]
    assert not candidate_is_eligible(make_chunk("normal"), request, intents)[0]
    assert score(theory_file, request).final_score > score(personal, request).final_score


def test_kritik_and_judge_eligibility_rules() -> None:
    personal_k = make_chunk(
        "k",
        source_group=SourceGroup.PERSONAL,
        document_type=DocumentType.KRITIK,
        section_type="kritik",
        text="Capitalism structures exploitation; reject its ontology.",
    )
    tech = RetrievalRequest(
        motion="Capitalism kritik ontology alternative",
        judge_category=JudgeCategory.TECH,
    )
    flow = tech.model_copy(update={"judge_category": JudgeCategory.FLOW})
    fully_lay = tech.model_copy(update={"judge_category": JudgeCategory.FULLY_LAY})
    explicit = fully_lay.model_copy(update={"include_kritiks": True})
    nonpersonal = personal_k.model_copy(
        update={"chunk_id": "other-k", "source_group": SourceGroup.OTHER}
    )

    assert candidate_is_eligible(personal_k, tech, infer_query_intents(tech))[0]
    assert not candidate_is_eligible(personal_k, flow, infer_query_intents(flow))[0]
    assert not candidate_is_eligible(personal_k, fully_lay, infer_query_intents(fully_lay))[0]
    assert candidate_is_eligible(personal_k, explicit, infer_query_intents(explicit))[0]
    assert not candidate_is_eligible(nonpersonal, explicit, infer_query_intents(explicit))[0]


def test_theory_and_k_are_suppressed_for_lay_requests_unless_explicit() -> None:
    theory = make_chunk(
        "theory",
        source_group=SourceGroup.PERSONAL,
        document_type=DocumentType.THEORY,
        section_type="theory_shell",
    )
    request = RetrievalRequest(
        motion="urban transport policy",
        judge_category=JudgeCategory.FULLY_LAY,
    )

    assert not candidate_is_eligible(theory, request, infer_query_intents(request))[0]
    explicit = request.model_copy(update={"include_theory": True})
    assert candidate_is_eligible(theory, explicit, infer_query_intents(explicit))[0]


def test_impact_intent_prefers_impact_and_internal_link_sections() -> None:
    request = RetrievalRequest(motion="economic decline causes poverty impact")
    impact = score(make_chunk("impact", section_type="impact"), request)
    definition = score(make_chunk("definition", section_type="definition"), request)

    assert impact.section_fit_score > 0
    assert impact.final_score > definition.final_score


def test_fresh_empirics_beat_stale_equivalent() -> None:
    request = RetrievalRequest(motion="current inflation harms household welfare")
    current = score(
        make_chunk(
            "current",
            section_type="uniqueness",
            freshness=Freshness.CURRENT,
            text="Inflation is currently raising household costs.",
        ),
        request,
    )
    stale = score(
        make_chunk(
            "stale",
            section_type="uniqueness",
            freshness=Freshness.STALE_EMPIRICS,
            text="Inflation is currently raising household costs.",
        ),
        request,
    )

    assert current.freshness_score > 0
    assert stale.freshness_score < 0
    assert current.final_score > stale.final_score


def test_theory_is_evergreen_regardless_of_year_or_freshness_label() -> None:
    request = RetrievalRequest(motion="conditional advocacies theory strategy skew")
    old = score(
        make_chunk(
            "old",
            source_group=SourceGroup.PERSONAL,
            document_type=DocumentType.THEORY,
            section_type="theory_shell",
            year=2005,
            freshness=Freshness.STALE_EMPIRICS,
        ),
        request,
    )
    new = score(
        old.chunk.model_copy(
            update={"chunk_id": "new", "year": 2026, "freshness": Freshness.CURRENT}
        ),
        request,
    )

    assert old.freshness_score == new.freshness_score == 0
    assert old.final_score == new.final_score


def test_score_breakdown_sums_transparently() -> None:
    candidate = score(
        make_chunk("candidate", source_group=SourceGroup.PERSONAL),
        RetrievalRequest(motion="regulation reduces private investment"),
    )
    expected = (
        candidate.base_score
        + candidate.source_score
        + candidate.masterfile_score
        + candidate.motion_similarity_score
        + candidate.section_fit_score
        + candidate.compatibility_score
        + candidate.freshness_score
        - candidate.redundancy_penalty
    )

    assert candidate.final_score == pytest.approx(expected, abs=1e-5)
    assert 0 <= candidate.support_score <= 1


def test_functional_diversity_reduces_repeated_module_types() -> None:
    request = RetrievalRequest(motion="economic decline causes poverty")
    first = score(make_chunk("a-il"), request, semantic=0.90)
    second = score(
        make_chunk(
            "b-il",
            text="Investor uncertainty suppresses capital expenditure and growth.",
            document_id="doc-b",
        ),
        request,
        semantic=0.88,
    )
    impact = score(
        make_chunk(
            "c-impact",
            document_id="doc-c",
            section_type="impact",
            text="Economic decline raises poverty and reduces human welfare.",
        ),
        request,
        semantic=0.84,
    )

    selected = diversify_candidates([second, impact, first], 3)

    assert {candidate.chunk_id for candidate in selected[:2]} == {"a-il", "c-impact"}
    assert selected[2].chunk_id == "b-il"
    assert selected[2].redundancy_penalty > 0


def test_diversity_ordering_is_deterministic_for_ties() -> None:
    request = RetrievalRequest(motion="economic investment")
    first = score(make_chunk("a"), request)
    second = score(make_chunk("b"), request)

    assert [item.chunk_id for item in diversify_candidates([second, first], 2)] == ["a", "b"]
