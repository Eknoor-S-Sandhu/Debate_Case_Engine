"""Exact/near duplicate grouping and representative selection tests."""

from __future__ import annotations

from copy import deepcopy

import pytest

from debate_engine.ingestion import (
    detect_duplicates,
    find_exact_duplicate_groups,
    fuzzy_similarity,
    generate_candidate_pairs,
    normalize_duplicate_text,
    select_representative,
    stable_content_hash,
)
from debate_engine.schemas import (
    ChunkLevel,
    DebateChunk,
    DocumentType,
    DuplicateType,
    Freshness,
    SourceGroup,
)


def make_chunk(
    chunk_id: str,
    text: str,
    **overrides: object,
) -> DebateChunk:
    fields: dict[str, object] = {
        "chunk_id": chunk_id,
        "document_id": f"document-{chunk_id}",
        "source_file": f"{chunk_id}.docx",
        "source_path": f"/archive/{chunk_id}.docx",
        "source_group": SourceGroup.OTHER,
        "document_type": DocumentType.CASE,
        "section_type": "advantage",
        "chunk_level": ChunkLevel.ARGUMENT,
        "text": text,
        "token_count": len(text.split()),
        "structure_confidence": 0.90,
    }
    fields.update(overrides)
    return DebateChunk(**fields)  # type: ignore[arg-type]


BASE_TEXT = (
    "Regulation creates uncertainty which reduces long-term investment and "
    "slows productive growth across the economy."
)


def test_normalization_is_safe_and_preserves_numbers() -> None:
    first = "  • Inflation is 8.2%.\nREGULATION   matters. "
    second = "inflation is 4.1%; regulation matters"

    assert normalize_duplicate_text(first) == "inflation is 8 2% regulation matters"
    assert normalize_duplicate_text(second) == "inflation is 4 1% regulation matters"
    assert normalize_duplicate_text(first) != normalize_duplicate_text(second)
    assert stable_content_hash(first) == stable_content_hash(
        "Inflation is 8.2%! Regulation matters"
    )


def test_exact_duplicates_group_after_punctuation_whitespace_normalization() -> None:
    chunks = [
        make_chunk("exact-a", BASE_TEXT),
        make_chunk(
            "exact-b",
            "REGULATION creates uncertainty, which reduces long term investment "
            "and slows productive growth across the economy!",
        ),
    ]

    result = detect_duplicates(chunks)

    assert find_exact_duplicate_groups(chunks) == [["exact-a", "exact-b"]]
    assert len(result.duplicate_groups) == 1
    group = result.duplicate_groups[0]
    assert group.duplicate_type is DuplicateType.EXACT
    assert group.similarity_min == 1.0
    assert group.similarity_max == 1.0
    assert all(chunk.duplicate_group == group.duplicate_group_id for chunk in result.updated_chunks)


def test_minor_rewrite_groups_as_near_duplicate() -> None:
    chunks = [
        make_chunk("near-a", BASE_TEXT),
        make_chunk(
            "near-b",
            "Regulation creates uncertainty, reducing long term investment and "
            "slowing productive growth across the economy.",
        ),
    ]

    result = detect_duplicates(chunks)

    assert fuzzy_similarity(chunks[0].text, chunks[1].text) > 0.92
    assert result.duplicate_groups[0].duplicate_type is DuplicateType.NEAR
    assert result.duplicate_groups[0].similarity_min >= 0.92


def test_updated_statistic_variant_groups_only_at_stricter_similarity() -> None:
    older = make_chunk(
        "stat-old",
        "Inflation is currently 8.2 percent, reducing household purchasing power "
        "and increasing economic insecurity.",
        section_type="impact",
        year=2022,
        freshness=Freshness.STALE_EMPIRICS,
    )
    newer = make_chunk(
        "stat-new",
        "Inflation is currently 4.1 percent, reducing household purchasing power "
        "and increasing economic insecurity.",
        section_type="impact",
        year=2026,
        freshness=Freshness.CURRENT,
    )

    result = detect_duplicates([older, newer])

    assert len(result.duplicate_groups) == 1
    group = result.duplicate_groups[0]
    assert group.duplicate_type is DuplicateType.NEAR
    assert group.similarity_min >= 0.97
    assert group.representative_chunk_id == "stat-new"
    assert any("updated-statistic" in note for note in group.notes)
    assert result.updated_chunks[0].text == older.text
    assert result.updated_chunks[1].text == newer.text


