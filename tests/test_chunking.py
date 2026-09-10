"""Semantic argument/submodule chunking and fallback behavior tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from debate_engine.config import ChunkingSettings, Settings
from debate_engine.ingestion import (
    approximate_token_count,
    chunk_structured_document,
    detect_structure,
    parse_document,
)
from debate_engine.schemas import (
    ChunkingMetadata,
    ChunkLevel,
    DebateChunk,
    DebateDocument,
    DocumentFormat,
    DocumentType,
    Freshness,
    ParsedBlock,
    ParsedDocument,
    ParseStatus,
    RoundType,
    Side,
    SourceGroup,
)

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "structure"


def chunks_for(
    relative_path: str,
    metadata: ChunkingMetadata | DebateDocument | None = None,
    *,
    settings: Settings | None = None,
) -> list[DebateChunk]:
    parsed = parse_document(FIXTURE_ROOT / relative_path)
    structured = detect_structure(parsed)
    return chunk_structured_document(structured, metadata, settings=settings)


def by_level(chunks: list[DebateChunk], level: ChunkLevel) -> list[DebateChunk]:
    return [chunk for chunk in chunks if chunk.chunk_level is level]


def test_policy_argument_chunks_include_descendants_without_sibling_bleed() -> None:
    chunks = chunks_for("Case File Sandhu.docx")
    arguments = by_level(chunks, ChunkLevel.ARGUMENT)

    # Ten detected structural nodes produce ten standard chunks: each root
    # argument once and each descendant submodule once.
    assert len(chunks) == 10
    assert [chunk.original_heading for chunk in arguments] == [
        "AD 1: Economic Mobility",
        "DA 2: Inflation",
    ]
    assert all(label in arguments[0].text for label in ("UQ:", "L:", "IL:", "IMPX:"))
    assert "Economic mobility reduces entrenched poverty." in arguments[0].text
    assert "DA 2: Inflation" not in arguments[0].text
    assert "AD 1: Economic Mobility" not in arguments[1].text
    assert "Price instability harms low-income households." in arguments[1].text


def test_policy_submodules_preserve_argument_context_and_heading_paths() -> None:
    chunks = chunks_for("Case File Sandhu.docx")
    arguments = by_level(chunks, ChunkLevel.ARGUMENT)
    submodules = by_level(chunks, ChunkLevel.SUBMODULE)
    internal_link = next(
        chunk
        for chunk in submodules
        if chunk.original_heading == "IL:" and chunk.argument_heading == "AD 1: Economic Mobility"
    )

    assert internal_link.section_type == "internal_link"
    assert internal_link.heading_path == ["AD 1: Economic Mobility", "IL:"]
    assert internal_link.parent_heading == "AD 1: Economic Mobility"
    assert internal_link.parent_argument_id == arguments[0].chunk_id
    assert internal_link.text.startswith("AD 1: Economic Mobility\n\nIL:")
    assert "Expanded service improves job access." in internal_link.text
    assert "Rapid spending can increase demand." not in internal_link.text


def test_policy_source_indexes_propagate_only_relevant_blocks() -> None:
    chunks = chunks_for("Case File Sandhu.docx")
    arguments = by_level(chunks, ChunkLevel.ARGUMENT)
    uniqueness = next(
        chunk for chunk in by_level(chunks, ChunkLevel.SUBMODULE) if chunk.original_heading == "UQ:"
    )

    assert arguments[0].source_block_indexes == list(range(9))
    assert arguments[1].source_block_indexes == list(range(9, 18))
    assert uniqueness.source_block_indexes == [0, 1, 2]


def test_claim_warrant_impact_chunks() -> None:
    chunks = chunks_for("claim_warrant_impact.docx")

    assert [chunk.section_type for chunk in by_level(chunks, ChunkLevel.ARGUMENT)] == ["contention"]
    assert [chunk.section_type for chunk in by_level(chunks, ChunkLevel.SUBMODULE)] == [
        "claim",
        "warrant",
        "impact",
    ]


@pytest.mark.parametrize(
    ("filename", "argument_types", "round_type"),
    [
        ("harms_solvency.docx", ["harms", "solvency", "impact"], RoundType.UNKNOWN),
        (
            "value_case.docx",
            ["value", "value_criterion", "weighing_mechanism"],
            RoundType.VALUE,
        ),
        (
            "fact_round.docx",
            ["threshold_of_truth", "observation", "claim"],
            RoundType.FACT,
        ),
        ("answers.docx", ["answer", "answer", "answer"], RoundType.UNKNOWN),
    ],
)
def test_top_level_debate_formats_create_separate_arguments(
    filename: str,
    argument_types: list[str],
    round_type: RoundType,
) -> None:
    chunks = chunks_for(filename)
    arguments = by_level(chunks, ChunkLevel.ARGUMENT)

    assert [chunk.section_type for chunk in arguments] == argument_types
    assert all(chunk.round_type is round_type for chunk in chunks)
    assert not by_level(chunks, ChunkLevel.FALLBACK)


def test_theory_shell_creates_full_argument_and_reusable_components() -> None:
    chunks = chunks_for("Theory File - Sandhu.docx")
    argument = by_level(chunks, ChunkLevel.ARGUMENT)[0]
    submodules = by_level(chunks, ChunkLevel.SUBMODULE)

    assert argument.section_type == "theory_shell"
    assert all(label in argument.text for label in ("Interpretation:", "Standards:", "Voters:"))
    assert [chunk.section_type for chunk in submodules] == [
        "interpretation",
        "standards",
        "voters",
    ]
    assert all(chunk.argument_heading == "Theory Shell" for chunk in submodules)
    assert all(chunk.parent_argument_id == argument.chunk_id for chunk in submodules)


def test_kritik_creates_full_argument_and_reusable_components() -> None:
    chunks = chunks_for("capitalism_kritik.docx")

    assert [chunk.section_type for chunk in by_level(chunks, ChunkLevel.ARGUMENT)] == ["kritik"]
    assert [chunk.section_type for chunk in by_level(chunks, ChunkLevel.SUBMODULE)] == [
        "framework",
        "link",
        "impact",
        "alternative",
    ]
    assert all(chunk.document_type is DocumentType.KRITIK for chunk in chunks)


def test_conservative_document_type_inference_uses_strong_structure() -> None:
    assert all(chunk.document_type is DocumentType.BLOCK for chunk in chunks_for("answers.docx"))
    assert all(
        chunk.document_type is DocumentType.CASE
        for chunk in chunks_for("claim_warrant_impact.docx")
    )
    assert all(
        chunk.document_type is DocumentType.THEORY for chunk in chunks_for("counter_theory.docx")
    )


def test_nested_subpoint_chunks_preserve_full_context() -> None:
    chunks = chunks_for("nested_numbering.docx")
    rural = next(chunk for chunk in chunks if chunk.original_heading == "i. Rural communities")

    assert rural.chunk_level is ChunkLevel.SUBMODULE
    assert rural.section_type == "subpoint"
    assert rural.heading_path == [
        "UQ",
        "1. Poverty",
        "a. Below the poverty line",
        "i. Rural communities",
    ]
    assert rural.parent_heading == "a. Below the poverty line"
    assert rural.text.startswith(
        "UQ\n\n1. Poverty\n\na. Below the poverty line\n\ni. Rural communities"
    )
    assert "Distance compounds access barriers." in rural.text


def test_case_masterfile_splits_broad_categories_into_contextual_modules() -> None:
    chunks = chunks_for("masterfiles/Case File Sandhu.docx")
    arguments = by_level(chunks, ChunkLevel.ARGUMENT)
    submodules = by_level(chunks, ChunkLevel.SUBMODULE)

    assert len(arguments) == 3
    assert len(submodules) == 3
    economy_argument = next(
        chunk for chunk in arguments if chunk.original_heading == "Economy (Regulation Bad)"
    )
    economy_module = next(
        chunk for chunk in submodules if chunk.original_heading == "Economy (Regulation Bad)"
    )

    assert economy_argument.heading_path == [
        "Internal Links",
        "Economy (Regulation Bad)",
    ]
    assert economy_argument.section_type == "internal_link"
    assert economy_module.chunk_level is ChunkLevel.SUBMODULE
    assert economy_module.section_type == "internal_link"
    assert economy_module.parent_argument_id == economy_argument.chunk_id
    assert "Public Health" not in economy_argument.text
    assert "Public Health" not in economy_module.text
    assert economy_module.is_special_masterfile
    assert economy_module.special_masterfile_name == "Case File Sandhu"
    assert economy_module.source_group is SourceGroup.PERSONAL
    assert economy_module.document_type is DocumentType.MASTERFILE
    assert economy_module.priority_weight == pytest.approx(1.15)


def test_theory_masterfile_identity_is_preserved_without_new_document_type() -> None:
    chunks = chunks_for("Theory File - Sandhu.docx")

    assert all(chunk.is_special_masterfile for chunk in chunks)
    assert all(chunk.special_masterfile_name == "Theory File - Sandhu" for chunk in chunks)
    assert all(chunk.document_type is DocumentType.MASTERFILE for chunk in chunks)
    assert all(chunk.source_group is SourceGroup.PERSONAL for chunk in chunks)


def test_long_semantic_argument_is_not_split_by_fallback_limits() -> None:
    settings = Settings(
        chunking=ChunkingSettings(
            fallback_max_tokens=40,
            fallback_overlap_tokens=10,
        )
    )
    chunks = chunks_for("long_semantic.docx", settings=settings)

    assert len(by_level(chunks, ChunkLevel.ARGUMENT)) == 1
    assert len(by_level(chunks, ChunkLevel.SUBMODULE)) == 1
    assert not by_level(chunks, ChunkLevel.FALLBACK)
    assert all(chunk.token_count > settings.chunking.fallback_max_tokens for chunk in chunks)
    assert "Sentence 159 preserves this synthetic semantic argument intact." in chunks[0].text


def test_unstructured_document_uses_paragraph_fallback_with_overlap() -> None:
    settings = Settings(
        chunking=ChunkingSettings(
            fallback_max_tokens=50,
            fallback_overlap_tokens=15,
        )
    )
    chunks = chunks_for("fallback_long.docx", settings=settings)

    assert len(chunks) == 4
    assert all(chunk.chunk_level is ChunkLevel.FALLBACK for chunk in chunks)
    assert all(chunk.token_count <= 50 for chunk in chunks)
    assert set(chunks[0].source_block_indexes) & set(chunks[1].source_block_indexes) == {2}
    repeated_paragraph = (
        "The gamma paragraph contains synthetic ordinary prose for fallback "
        "boundary and overlap testing."
    )
    assert repeated_paragraph in chunks[0].text
    assert repeated_paragraph in chunks[1].text


def test_oversized_fallback_paragraph_splits_only_when_unavoidable() -> None:
    text = " ".join(f"word{index}" for index in range(80))
    parsed = ParsedDocument(
        source_path=Path("/synthetic/long.txt"),
        filename="long.txt",
        detected_format=DocumentFormat.TEXT,
        parse_status=ParseStatus.SUCCESS,
        raw_text=text,
        blocks=[ParsedBlock(text=text, index=0)],
    )
    structured = detect_structure(parsed)
    settings = Settings(
        chunking=ChunkingSettings(
            fallback_max_tokens=20,
            fallback_overlap_tokens=5,
        )
    )

    chunks = chunk_structured_document(structured, settings=settings)

    assert len(chunks) == 5
    assert all(chunk.token_count <= 20 for chunk in chunks)
    first_tokens = chunks[0].text.split()
    second_tokens = chunks[1].text.split()
    assert first_tokens[-5:] == second_tokens[:5]
    assert all(chunk.source_block_indexes == [0] for chunk in chunks)


def test_partial_structure_uses_semantics_not_fallback() -> None:
    chunks = chunks_for("partial_structure.docx")

    assert [chunk.chunk_level for chunk in chunks] == [
        ChunkLevel.ARGUMENT,
        ChunkLevel.SUBMODULE,
    ]
    assert "Synthetic prefatory note remains orphaned." not in chunks[0].text
    assert chunks[1].original_heading == "Local Comparison"


def test_debate_document_metadata_propagates_without_reinference() -> None:
    metadata = DebateDocument(
        document_id="known-document-id",
        filename="source.docx",
        full_path="/archive/Aff/source.docx",
        source_group=SourceGroup.PAST_CASE,
        document_type=DocumentType.CASE,
        side=Side.AFF,
        round_type=RoundType.VALUE,
        year=2024,
        priority_weight=1.37,
    )

    chunks = chunks_for("claim_warrant_impact.docx", metadata)

    assert all(chunk.document_id == "known-document-id" for chunk in chunks)
    assert all(chunk.source_group is SourceGroup.PAST_CASE for chunk in chunks)
    assert all(chunk.document_type is DocumentType.CASE for chunk in chunks)
    assert all(chunk.side is Side.AFF for chunk in chunks)
    assert all(chunk.round_type is RoundType.VALUE for chunk in chunks)
    assert all(chunk.year == 2024 for chunk in chunks)
    assert all(chunk.priority_weight == pytest.approx(1.37) for chunk in chunks)


def test_optional_metadata_can_prepare_evergreen_freshness() -> None:
    metadata = ChunkingMetadata(freshness=Freshness.EVERGREEN)

    chunks = chunks_for("counter_theory.docx", metadata)

    assert all(chunk.freshness is Freshness.EVERGREEN for chunk in chunks)


def test_unknown_metadata_remains_conservative() -> None:
    chunks = chunks_for("ordinary_prose.docx")

    assert chunks[0].source_group is SourceGroup.OTHER
    assert chunks[0].document_type is DocumentType.UNKNOWN
    assert chunks[0].side is Side.UNKNOWN
    assert chunks[0].round_type is RoundType.UNKNOWN
    assert chunks[0].year is None
    assert chunks[0].freshness is Freshness.UNKNOWN


def test_strong_path_side_hint_is_inferred() -> None:
    parsed = parse_document(FIXTURE_ROOT / "claim_warrant_impact.docx")
    structured = detect_structure(parsed).model_copy(
        update={"source_path": Path("/archive/Affirmative/access_case.docx")}
    )

    chunks = chunk_structured_document(structured)

    assert all(chunk.side is Side.AFF for chunk in chunks)


def test_chunk_ids_and_output_are_deterministic_and_unique() -> None:
    parsed = parse_document(FIXTURE_ROOT / "Case File Sandhu.docx")
    structured = detect_structure(parsed)

    first = chunk_structured_document(structured)
    second = chunk_structured_document(structured)

    assert [chunk.model_dump(mode="json") for chunk in first] == [
        chunk.model_dump(mode="json") for chunk in second
    ]
    assert len({chunk.chunk_id for chunk in first}) == len(first)
    assert all(chunk.text.strip() for chunk in first)
    assert all(chunk.token_count == approximate_token_count(chunk.text) for chunk in first)


def test_invalid_fallback_overlap_is_rejected() -> None:
    with pytest.raises(ValidationError, match="must be smaller"):
        ChunkingSettings(
            fallback_max_tokens=40,
            fallback_overlap_tokens=40,
        )
