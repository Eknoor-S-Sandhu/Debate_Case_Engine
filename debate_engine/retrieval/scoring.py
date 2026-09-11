"""Transparent hybrid scoring, eligibility rules, and deterministic diversity."""

from __future__ import annotations

from dataclasses import dataclass

from debate_engine.config import Settings, get_settings
from debate_engine.ingestion import fuzzy_similarity
from debate_engine.retrieval.queries import clean_motion, concept_tokens
from debate_engine.schemas import (
    DebateChunk,
    DocumentType,
    Freshness,
    JudgeCategory,
    RetrievalCandidate,
    RetrievalRequest,
    RoundType,
    Side,
    SourceGroup,
    SupportLevel,
)

_THEORY_SECTIONS = frozenset(
    {
        "theory_shell",
        "interpretation",
        "violation",
        "standards",
        "voters",
        "counter_interpretation",
        "counter_standards",
        "reasonability",
        "competing_interpretations",
    }
)
_KRITIK_SECTIONS = frozenset(
    {
        "kritik",
        "thesis",
        "framework",
        "role_of_the_ballot",
        "alternative",
    }
)
_AGE_NEUTRAL_SECTIONS = frozenset(
    {
        *_THEORY_SECTIONS,
        *_KRITIK_SECTIONS,
        "impact_calculus",
        "framing",
        "framework",
        "claim",
        "warrant",
    }
)
_EMPIRICAL_SECTIONS = frozenset({"uniqueness", "harms", "solvency", "example", "empirics", "fact"})
_CASE_MASTERFILE_TOPICS = frozenset(
    {
        "economy",
        "economic",
        "regulation",
        "subsidies",
        "subsidy",
        "inflation",
        "interest",
        "currency",
        "currencies",
        "development",
        "resources",
        "nationalization",
        "environment",
        "environmental",
        "investment",
        "poverty",
        "welfare",
        "power",
    }
)
_SECTION_FIT: dict[str, frozenset[str]] = {
    "uniqueness": frozenset({"uniqueness"}),
    "link": frozenset({"link", "internal_link", "warrant"}),
    "internal_link": frozenset({"internal_link", "link", "warrant", "impact"}),
    "impact": frozenset({"impact", "internal_link", "impact_calculus", "framing"}),
    "solvency": frozenset({"solvency", "harms"}),
    "framework": frozenset({"framework", "framing", "impact_calculus", "value", "value_criterion"}),
    "answer": frozenset({"answer", "response", "preempt", "rebuttal"}),
    "theory": _THEORY_SECTIONS,
    "kritik": _KRITIK_SECTIONS,
}


@dataclass(frozen=True, slots=True)
class CandidateSignals:
    semantic_score: float = 0.0
    lexical_score: float = 0.0
    semantic_query_matches: int = 0
    lexical_query_matches: int = 0


def is_theory_chunk(chunk: DebateChunk) -> bool:
    return (
        chunk.document_type is DocumentType.THEORY
        or chunk.section_type.casefold() in _THEORY_SECTIONS
        or (chunk.special_masterfile_name or "").casefold() == "theory file - sandhu"
    )


def is_kritik_chunk(chunk: DebateChunk) -> bool:
    return (
        chunk.document_type is DocumentType.KRITIK
        or chunk.section_type.casefold() in _KRITIK_SECTIONS
        and not is_theory_chunk(chunk)
    )


def _is_personal_source(chunk: DebateChunk) -> bool:
    """Treat configured named masterfiles as personal even outside archive folders."""
    return chunk.source_group is SourceGroup.PERSONAL or bool(
        chunk.is_special_masterfile and chunk.special_masterfile_name
    )