def test_related_but_distinct_arguments_do_not_group() -> None:
    chunks = [
        make_chunk("related-a", BASE_TEXT),
        make_chunk(
            "related-b",
            "Regulations reduce firm entry by increasing compliance costs and "
            "administrative burdens for new businesses.",
        ),
    ]

    result = detect_duplicates(chunks)

    assert fuzzy_similarity(chunks[0].text, chunks[1].text) < 0.60
    assert result.duplicate_groups == []
    assert all(chunk.duplicate_group is None for chunk in result.updated_chunks)


def test_near_groups_require_complete_link_not_similarity_chaining() -> None:
    first = " ".join(f"word{index}" for index in range(100))
    bridge = " ".join(f"changedA{index}" if index < 8 else f"word{index}" for index in range(100))
    third = " ".join(
        (f"changedA{index}" if index < 8 else f"changedB{index}" if index < 16 else f"word{index}")
        for index in range(100)
    )
    chunks = [
        make_chunk("chain-a", first),
        make_chunk("chain-b", bridge),
        make_chunk("chain-c", third),
    ]

    result = detect_duplicates(chunks)

    assert fuzzy_similarity(first, bridge) > 0.92
    assert fuzzy_similarity(bridge, third) > 0.92
    assert fuzzy_similarity(first, third) < 0.92
    assert max(len(group.member_chunk_ids) for group in result.duplicate_groups) == 2


def test_argument_and_submodule_are_structurally_incompatible() -> None:
    chunks = [
        make_chunk("argument", BASE_TEXT, chunk_level=ChunkLevel.ARGUMENT),
        make_chunk(
            "submodule",
            BASE_TEXT,
            chunk_level=ChunkLevel.SUBMODULE,
            section_type="link",
        ),
    ]

    result = detect_duplicates(chunks)

    assert result.duplicate_groups == []
    assert result.statistics.candidate_pairs == 0


def test_incompatible_submodule_types_are_not_compared() -> None:
    chunks = [
        make_chunk(
            "impact",
            BASE_TEXT,
            chunk_level=ChunkLevel.SUBMODULE,
            section_type="impact",
        ),
        make_chunk(
            "alternative",
            BASE_TEXT,
            chunk_level=ChunkLevel.SUBMODULE,
            section_type="alternative",
        ),
    ]

    assert detect_duplicates(chunks).duplicate_groups == []


def test_representative_prefers_personal_over_frequency() -> None:
    chunks = [
        make_chunk(
            f"other-{index}",
            BASE_TEXT,
            source_group=SourceGroup.OTHER,
        )
        for index in range(5)
    ]
    chunks.append(
        make_chunk(
            "personal",
            BASE_TEXT,
            source_group=SourceGroup.PERSONAL,
        )
    )

    group = detect_duplicates(chunks).duplicate_groups[0]

    assert group.representative_chunk_id == "personal"
    assert len(group.member_chunk_ids) == 6


def test_representative_prefers_special_masterfile_within_personal() -> None:
    chunks = [
        make_chunk(
            "ordinary-personal",
            BASE_TEXT,
            source_group=SourceGroup.PERSONAL,
            token_count=100,
        ),
        make_chunk(
            "special-personal",
            BASE_TEXT,
            source_group=SourceGroup.PERSONAL,
            is_special_masterfile=True,
            special_masterfile_name="Case File Sandhu",
            token_count=20,
        ),
    ]

    assert select_representative(chunks).chunk_id == "special-personal"
    assert detect_duplicates(chunks).duplicate_groups[0].representative_chunk_id == (
        "special-personal"
    )


def test_empirical_representative_prefers_newer_year_within_same_source_tier() -> None:
    common = {
        "source_group": SourceGroup.PAST_CASE,
        "section_type": "impact",
        "freshness": Freshness.CURRENT,
    }
    chunks = [
        make_chunk("empirical-old", BASE_TEXT, year=2021, **common),
        make_chunk("empirical-new", BASE_TEXT, year=2026, **common),
    ]

    assert detect_duplicates(chunks).duplicate_groups[0].representative_chunk_id == (
        "empirical-new"
    )


@pytest.mark.parametrize(
    ("document_type", "section_type"),
    [
        (DocumentType.THEORY, "theory_shell"),
        (DocumentType.KRITIK, "kritik"),
    ],
)
def test_theory_and_k_representative_selection_ignore_year(
    document_type: DocumentType,
    section_type: str,
) -> None:
    chunks = [
        make_chunk(
            "a-older",
            BASE_TEXT,
            document_type=document_type,
            section_type=section_type,
            source_group=SourceGroup.PERSONAL,
            year=2018,
        ),
        make_chunk(
            "z-newer",
            BASE_TEXT,
            document_type=document_type,
            section_type=section_type,
            source_group=SourceGroup.PERSONAL,
            year=2026,
        ),
    ]

    result = detect_duplicates(chunks)

    assert result.duplicate_groups[0].representative_chunk_id == "a-older"
    assert any("age-neutral" in note for note in result.duplicate_groups[0].notes)


