"""Focused normalization tests for common heading variants."""

import pytest

from debate_engine.ingestion.structure_rules import match_debate_heading


@pytest.mark.parametrize(
    ("heading", "section_type", "normalized"),
    [
        ("AD1 — Economy", "advantage", "Advantage 1: Economy"),
        ("Advantage 1 - Growth", "advantage", "Advantage 1: Growth"),
        ("DA 2: Inflation", "disadvantage", "Disadvantage 2: Inflation"),
        ("Uniqueness:", "uniqueness", "Uniqueness"),
        ("Links:", "link", "Link"),
        ("Internal Links:", "internal_link", "Internal Link"),
        ("Impacts:", "impact", "Impact"),
        ("Warrants:", "warrant", "Warrant"),
        ("Security K", "kritik", "Kritik: Security"),
        ("Neoliberalism Kritik", "kritik", "Kritik: Neoliberalism"),
        ("Answer To: Framework", "answer", "Answer: Framework"),
        ("Counter-Interp:", "counter_interpretation", "Counter-Interpretation"),
        ("Counter-Standards:", "counter_standards", "Counter-Standards"),
        ("Alt", "alternative", "Alternative"),
        ("Plan Text", "plan", "Plan"),
        ("CP: Public Option", "counterplan", "Counterplan: Public Option"),
    ],
)
def test_heading_variants_normalize(
    heading: str,
    section_type: str,
    normalized: str,
) -> None:
    result = match_debate_heading(heading)

    assert result is not None
    assert result.section_type == section_type
    assert result.normalized_heading == normalized


@pytest.mark.parametrize(
    "prose",
    [
        "The impact reaches people over time.",
        "Our link depends on adoption rates.",
        "This framework compares two possible outcomes.",
        "The claim remains contested by available evidence.",
    ],
)
def test_ordinary_sentences_do_not_match_rules(prose: str) -> None:
    assert match_debate_heading(prose) is None
