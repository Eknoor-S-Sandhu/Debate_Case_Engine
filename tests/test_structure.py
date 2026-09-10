"""Debate-specific heading normalization and hierarchy tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from debate_engine.config import StructureDetectionSettings
from debate_engine.ingestion import detect_structure, parse_document
from debate_engine.schemas import (
    DocumentFormat,
    ParsedBlock,
    ParsedDocument,
    ParseStatus,
    StructuredDocument,
    StructuredSection,
)

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "structure"


def structured(filename: str) -> StructuredDocument:
    return detect_structure(parse_document(FIXTURE_ROOT / filename))


def flattened(document: StructuredDocument) -> list[StructuredSection]:
    return list(document.iter_sections())


def section_types(document: StructuredDocument) -> list[str]:
    return [section.section_type for section in flattened(document)]


def test_policy_ad_da_and_uq_link_internal_link_impact_detection() -> None:
    result = structured("Case File Sandhu.docx")

    assert [section.section_type for section in result.sections] == [
        "advantage",
        "disadvantage",
    ]
    assert [child.section_type for child in result.sections[0].children] == [
        "uniqueness",
        "link",
        "internal_link",
        "impact",
    ]
    assert [child.section_type for child in result.sections[1].children] == [
        "uniqueness",
        "link",
        "internal_link",
        "impact",
    ]


def test_original_and_normalized_headings_are_both_preserved() -> None:
    result = structured("Case File Sandhu.docx")
    advantage = result.sections[0]
    uniqueness = advantage.children[0]
    impact = advantage.children[-1]

    assert advantage.original_heading == "AD 1: Economic Mobility"
    assert advantage.normalized_heading == "Advantage 1: Economic Mobility"
    assert uniqueness.original_heading == "UQ:"
    assert uniqueness.normalized_heading == "Uniqueness"
    assert impact.original_heading == "IMPX:"
    assert impact.normalized_heading == "Impact"


def test_contention_claim_warrant_impact_hierarchy() -> None:
    result = structured("claim_warrant_impact.docx")
    contention = result.sections[0]

    assert contention.section_type == "contention"
    assert [child.section_type for child in contention.children] == [
        "claim",
        "warrant",
        "impact",
    ]
    assert all(child.parent_section_id == contention.section_id for child in contention.children)
    assert all(child.level == 2 for child in contention.children)


def test_harms_solvency_impacts_remain_sensible_root_sections() -> None:
    result = structured("harms_solvency.docx")

    assert [section.section_type for section in result.sections] == [
        "harms",
        "solvency",
        "impact",
    ]
    assert all(section.parent_section_id is None for section in result.sections)


def test_value_and_value_criterion_are_distinct_types() -> None:
    result = structured("value_case.docx")

    assert [section.section_type for section in result.sections] == [
        "value",
        "value_criterion",
        "weighing_mechanism",
    ]
    assert result.sections[0].normalized_heading == "Value: Justice"
    assert result.sections[1].normalized_heading == "Value Criterion: Equal Opportunity"


def test_fact_round_threshold_and_observation_detection() -> None:
    result = structured("fact_round.docx")

    assert section_types(result) == [
        "threshold_of_truth",
        "observation",
        "claim",
    ]


def test_theory_interpretation_standards_voters_hierarchy() -> None:
    result = structured("Theory File - Sandhu.docx")
    shell = result.sections[0]

    assert shell.section_type == "theory_shell"
    assert [child.section_type for child in shell.children] == [
        "interpretation",
        "standards",
        "voters",
    ]
    assert result.title == "Theory Shell"


def test_counter_interpretation_and_counter_standards_normalization() -> None:
    result = structured("counter_theory.docx")
    shell = result.sections[0]

    assert shell.section_type == "theory_shell"
    assert shell.normalized_heading == "Theory Shell: Conditionality"
    assert [child.section_type for child in shell.children] == [
        "counter_interpretation",
        "counter_standards",
        "competing_interpretations",
        "reasonability",
    ]


def test_kritik_framework_link_impact_alternative_hierarchy() -> None:
    result = structured("capitalism_kritik.docx")
    kritik = result.sections[0]

    assert kritik.section_type == "kritik"
    assert kritik.normalized_heading == "Kritik: Capitalism"
    assert [child.section_type for child in kritik.children] == [
        "framework",
        "link",
        "impact",
        "alternative",
    ]


def test_at_a2_and_answer_to_normalize_to_answer() -> None:
    result = structured("answers.docx")

    assert section_types(result) == ["answer", "answer", "answer"]
    assert [section.normalized_heading for section in result.sections] == [
        "Answer: Solvency",
        "Answer: Inflation",
        "Answer: Framework",
    ]
    assert [section.original_heading for section in result.sections] == [
        "AT: Solvency",
        "A2 Inflation",
        "Answer To: Framework",
    ]


def test_nested_numbering_builds_1_a_i_hierarchy() -> None:
    result = structured("nested_numbering.docx")
    uniqueness = result.sections[0]
    poverty, inflation = uniqueness.children
    poverty_detail = poverty.children[0]
    rural_detail = poverty_detail.children[0]

    assert [poverty.original_heading, inflation.original_heading] == [
        "1. Poverty",
        "2. Inflation",
    ]
    assert poverty_detail.original_heading == "a. Below the poverty line"
    assert rural_detail.original_heading == "i. Rural communities"
    assert [poverty.level, poverty_detail.level, rural_detail.level] == [2, 3, 4]
    assert poverty_detail.parent_section_id == poverty.section_id
    assert rural_detail.parent_section_id == poverty_detail.section_id
    assert poverty.detection_method == "numbering"


def test_heading_style_and_formatting_signals_affect_detection() -> None:
    strong = structured("Case File Sandhu.docx").sections[0]
    weak = structured("weak_headings.docx")

    assert strong.detection_method == "docx_heading_style+debate_keyword"
    assert strong.heading_style_name == "Heading 1"
    assert strong.confidence == pytest.approx(0.98)

    assert [section.original_heading for section in weak.sections] == [
        "ROUND FRAMING",
        "Long-Term Weighing",
    ]
    assert weak.sections[0].heading_contains_bold
    assert weak.sections[1].heading_contains_highlight
    assert weak.sections[0].detection_method.startswith("formatted_short_line")
    assert weak.sections[0].confidence == pytest.approx(0.68)


def test_body_text_and_source_block_indexes_are_not_rewritten() -> None:
    result = structured("claim_warrant_impact.docx")
    claim = result.sections[0].children[0]

    assert claim.text == "Accessible transport expands meaningful choice."
    assert len(claim.source_block_indexes) == 2
    assert claim.source_block_indexes == sorted(claim.source_block_indexes)


def test_ordinary_prose_with_debate_words_is_not_misclassified() -> None:
    parsed = parse_document(FIXTURE_ROOT / "ordinary_prose.docx")
    result = detect_structure(parsed)

    assert result.sections == []
    assert result.overall_structure_confidence == 0.0
    assert len(result.orphan_blocks) == len(parsed.blocks)
    assert result.unstructured_text == "\n".join(block.text for block in parsed.blocks)


def test_orphan_text_is_preserved_before_weak_structure() -> None:
    result = structured("weak_headings.docx")

    assert result.unstructured_text == "Synthetic preface without an identified heading."
    assert result.orphan_blocks[0].text in result.unstructured_text
    assert any("precede any detected heading" in warning for warning in result.detection_warnings)


def test_markdown_heading_signal_is_recognized_without_parser_duplication() -> None:
    parsed = ParsedDocument(
        source_path=Path("/synthetic/brief.md"),
        filename="brief.md",
        detected_format=DocumentFormat.MARKDOWN,
        parse_status=ParseStatus.SUCCESS,
        blocks=[
            ParsedBlock(text="# Contention 1: Access", index=0, block_type="line"),
            ParsedBlock(text="Access determines opportunity.", index=1, block_type="line"),
        ],
    )

    result = detect_structure(parsed)

    assert result.sections[0].section_type == "contention"
    assert result.sections[0].detection_method == "markdown_heading+debate_keyword"
    assert result.sections[0].text == "Access determines opportunity."


def test_structure_confidence_is_bounded_and_averaged() -> None:
    result = structured("weak_headings.docx")
    confidences = [section.confidence for section in flattened(result)]

    assert all(0.0 <= confidence <= 1.0 for confidence in confidences)
    assert result.overall_structure_confidence == pytest.approx(sum(confidences) / len(confidences))


def test_detection_thresholds_are_configurable() -> None:
    parsed = ParsedDocument(
        source_path=Path("/synthetic/formatted.docx"),
        filename="formatted.docx",
        detected_format=DocumentFormat.DOCX,
        parse_status=ParseStatus.SUCCESS,
        blocks=[
            ParsedBlock(
                text="Synthetic Heading",
                index=0,
                contains_bold=True,
            )
        ],
    )
    strict = StructureDetectionSettings(minimum_section_confidence=0.90)

    result = detect_structure(parsed, settings=strict)

    assert result.sections == []
    assert result.orphan_blocks[0].text == "Synthetic Heading"


def test_output_is_deterministic() -> None:
    parsed = parse_document(FIXTURE_ROOT / "Case File Sandhu.docx")

    first = detect_structure(parsed)
    second = detect_structure(parsed)

    assert first.model_dump(mode="json") == second.model_dump(mode="json")


def test_malformed_parse_degrades_to_unstructured_warning() -> None:
    parsed = ParsedDocument(
        source_path=Path("/synthetic/broken.docx"),
        filename="broken.docx",
        detected_format=DocumentFormat.DOCX,
        parse_status=ParseStatus.FAILED,
        warnings=["Bad zip file"],
        error_message="Bad zip file",
    )

    result = detect_structure(parsed)

    assert result.sections == []
    assert result.overall_structure_confidence == 0.0
    assert any("Source parse status is failed" in warning for warning in result.detection_warnings)
    assert any("No reliable debate structure" in warning for warning in result.detection_warnings)


def test_ambiguous_heading_level_jump_is_preserved_and_warned() -> None:
    parsed = ParsedDocument(
        source_path=Path("/synthetic/ambiguous.docx"),
        filename="ambiguous.docx",
        detected_format=DocumentFormat.DOCX,
        parse_status=ParseStatus.SUCCESS,
        blocks=[
            ParsedBlock(
                text="Orphan Styled Heading",
                index=0,
                style_name="Heading 3",
                heading_level=3,
            )
        ],
    )

    result = detect_structure(parsed)

    assert result.sections[0].level == 3
    assert result.sections[0].parent_section_id is None
    assert any("without a detected parent" in warning for warning in result.detection_warnings)