def test_group_ids_and_representatives_are_deterministic_across_input_order() -> None:
    chunks = [
        make_chunk("det-a", BASE_TEXT, source_group=SourceGroup.OTHER),
        make_chunk("det-b", BASE_TEXT, source_group=SourceGroup.PERSONAL),
        make_chunk(
            "det-c",
            "Regulation creates uncertainty, reducing long term investment and "
            "slowing productive growth across the economy.",
            source_group=SourceGroup.PAST_CASE,
        ),
    ]

    first = detect_duplicates(chunks)
    second = detect_duplicates(list(reversed(chunks)))

    assert first.duplicate_groups == second.duplicate_groups
    assert first.duplicate_groups[0].duplicate_group_id.startswith("dup_")
    assert first.duplicate_groups[0].representative_chunk_id == "det-b"


def test_singleton_has_no_group_and_stale_group_is_cleared() -> None:
    chunk = make_chunk("singleton", BASE_TEXT, duplicate_group="stale-group")

    result = detect_duplicates([chunk])

    assert result.duplicate_groups == []
    assert result.updated_chunks[0].duplicate_group is None
    assert result.statistics.singleton_chunks == 1


def test_every_original_chunk_and_text_is_preserved_without_input_mutation() -> None:
    chunks = [
        make_chunk("preserve-a", BASE_TEXT),
        make_chunk(
            "preserve-b",
            "REGULATION creates uncertainty, which reduces long term investment "
            "and slows productive growth across the economy!",
        ),
        make_chunk("preserve-c", "A fully distinct synthetic argument about public health."),
    ]
    snapshot = deepcopy(chunks)

    result = detect_duplicates(chunks)

    assert chunks == snapshot
    assert [chunk.chunk_id for chunk in result.updated_chunks] == [
        chunk.chunk_id for chunk in chunks
    ]
    assert [chunk.text for chunk in result.updated_chunks] == [chunk.text for chunk in chunks]
    assert len(result.updated_chunks) == len(chunks)


def test_candidate_blocking_avoids_blind_quadratic_comparison() -> None:
    chunks = [
        make_chunk(
            f"scale-{index:04d}",
            f"Unique marker{index} explains a separate synthetic mechanism involving "
            f"sector{index} institutions and outcome{index} evidence.",
        )
        for index in range(300)
    ]

    result = detect_duplicates(chunks)

    assert result.statistics.possible_fuzzy_pairs == 44_850
    assert result.statistics.candidate_pairs < 300
    assert result.statistics.compared_pairs < 300
    assert result.duplicate_groups == []


def test_fallback_near_matching_uses_stricter_threshold() -> None:
    first = (
        "Public transit expands access to employment because reliable routes "
        "connect isolated communities to major job centers."
    )
    second = (
        "Public transit expands access to employment because reliable bus routes "
        "connect isolated communities with major job centers."
    )
    argument_chunks = [
        make_chunk("argument-a", first),
        make_chunk("argument-b", second),
    ]
    fallback_chunks = [
        make_chunk(
            "fallback-a",
            first,
            chunk_level=ChunkLevel.FALLBACK,
            section_type="fallback",
        ),
        make_chunk(
            "fallback-b",
            second,
            chunk_level=ChunkLevel.FALLBACK,
            section_type="fallback",
        ),
    ]

    assert len(detect_duplicates(argument_chunks).duplicate_groups) == 1
    assert detect_duplicates(fallback_chunks).duplicate_groups == []


def test_duplicate_chunk_ids_fail_clearly() -> None:
    chunks = [
        make_chunk("same-id", BASE_TEXT),
        make_chunk("same-id", f"{BASE_TEXT} Additional wording."),
    ]

    with pytest.raises(ValueError, match="chunk_id values must be unique"):
        detect_duplicates(chunks)


def test_empty_representative_selection_fails_clearly() -> None:
    with pytest.raises(ValueError, match="empty list"):
        select_representative([])


def test_candidate_pair_helper_returns_chunk_ids() -> None:
    chunks = [
        make_chunk("candidate-a", BASE_TEXT),
        make_chunk(
            "candidate-b",
            "Regulation creates uncertainty, reducing long term investment and "
            "slowing productive growth across the economy.",
        ),
    ]

    assert generate_candidate_pairs(chunks) == {("candidate-a", "candidate-b")}