def candidate_is_eligible(
    chunk: DebateChunk,
    request: RetrievalRequest,
    intents: set[str],
) -> tuple[bool, str | None]:
    """Apply source, theory, K, and judge eligibility before scoring."""
    if request.source_group is not None and chunk.source_group is not request.source_group:
        return False, "source-group filter"

    if is_theory_chunk(chunk):
        if not _is_personal_source(chunk):
            return False, "non-personal theory excluded"
        if request.include_theory is False:
            return False, "theory explicitly excluded"
        if request.include_theory is True or "theory" in intents:
            return True, None
        return False, "theory not requested"

    if "theory" in intents:
        return False, "non-theory material excluded from theory retrieval"

    if is_kritik_chunk(chunk):
        if not _is_personal_source(chunk):
            return False, "non-personal kritik excluded"
        if request.include_kritiks is False:
            return False, "kritiks explicitly excluded"
        if request.include_kritiks is True:
            return True, None
        if request.judge_category is JudgeCategory.TECH and "kritik" in intents:
            return True, None
        return False, "kritik not eligible for judge/context"

    return True, None


def _overlap_score(query_tokens: set[str], target: str) -> float:
    if not query_tokens:
        return 0.0
    target_tokens = set(concept_tokens(target))
    return min(1.0, len(query_tokens & target_tokens) / max(1, min(len(query_tokens), 8)))


def _source_score(base: float, chunk: DebateChunk, settings: Settings) -> float:
    if chunk.is_special_masterfile and chunk.special_masterfile_name:
        weight = settings.source_weights.personal_masterfile
    else:
        weight = {
            SourceGroup.PERSONAL: settings.source_weights.personal,
            SourceGroup.PAST_CASE: settings.source_weights.past_case,
            SourceGroup.OTHER: settings.source_weights.other,
        }[chunk.source_group]
    return base * (weight - 1.0) * settings.retrieval.source_influence


def _masterfile_score(
    base: float,
    chunk: DebateChunk,
    motion_tokens: set[str],
    intents: set[str],
    settings: Settings,
) -> float:
    special = (chunk.special_masterfile_name or "").casefold()
    if special == "theory file - sandhu" and "theory" in intents:
        return base * settings.retrieval.theory_masterfile_bonus
    if special != "case file sandhu":
        return 0.0
    relevant = bool(
        motion_tokens & _CASE_MASTERFILE_TOPICS
        or intents & {"internal_link", "impact", "framework", "link"}
    )
    return base * settings.retrieval.masterfile_bonus if relevant else 0.0


def _motion_similarity_score(
    semantic: float,
    chunk: DebateChunk,
    motion_tokens: set[str],
    settings: Settings,
) -> float:
    if chunk.source_group is not SourceGroup.PAST_CASE:
        return 0.0
    context = " ".join(
        [
            chunk.source_file,
            chunk.argument_heading or "",
            chunk.original_heading or "",
            *chunk.heading_path,
            chunk.text[:500],
        ]
    )
    overlap = _overlap_score(motion_tokens, context)
    similarity = 0.7 * overlap + 0.3 * max(0.0, semantic)
    if overlap < 0.20:
        return 0.0
    return min(1.0, similarity) * settings.retrieval.motion_similarity_bonus


def _section_fit_score(
    chunk: DebateChunk,
    intents: set[str],
    request: RetrievalRequest,
    settings: Settings,
) -> float:
    section = chunk.section_type.casefold()
    fit = 0.0
    for intent in intents:
        compatible = _SECTION_FIT.get(intent, frozenset())
        if section in compatible:
            fit = max(fit, 1.0 if section == intent else 0.75)
    if request.judge_category in {JudgeCategory.FLAY, JudgeCategory.FULLY_LAY} and section in {
        "claim",
        "warrant",
        "impact",
        "harms",
        "solvency",
    }:
        fit = max(fit, 0.35)
    return fit * settings.retrieval.section_fit_bonus


def _is_empirical(chunk: DebateChunk) -> bool:
    section = chunk.section_type.casefold()
    if is_theory_chunk(chunk) or is_kritik_chunk(chunk) or section in _AGE_NEUTRAL_SECTIONS:
        return False
    return (
        section in _EMPIRICAL_SECTIONS
        or chunk.freshness
        in {Freshness.CURRENT, Freshness.POSSIBLY_STALE, Freshness.STALE_EMPIRICS}
        or any(character.isdigit() for character in chunk.text)
    )


