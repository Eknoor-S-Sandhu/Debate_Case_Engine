"""Schema validation tests for DebateDocument and DebateChunk."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from debate_engine.schemas import (
    ChunkLevel,
    DebateChunk,
    DebateDocument,
    DocumentType,
    Freshness,
    RoundType,
    Side,
    SourceGroup,
)


def make_document(**overrides: object) -> DebateDocument:
    fields: dict[str, object] = {
        "document_id": "doc-0001",
        "filename": "Case File Sandhu.docx",
        "full_path": "data/raw/personal/Case File Sandhu.docx",
        "raw_text": "Nuclear energy is the fastest route to decarbonisation.",
    }
    fields.update(overrides)
    return DebateDocument(**fields)  # type: ignore[arg-type]


def make_chunk(**overrides: object) -> DebateChunk:
    fields: dict[str, object] = {
        "chunk_id": "doc-0001::arg-03",
        "document_id": "doc-0001",
        "source_file": "Case File Sandhu.docx",
        "source_path": "data/raw/personal/Case File Sandhu.docx",
        "text": "Baseload capacity is the binding constraint on grid decarbonisation.",
    }
    fields.update(overrides)
    return DebateChunk(**fields)  # type: ignore[arg-type]


# --- 1. DebateDocument validates correctly ---------------------------------


def test_debate_document_validates_with_full_metadata() -> None:
    document = make_document(
        source_group=SourceGroup.PERSONAL,
        document_type=DocumentType.MASTERFILE,
        side=Side.GOV,
        round_type=RoundType.POLICY,
        year=2025,
        title="Nuclear Energy Masterfile",
        priority_weight=1.15,
    )

    assert document.document_id == "doc-0001"
    assert document.source_group is SourceGroup.PERSONAL
    assert document.document_type is DocumentType.MASTERFILE
    assert document.side is Side.GOV
    assert document.round_type is RoundType.POLICY
    assert document.year == 2025
    assert document.priority_weight == pytest.approx(1.15)


# --- 2. DebateChunk validates correctly ------------------------------------


def test_debate_chunk_validates_with_full_metadata() -> None:
    chunk = make_chunk(
        source_group=SourceGroup.PERSONAL,
        document_type=DocumentType.MASTERFILE,
        section_type="IMPX",
        chunk_level=ChunkLevel.SUBMODULE,
        original_heading="Impact - Climate Tipping Points",
        argument_heading="Advantage 1: Climate",
        parent_heading="Advantage 1: Climate",
        heading_path=["Advantage 1: Climate", "Impact - Climate Tipping Points"],
        parent_argument_id="doc-0001::arg-03",
        side=Side.GOV,
        round_type=RoundType.POLICY,
        year=2025,
        token_count=142,
        freshness=Freshness.CURRENT,
        duplicate_group="dup-17",
        priority_weight=1.15,
        source_block_indexes=[10, 11],
        structure_confidence=0.98,
        is_special_masterfile=True,
        special_masterfile_name="Case File Sandhu",
    )

    assert chunk.chunk_id == "doc-0001::arg-03"
    assert chunk.parent_argument_id == "doc-0001::arg-03"
    assert chunk.chunk_level is ChunkLevel.SUBMODULE
    assert chunk.heading_path[-1] == "Impact - Climate Tipping Points"
    assert chunk.year == 2025
    assert chunk.token_count == 142
    assert chunk.freshness is Freshness.CURRENT
    assert chunk.duplicate_group == "dup-17"
    assert chunk.source_block_indexes == [10, 11]
    assert chunk.structure_confidence == pytest.approx(0.98)
    assert chunk.is_special_masterfile


# --- 3. Valid enum values work ---------------------------------------------


@pytest.mark.parametrize("value", ["personal", "past_case", "other"])
def test_source_group_accepts_every_valid_value(value: str) -> None:
    assert make_document(source_group=value).source_group == value


@pytest.mark.parametrize(
    "value",
    ["case", "masterfile", "block", "impact", "fact_sheet", "theory", "kritik", "unknown"],
)
def test_document_type_accepts_every_valid_value(value: str) -> None:
    assert make_document(document_type=value).document_type == value


@pytest.mark.parametrize("value", ["aff", "neg", "gov", "opp", "unknown"])
def test_side_accepts_every_valid_value(value: str) -> None:
    assert make_document(side=value).side == value


@pytest.mark.parametrize("value", ["policy", "value", "fact", "unknown"])
def test_round_type_accepts_every_valid_value(value: str) -> None:
    assert make_document(round_type=value).round_type == value


@pytest.mark.parametrize(
    "value",
    ["current", "possibly_stale", "stale_empirics", "evergreen", "unknown"],
)
def test_freshness_accepts_every_valid_value(value: str) -> None:
    assert make_chunk(freshness=value).freshness == value


# --- 4. Optional and unknown metadata works --------------------------------


def test_document_defaults_to_unknown_metadata() -> None:
    document = make_document()

    assert document.year is None
    assert document.title is None
    assert document.document_type is DocumentType.UNKNOWN
    assert document.side is Side.UNKNOWN
    assert document.round_type is RoundType.UNKNOWN
    assert document.source_group is SourceGroup.OTHER
    assert document.priority_weight == pytest.approx(1.0)


def test_chunk_defaults_to_unknown_metadata() -> None:
    chunk = make_chunk()

    assert chunk.original_heading is None
    assert chunk.parent_argument_id is None
    assert chunk.duplicate_group is None
    assert chunk.section_type == "unknown"
    assert chunk.freshness is Freshness.UNKNOWN
    assert chunk.token_count == 0


# --- 5. Invalid source_group values fail -----------------------------------


def test_invalid_source_group_is_rejected() -> None:
    with pytest.raises(ValidationError):
        make_document(source_group="borrowed_from_a_friend")

    with pytest.raises(ValidationError):
        make_chunk(source_group="borrowed_from_a_friend")


# --- 6. Invalid document_type values fail ----------------------------------


def test_invalid_document_type_is_rejected() -> None:
    with pytest.raises(ValidationError):
        make_document(document_type="counterplan")

    with pytest.raises(ValidationError):
        make_chunk(document_type="counterplan")


def test_invalid_side_and_round_type_are_rejected() -> None:
    with pytest.raises(ValidationError):
        make_document(side="proposition")

    with pytest.raises(ValidationError):
        make_document(round_type="parliamentary")


def test_missing_required_field_is_rejected() -> None:
    with pytest.raises(ValidationError):
        DebateDocument(filename="orphan.docx")  # type: ignore[call-arg]


def test_negative_token_count_is_rejected() -> None:
    with pytest.raises(ValidationError):
        make_chunk(token_count=-1)


def test_empty_chunk_text_is_rejected() -> None:
    with pytest.raises(ValidationError):
        make_chunk(text="   ")


# --- 10. section_type accepts flexible strings -----------------------------


@pytest.mark.parametrize(
    "section_type",
    [
        "UQ",
        "L",
        "IL",
        "IMPX",
        "Harms",
        "Solvency",
        "Impacts",
        "Claim",
        "Warrant",
        "Impact",
        "Framing",
        "A2: Economic Collapse",
        "some_convention_we_have_not_seen_yet",
    ],
)
def test_section_type_accepts_arbitrary_debate_conventions(section_type: str) -> None:
    assert make_chunk(section_type=section_type).section_type == section_type


def test_section_type_is_trimmed_but_case_preserved() -> None:
    assert make_chunk(section_type="  IMPX  ").section_type == "IMPX"


def test_empty_section_type_is_rejected() -> None:
    with pytest.raises(ValidationError):
        make_chunk(section_type="   ")
