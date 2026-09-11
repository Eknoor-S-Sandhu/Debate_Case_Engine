"""Deterministic motion parsing and multi-query generation tests."""

from __future__ import annotations

import pytest

from debate_engine.config import Settings
from debate_engine.retrieval import (
    clean_motion,
    concept_tokens,
    generate_retrieval_queries,
    infer_query_intents,
)
from debate_engine.schemas import QueryFamily, RetrievalRequest, Side


@pytest.mark.parametrize(
    ("motion", "expected"),
    [
        ("THW ban facial recognition", "ban facial recognition"),
        ("THBT: cities should subsidize transit", "cities should subsidize transit"),
        ("THP a carbon tax", "a carbon tax"),
        ("THR—privatization", "privatization"),
        ("THS nuclear energy", "nuclear energy"),
        ("THO military intervention", "military intervention"),
        ("This House Would regulate AI", "regulate AI"),
        ("This House Believes That Mexico should allow GM corn", "Mexico should allow GM corn"),
        ("This House Prefers public transport", "public transport"),
        ("This House Regrets agricultural subsidies", "agricultural subsidies"),
        ("This House Supports NATO expansion", "NATO expansion"),
        ("This House Opposes currency controls", "currency controls"),
    ],
)
def test_common_motion_prefixes_are_cleaned(motion: str, expected: str) -> None:
    assert clean_motion(motion) == expected


def test_concepts_preserve_entities_technologies_and_acronyms() -> None:
    tokens = concept_tokens(
        "Mexico should permit genetically modified corn through USMCA agricultural trade"
    )

    assert tokens == [
        "mexico",
        "permit",
        "genetically",
        "modified",
        "corn",
        "through",
        "usmca",
        "agricultural",
        "trade",
    ]


def test_query_generation_is_deterministic_bounded_and_multifamily() -> None:
    request = RetrievalRequest(
        motion="THW lift Mexico's ban on planting genetically modified corn",
        side=Side.AFF,
    )

    first = generate_retrieval_queries(request)
    second = generate_retrieval_queries(request)

    assert first == second
    assert 4 <= len(first) <= 7
    assert first[0].family is QueryFamily.FULL_MOTION
    assert first[0].text == "lift Mexico's ban on planting genetically modified corn"
    assert {query.family for query in first} >= {
        QueryFamily.FULL_MOTION,
        QueryFamily.CORE_CONCEPT,
        QueryFamily.MECHANISM,
        QueryFamily.IMPACT,
        QueryFamily.SIDE_AWARE,
    }
    assert any("agricultural productivity" in query.text for query in first)


def test_explicit_queries_and_concepts_are_preserved_without_duplicates() -> None:
    request = RetrievalRequest(
        motion="THW regulate artificial intelligence",
        explicit_concepts=["algorithmic accountability"],
        user_queries=["labor displacement", "labor displacement"],
    )

    queries = generate_retrieval_queries(request)

    assert sum(query.text == "labor displacement" for query in queries) == 1
    assert any("algorithmic accountability" in query.text for query in queries)


def test_side_aware_queries_change_with_side() -> None:
    affirmative = generate_retrieval_queries(
        RetrievalRequest(motion="THW remove trade restrictions", side=Side.GOV)
    )
    negative = generate_retrieval_queries(
        RetrievalRequest(motion="THW remove trade restrictions", side=Side.OPP)
    )

    assert any("benefits advantages reform" in query.text for query in affirmative)
    assert any("harms risks disadvantages" in query.text for query in negative)


def test_query_limit_is_configurable() -> None:
    settings = Settings(retrieval={"max_generated_queries": 4})
    request = RetrievalRequest(
        motion="THW lift Mexico's ban on genetically modified corn",
        side=Side.AFF,
    )

    assert len(generate_retrieval_queries(request, settings=settings)) == 4


def test_intent_inference_uses_request_not_generated_expansion_noise() -> None:
    ordinary = RetrievalRequest(motion="THW legalize urban farming")
    impact = RetrievalRequest(
        motion="THW legalize urban farming",
        user_queries=["economic decline causes poverty impact"],
    )
    theory = RetrievalRequest(motion="Conditional advocacies cause strategy skew")

    assert "impact" not in infer_query_intents(
        ordinary,
        generate_retrieval_queries(ordinary),
    )
    assert {"impact", "internal_link"} <= infer_query_intents(impact)
    assert "theory" in infer_query_intents(theory)