def _freshness_score(chunk: DebateChunk, settings: Settings) -> float:
    if not _is_empirical(chunk):
        return 0.0
    influence = settings.retrieval.freshness_influence
    return {
        Freshness.CURRENT: influence,
        Freshness.POSSIBLY_STALE: -0.5 * influence,
        Freshness.STALE_EMPIRICS: -influence,
        Freshness.EVERGREEN: 0.0,
        Freshness.UNKNOWN: 0.0,
    }[chunk.freshness]


def _compatibility_score(chunk: DebateChunk, request: RetrievalRequest) -> float:
    score = 0.0
    if (
        request.side is not None
        and request.side is not Side.UNKNOWN
        and chunk.side is not Side.UNKNOWN
    ):
        request_family = "affirmative" if request.side in {Side.AFF, Side.GOV} else "negative"
        chunk_family = "affirmative" if chunk.side in {Side.AFF, Side.GOV} else "negative"
        score += 0.025 if request_family == chunk_family else -0.01
    if (
        request.round_type is not None
        and request.round_type is not RoundType.UNKNOWN
        and chunk.round_type is not RoundType.UNKNOWN
    ):
        score += 0.015 if request.round_type is chunk.round_type else -0.005
    return score


def _support(
    chunk: DebateChunk,
    signals: CandidateSignals,
) -> tuple[float, SupportLevel]:
    source_quality = {
        SourceGroup.PERSONAL: 1.0,
        SourceGroup.PAST_CASE: 0.8,
        SourceGroup.OTHER: 0.55,
    }[chunk.source_group]
    corroboration = min(
        1.0,
        (signals.semantic_query_matches + signals.lexical_query_matches) / 4.0,
    )
    score = (
        0.65 * max(0.0, signals.semantic_score)
        + 0.15 * signals.lexical_score
        + 0.10 * source_quality
        + 0.10 * corroboration
    )
    if chunk.freshness is Freshness.STALE_EMPIRICS and _is_empirical(chunk):
        score -= 0.10
    score = round(max(0.0, min(1.0, score)), 6)
    level = (
        SupportLevel.HIGH
        if score >= 0.72
        else SupportLevel.MODERATE
        if score >= 0.42
        else SupportLevel.LOW
    )
    return score, level


