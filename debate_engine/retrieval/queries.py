"""Deterministic motion cleanup, concept extraction, and multi-query generation."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

from debate_engine.config import Settings, get_settings
from debate_engine.schemas import (
    GeneratedQuery,
    QueryFamily,
    RetrievalRequest,
    Side,
)

_MOTION_PREFIX = re.compile(
    r"^\s*(?:"
    r"TH(?:W|BT|P|R|S|O)"
    r"|This\s+House\s+(?:Would|Believes\s+That|Prefers|Regrets|Supports|Opposes)"
    r")\s*[:\-–—,.]?\s*",
    re.IGNORECASE,
)
_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9'-]*")
_SPACE = re.compile(r"\s+")
_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "has",
        "in",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "that",
        "the",
        "their",
        "this",
        "to",
        "would",
        "should",
        "with",
    }
)

_MECHANISM_THEMES: tuple[tuple[frozenset[str], str], ...] = (
    (
        frozenset({"ban", "bans", "regulation", "regulations", "restriction", "restrictions"}),
        "regulation restrictions incentives compliance investment",
    ),
    (
        frozenset({"agriculture", "agricultural", "corn", "crop", "crops", "maize", "farming"}),
        "agricultural productivity crop yields farmer livelihoods",
    ),
    (
        frozenset({"trade", "tariff", "tariffs", "imports", "exports"}),
        "trade restrictions prices competition economic effects",
    ),
    (
        frozenset({"economy", "economic", "growth", "investment", "inflation", "currency"}),
        "investment productivity employment economic growth mechanism",
    ),
    (
        frozenset({"climate", "environment", "environmental", "emissions", "pollution"}),
        "environmental incentives emissions ecosystem mechanism",
    ),
    (
        frozenset({"military", "security", "war", "conflict", "power"}),
        "security deterrence conflict hard power soft power",
    ),
    (
        frozenset({"subsidy", "subsidies"}),
        "subsidies market incentives prices resource allocation",
    ),
)

_IMPACT_THEMES: tuple[tuple[frozenset[str], str], ...] = (
    (
        frozenset({"agriculture", "agricultural", "corn", "crop", "crops", "maize", "food"}),
        "agricultural productivity poverty food security",
    ),
    (
        frozenset({"economy", "economic", "growth", "investment", "trade", "jobs"}),
        "economic growth employment poverty human welfare",
    ),
    (
        frozenset({"climate", "environment", "environmental", "emissions", "pollution"}),
        "environmental destruction public health human welfare biodiversity",
    ),
    (
        frozenset({"military", "security", "war", "conflict"}),
        "conflict escalation lives stability security",
    ),
)

_INTENT_TERMS: dict[str, frozenset[str]] = {
    "uniqueness": frozenset({"uniqueness", "status", "currently", "now", "trend"}),
    "link": frozenset({"link", "links", "causes", "mechanism", "mechanisms", "leads"}),
    "internal_link": frozenset(
        {"internal", "investment", "confidence", "growth", "poverty", "productivity"}
    ),
    "impact": frozenset(
        {"impact", "impacts", "harm", "harms", "welfare", "poverty", "security", "lives"}
    ),
    "solvency": frozenset({"solvency", "solve", "solves", "solution", "effective"}),
    "framework": frozenset({"framework", "framing", "weighing", "calculus", "criterion"}),
    "answer": frozenset({"answer", "answers", "response", "responses", "preempt", "rebuttal"}),
    "theory": frozenset(
        {
            "theory",
            "conditional",
            "advocacies",
            "interpretation",
            "violation",
            "standards",
            "voters",
            "skew",
        }
    ),
    "kritik": frozenset(
        {"kritik", "critique", "capitalism", "ontology", "epistemology", "alternative", "ballot"}
    ),
}


def clean_motion(motion: str) -> str:
    """Remove one recognized parliamentary prefix and normalize whitespace."""
    normalized = unicodedata.normalize("NFKC", motion).strip()
    cleaned = _MOTION_PREFIX.sub("", normalized, count=1)
    return _SPACE.sub(" ", cleaned).strip(" .,:;–—-")


def concept_tokens(text: str) -> list[str]:
    """Extract ordered content terms without discarding entities or acronyms."""
    seen: set[str] = set()
    tokens: list[str] = []
    for match in _TOKEN.finditer(unicodedata.normalize("NFKC", text)):
        token = match.group().casefold().strip("'-")
        if len(token) < 2 or token in _STOPWORDS or token in seen:
            continue
        seen.add(token)
        tokens.append(token)
    return tokens


def _append_query(
    queries: list[GeneratedQuery],
    seen: set[str],
    family: QueryFamily,
    text: str,
) -> None:
    cleaned = _SPACE.sub(" ", text).strip()
    key = cleaned.casefold()
    if cleaned and key not in seen:
        seen.add(key)
        queries.append(GeneratedQuery(family=family, text=cleaned))


def _matching_theme_queries(
    tokens: set[str],
    themes: Iterable[tuple[frozenset[str], str]],
) -> list[str]:
    return [query for markers, query in themes if markers & tokens]


def generate_retrieval_queries(
    request: RetrievalRequest,
    *,
    settings: Settings | None = None,
) -> list[GeneratedQuery]:
    """Generate a bounded, deterministic 4–8 query set from round context."""
    configured = settings or get_settings()
    cleaned_motion = clean_motion(request.motion)
    motion_tokens = concept_tokens(cleaned_motion)
    explicit_tokens = [
        token for concept in request.explicit_concepts for token in concept_tokens(concept)
    ]
    core_tokens = list(dict.fromkeys([*motion_tokens, *explicit_tokens]))
    core = " ".join(core_tokens)
    token_set = set(core_tokens)

    queries: list[GeneratedQuery] = []
    seen: set[str] = set()
    _append_query(queries, seen, QueryFamily.FULL_MOTION, cleaned_motion)
    for user_query in request.user_queries:
        _append_query(queries, seen, QueryFamily.EXPLICIT, user_query)
    _append_query(queries, seen, QueryFamily.CORE_CONCEPT, core)

    mechanism_queries = _matching_theme_queries(token_set, _MECHANISM_THEMES)
    impact_queries = _matching_theme_queries(token_set, _IMPACT_THEMES)
    if not mechanism_queries and core:
        mechanism_queries = [f"{core} incentives mechanism effects"]
    if not impact_queries and core:
        impact_queries = [f"{core} impacts harms benefits"]
    for query in mechanism_queries[:2]:
        _append_query(queries, seen, QueryFamily.MECHANISM, query)
    for query in impact_queries[:2]:
        _append_query(queries, seen, QueryFamily.IMPACT, query)

    if request.side in {Side.AFF, Side.GOV}:
        _append_query(
            queries,
            seen,
            QueryFamily.SIDE_AWARE,
            f"benefits advantages reform change {core}",
        )
        _append_query(
            queries,
            seen,
            QueryFamily.SIDE_AWARE,
            f"harms problems current policy status quo {core}",
        )
    elif request.side in {Side.NEG, Side.OPP}:
        _append_query(
            queries,
            seen,
            QueryFamily.SIDE_AWARE,
            f"harms risks disadvantages change {core}",
        )
        _append_query(
            queries,
            seen,
            QueryFamily.SIDE_AWARE,
            f"benefits defenses current policy restrictions {core}",
        )

    return queries[: configured.retrieval.max_generated_queries]


def infer_query_intents(
    request: RetrievalRequest,
    queries: Iterable[GeneratedQuery] = (),
) -> set[str]:
    """Infer broad argumentative functions requested by the round context."""
    del queries  # Generated expansion terms must not invent user intent.
    combined = " ".join(
        [
            request.motion,
            *request.explicit_concepts,
            *request.user_queries,
        ]
    )
    tokens = set(concept_tokens(combined))
    return {intent for intent, markers in _INTENT_TERMS.items() if markers & tokens}