def score_candidate(
    chunk: DebateChunk,
    signals: CandidateSignals,
    request: RetrievalRequest,
    intents: set[str],
    *,
    settings: Settings | None = None,
) -> RetrievalCandidate:
    """Build one complete, inspectable pre-diversity score."""
    configured = settings or get_settings()
    motion = clean_motion(request.motion)
    motion_tokens = set(concept_tokens(" ".join([motion, *request.explicit_concepts])))
    context = " ".join([chunk.text, chunk.argument_heading or "", chunk.original_heading or ""])
    headings = " ".join(
        [*chunk.heading_path, chunk.argument_heading or "", chunk.original_heading or ""]
    )
    concept_score = _overlap_score(motion_tokens, context)
    heading_score = _overlap_score(motion_tokens, headings)
    semantic = max(0.0, min(1.0, signals.semantic_score))
    lexical = max(0.0, min(1.0, signals.lexical_score))
    base = (
        configured.retrieval.semantic_weight * semantic
        + configured.retrieval.lexical_weight * lexical
        + configured.retrieval.concept_weight * concept_score
        + configured.retrieval.heading_weight * heading_score
    )
    source = _source_score(base, chunk, configured)
    masterfile = _masterfile_score(base, chunk, motion_tokens, intents, configured)
    motion_similarity = _motion_similarity_score(semantic, chunk, motion_tokens, configured)
    section_fit = _section_fit_score(chunk, intents, request, configured)
    compatibility = _compatibility_score(chunk, request)
    freshness = _freshness_score(chunk, configured)
    final = base + source + masterfile + motion_similarity + section_fit + compatibility + freshness
    support_score, support_level = _support(chunk, signals)

    reasons = []
    if semantic >= 0.65:
        reasons.append("strong semantic match")
    if lexical >= 0.50:
        reasons.append("lexically corroborated")
    if concept_score >= 0.50:
        reasons.append("motion concepts overlap")
    if source > 0:
        source_label = (
            "personal masterfile"
            if chunk.is_special_masterfile and chunk.special_masterfile_name
            else chunk.source_group.value
        )
        reasons.append(f"{source_label} source preference")
    if masterfile > 0:
        reasons.append(f"relevant {chunk.special_masterfile_name}")
    if motion_similarity > 0:
        reasons.append("similar past motion/context")
    if section_fit > 0:
        reasons.append(f"{chunk.section_type} fits query intent")
    if compatibility > 0:
        reasons.append("side/round metadata compatible")
    elif compatibility < 0:
        reasons.append("side/round metadata mismatch")
    if freshness > 0:
        reasons.append("current empirical material")
    elif freshness < 0:
        reasons.append("stale empirical material")

    return RetrievalCandidate(
        chunk_id=chunk.chunk_id,
        chunk=chunk,
        semantic_score=round(semantic, 6),
        lexical_score=round(lexical, 6),
        concept_score=round(concept_score, 6),
        heading_score=round(heading_score, 6),
        base_score=round(base, 6),
        source_score=round(source, 6),
        masterfile_score=round(masterfile, 6),
        motion_similarity_score=round(motion_similarity, 6),
        section_fit_score=round(section_fit, 6),
        compatibility_score=round(compatibility, 6),
        freshness_score=round(freshness, 6),
        final_score=round(final, 6),
        support_score=support_score,
        support_level=support_level,
        semantic_query_matches=signals.semantic_query_matches,
        lexical_query_matches=signals.lexical_query_matches,
        reasons=reasons,
    )


def _redundancy_penalty(
    candidate: RetrievalCandidate,
    selected: list[RetrievalCandidate],
    settings: Settings,
) -> float:
    if not selected:
        return 0.0
    chunk = candidate.chunk
    penalty = 0.0
    same_function = 0
    for existing in selected:
        other = existing.chunk
        if chunk.parent_argument_id and chunk.parent_argument_id == other.parent_argument_id:
            penalty = max(penalty, settings.retrieval.same_parent_penalty)
        if chunk.document_id == other.document_id:
            penalty = max(penalty, settings.retrieval.same_document_penalty)
        if chunk.section_type.casefold() == other.section_type.casefold():
            same_function += 1
        text_similarity = fuzzy_similarity(chunk.text, other.text)
        if text_similarity >= 0.82:
            scaled = (text_similarity - 0.82) / 0.18
            penalty = max(penalty, scaled * settings.retrieval.text_redundancy_penalty)
    penalty += min(2, same_function) * settings.retrieval.repeated_function_penalty
    return round(penalty, 6)


def diversify_candidates(
    candidates: list[RetrievalCandidate],
    limit: int,
    *,
    settings: Settings | None = None,
) -> list[RetrievalCandidate]:
    """Greedily select by score minus transparent redundancy penalties."""
    configured = settings or get_settings()
    remaining = list(candidates)
    selected: list[RetrievalCandidate] = []
    while remaining and len(selected) < limit:
        scored = [
            (
                candidate.final_score - _redundancy_penalty(candidate, selected, configured),
                candidate.chunk_id,
                candidate,
            )
            for candidate in remaining
        ]
        adjusted, _, best = min(scored, key=lambda item: (-item[0], item[1]))
        penalty = round(best.final_score - adjusted, 6)
        reasons = [*best.reasons]
        if penalty > 0:
            reasons.append("redundancy/diversity penalty applied")
        selected.append(
            best.model_copy(
                update={
                    "redundancy_penalty": penalty,
                    "final_score": round(adjusted, 6),
                    "rank": len(selected) + 1,
                    "reasons": reasons,
                }
            )
        )
        remaining.remove(best)
    return selected
