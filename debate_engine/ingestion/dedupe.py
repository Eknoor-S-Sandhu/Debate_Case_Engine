"""Deterministic, non-destructive exact and near-duplicate detection."""

from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from itertools import combinations

from rapidfuzz import fuzz

from debate_engine.config import DuplicateDetectionSettings, Settings, get_settings
from debate_engine.schemas import (
    ChunkLevel,
    DebateChunk,
    DocumentType,
    DuplicateDetectionResult,
    DuplicateGroup,
    DuplicateStatistics,
    DuplicateType,
    Freshness,
    SourceGroup,
)

_NON_NUMERIC_BULLET = re.compile(r"(?m)^\s*[-*•‣▪◦]+\s+")
_MINOR_PUNCTUATION = re.compile(r"[^\w\s%]")
_WHITESPACE = re.compile(r"\s+")
_WORD = re.compile(r"\b[\w%]+\b")
_NUMBER = re.compile(r"(?<!\w)\d+(?:[.,]\d+)?%?(?!\w)")
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

_STOPWORDS = frozenset(
    {
        "about",
        "after",
        "again",
        "against",
        "argument",
        "because",
        "before",
        "being",
        "between",
        "claim",
        "could",
        "debate",
        "does",
        "from",
        "have",
        "impact",
        "into",
        "more",
        "other",
        "should",
        "that",
        "their",
        "there",
        "these",
        "they",
        "this",
        "through",
        "under",
        "which",
        "with",
        "would",
    }
)
_AGE_NEUTRAL_SECTION_TYPES = frozenset(
    {
        "alternative",
        "competing_interpretations",
        "counter_interpretation",
        "counter_standards",
        "framework",
        "framing",
        "impact_calculus",
        "interpretation",
        "kritik",
        "reasonability",
        "role_of_the_ballot",
        "standards",
        "theory_shell",
        "thesis",
        "violation",
        "voters",
    }
)


@dataclass(frozen=True, slots=True)
class _ExactUnit:
    """One normalized-text bucket, potentially containing exact copies."""

    member_indexes: tuple[int, ...]
    canonical_index: int
    normalized_text: str
    compatibility_key: tuple[str, str]


class _UnionFind:
    def __init__(self, size: int) -> None:
        self.parent = list(range(size))
        self.members = {index: {index} for index in range(size)}

    def find(self, item: int) -> int:
        while self.parent[item] != item:
            self.parent[item] = self.parent[self.parent[item]]
            item = self.parent[item]
        return item

    def union(self, first: int, second: int) -> int:
        first_root = self.find(first)
        second_root = self.find(second)
        if first_root == second_root:
            return first_root
        if min(self.members[first_root]) > min(self.members[second_root]):
            first_root, second_root = second_root, first_root
        self.parent[second_root] = first_root
        self.members[first_root].update(self.members.pop(second_root))
        return first_root


def normalize_duplicate_text(text: str) -> str:
    """Apply conservative comparison-only normalization.

    Numbers and percent signs remain meaningful. Original chunk text is never
    changed; this normalized form exists only for hashes and fuzzy comparison.
    """
    normalized = unicodedata.normalize("NFKC", text)
    normalized = normalized.translate(
        str.maketrans(
            {
                "\u00a0": " ",
                "\u2007": " ",
                "\u202f": " ",
                "\u2018": "",
                "\u2019": "",
                "'": "",
                "\u2010": "-",
                "\u2011": "-",
                "\u2012": "-",
                "\u2013": "-",
                "\u2014": "-",
                "\u2212": "-",
            }
        )
    )
    normalized = _NON_NUMERIC_BULLET.sub("", normalized)
    normalized = _MINOR_PUNCTUATION.sub(" ", normalized.casefold())
    return _WHITESPACE.sub(" ", normalized).strip()


def stable_content_hash(text: str) -> str:
    """Hash safely normalized content for the exact first pass."""
    return hashlib.sha256(normalize_duplicate_text(text).encode()).hexdigest()


def fuzzy_similarity(first: str, second: str) -> float:
    """Return a conservative 0–1 character/token-order similarity score."""
    first_normalized = normalize_duplicate_text(first)
    second_normalized = normalize_duplicate_text(second)
    if not first_normalized and not second_normalized:
        return 1.0
    if not first_normalized or not second_normalized:
        return 0.0
    character_ratio = fuzz.ratio(first_normalized, second_normalized) / 100.0
    token_sort_ratio = fuzz.token_sort_ratio(first_normalized, second_normalized) / 100.0
    return round(0.70 * character_ratio + 0.30 * token_sort_ratio, 6)


def _compatibility_key(chunk: DebateChunk) -> tuple[str, str]:
    if chunk.chunk_level is ChunkLevel.ARGUMENT:
        return chunk.chunk_level.value, "argument"
    if chunk.chunk_level is ChunkLevel.FALLBACK:
        return chunk.chunk_level.value, "fallback"
    return chunk.chunk_level.value, chunk.section_type.casefold()


def find_exact_duplicate_groups(chunks: list[DebateChunk]) -> list[list[str]]:
    """Return deterministic compatible exact-match buckets."""
    buckets: dict[tuple[tuple[str, str], str, str], list[str]] = defaultdict(list)
    for chunk in chunks:
        normalized = normalize_duplicate_text(chunk.text)
        key = (_compatibility_key(chunk), stable_content_hash(chunk.text), normalized)
        buckets[key].append(chunk.chunk_id)
    return sorted(
        (sorted(member_ids) for member_ids in buckets.values() if len(member_ids) > 1),
        key=lambda member_ids: member_ids[0],
    )


def _build_exact_units(chunks: list[DebateChunk]) -> list[_ExactUnit]:
    buckets: dict[tuple[tuple[str, str], str, str], list[int]] = defaultdict(list)
    for index, chunk in enumerate(chunks):
        normalized = normalize_duplicate_text(chunk.text)
        key = (_compatibility_key(chunk), stable_content_hash(chunk.text), normalized)
        buckets[key].append(index)

    units: list[_ExactUnit] = []
    for (compatibility_key, _, normalized), member_indexes in buckets.items():
        ordered_members = tuple(sorted(member_indexes, key=lambda item: chunks[item].chunk_id))
        units.append(
            _ExactUnit(
                member_indexes=ordered_members,
                canonical_index=ordered_members[0],
                normalized_text=normalized,
                compatibility_key=compatibility_key,
            )
        )
    return sorted(units, key=lambda unit: chunks[unit.canonical_index].chunk_id)


def _significant_tokens(text: str) -> set[str]:
    return {
        token
        for token in _WORD.findall(text)
        if len(token) >= 4 and token not in _STOPWORDS and not token.isdigit()
    }


def _candidate_anchors(
    text: str,
    frequencies: Counter[str],
    anchor_count: int,
    unit_count: int,
) -> set[str]:
    tokens_in_order = [
        token
        for token in _WORD.findall(text)
        if len(token) >= 4 and token not in _STOPWORDS and not token.isdigit()
    ]
    unique_tokens = set(tokens_in_order)
    contextual_frequency_limit = max(2, unit_count // 100)
    rare = sorted(
        (token for token in unique_tokens if frequencies[token] <= contextual_frequency_limit),
        key=lambda token: (frequencies[token], token),
    )[:anchor_count]
    contextual = [
        token
        for token in [*tokens_in_order[:2], *tokens_in_order[-2:]]
        if frequencies[token] <= contextual_frequency_limit
    ]
    anchors = {*rare, *contextual}
    return anchors or {hashlib.sha256(text.encode()).hexdigest()[:16]}


def _length_ratio(first: str, second: str) -> float:
    longer = max(len(first), len(second))
    return min(len(first), len(second)) / longer if longer else 1.0


def _length_bucket(text: str, bucket_ratio: float) -> int:
    return int(math.log(max(len(text), 1), bucket_ratio))


def _generate_candidate_pairs(
    units: list[_ExactUnit],
    settings: DuplicateDetectionSettings,
) -> set[tuple[int, int]]:
    token_sets = [_significant_tokens(unit.normalized_text) for unit in units]
    frequencies = Counter(token for tokens in token_sets for token in tokens)
    index: dict[tuple[tuple[str, str], int, str], list[int]] = defaultdict(list)
    candidates: set[tuple[int, int]] = set()

    for unit_index, unit in enumerate(units):
        if len(unit.normalized_text) < settings.minimum_fuzzy_characters:
            continue
        bucket = _length_bucket(unit.normalized_text, settings.length_bucket_ratio)
        anchors = _candidate_anchors(
            unit.normalized_text,
            frequencies,
            settings.candidate_anchor_count,
            len(units),
        )
        for anchor in anchors:
            for neighboring_bucket in (bucket - 1, bucket, bucket + 1):
                key = (unit.compatibility_key, neighboring_bucket, anchor)
                for other_index in index.get(key, []):
                    other = units[other_index]
                    if (
                        _length_ratio(unit.normalized_text, other.normalized_text)
                        >= settings.minimum_length_ratio
                    ):
                        candidates.add((other_index, unit_index))
            index[(unit.compatibility_key, bucket, anchor)].append(unit_index)
    return candidates


def generate_candidate_pairs(
    chunks: list[DebateChunk],
    *,
    settings: Settings | None = None,
) -> set[tuple[str, str]]:
    """Return blocked fuzzy candidate chunk IDs for inspection and tests."""
    configured = settings or get_settings()
    units = _build_exact_units(chunks)
    return {
        tuple(
            sorted(
                (
                    chunks[units[first].canonical_index].chunk_id,
                    chunks[units[second].canonical_index].chunk_id,
                )
            )
        )
        for first, second in _generate_candidate_pairs(
            units,
            configured.duplicate_detection,
        )
    }


def _number_tokens(text: str) -> tuple[str, ...]:
    return tuple(_NUMBER.findall(unicodedata.normalize("NFKC", text)))


def _has_updated_statistics(first: DebateChunk, second: DebateChunk) -> bool:
    first_numbers = _number_tokens(first.text)
    second_numbers = _number_tokens(second.text)
    return bool(first_numbers or second_numbers) and first_numbers != second_numbers


def _required_similarity(
    first: DebateChunk,
    second: DebateChunk,
    settings: Settings,
) -> float:
    threshold = settings.duplicate_similarity_threshold
    if first.chunk_level is ChunkLevel.FALLBACK:
        threshold = max(
            threshold,
            settings.duplicate_detection.fallback_similarity_threshold,
        )
    if _has_updated_statistics(first, second):
        threshold = max(
            threshold,
            settings.duplicate_detection.updated_statistic_threshold,
        )
    return threshold


def _is_age_neutral(chunk: DebateChunk) -> bool:
    return (
        chunk.document_type in {DocumentType.THEORY, DocumentType.KRITIK}
        or chunk.section_type.casefold() in _AGE_NEUTRAL_SECTION_TYPES
    )


def _is_empirical(chunk: DebateChunk) -> bool:
    if _is_age_neutral(chunk):
        return False
    return chunk.freshness in {
        Freshness.CURRENT,
        Freshness.POSSIBLY_STALE,
        Freshness.STALE_EMPIRICS,
    } or bool(_number_tokens(chunk.text))


def _is_truncated(chunk: DebateChunk) -> bool:
    lowered = chunk.text.rstrip().casefold()
    return lowered.endswith(("...", "…")) or "[truncated]" in lowered


def _quality_key(chunk: DebateChunk) -> tuple[int, int, int, int, int, int, int, float, int]:
    source_rank = {
        SourceGroup.PERSONAL: 3,
        SourceGroup.PAST_CASE: 2,
        SourceGroup.OTHER: 1,
    }[chunk.source_group]
    special_rank = int(chunk.source_group is SourceGroup.PERSONAL and chunk.is_special_masterfile)
    empirical = _is_empirical(chunk)
    year_rank = (chunk.year or 0) if empirical else 0
    freshness_rank = (
        {
            Freshness.CURRENT: 4,
            Freshness.POSSIBLY_STALE: 3,
            Freshness.UNKNOWN: 2,
            Freshness.STALE_EMPIRICS: 1,
            Freshness.EVERGREEN: 2,
        }[chunk.freshness]
        if empirical
        else 0
    )
    context_rank = len(chunk.heading_path) + int(chunk.argument_heading is not None)
    cleanliness = -(chunk.text.count("\ufffd") + len(_CONTROL_CHARACTERS.findall(chunk.text)))
    return (
        source_rank,
        special_rank,
        year_rank,
        freshness_rank,
        int(not _is_truncated(chunk)),
        chunk.token_count,
        context_rank,
        chunk.structure_confidence,
        cleanliness,
    )


def select_representative(chunks: list[DebateChunk]) -> DebateChunk:
    """Select one preferred member without considering copy frequency."""
    if not chunks:
        raise ValueError("cannot select a representative from an empty list")
    best_quality = max(_quality_key(chunk) for chunk in chunks)
    tied = [chunk for chunk in chunks if _quality_key(chunk) == best_quality]
    return min(tied, key=lambda chunk: chunk.chunk_id)


def _duplicate_group_id(member_chunk_ids: list[str]) -> str:
    digest = hashlib.sha256("|".join(sorted(member_chunk_ids)).encode()).hexdigest()[:16]
    return f"dup_{digest}"


def detect_duplicates(
    chunks: list[DebateChunk],
    *,
    settings: Settings | None = None,
) -> DuplicateDetectionResult:
    """Group compatible exact and conservative near duplicates.

    Input chunks are never mutated. The returned copies differ only in their
    ``duplicate_group`` field.
    """
    configured = settings or get_settings()
    chunk_ids = [chunk.chunk_id for chunk in chunks]
    if len(set(chunk_ids)) != len(chunk_ids):
        raise ValueError("chunk_id values must be unique before duplicate detection")

    units = _build_exact_units(chunks)
    candidates = _generate_candidate_pairs(units, configured.duplicate_detection)
    union_find = _UnionFind(len(units))
    similarity_cache: dict[tuple[int, int], float] = {}
    compared_pairs = 0

    def unit_similarity(first: int, second: int) -> float:
        nonlocal compared_pairs
        key = tuple(sorted((first, second)))
        if key not in similarity_cache:
            similarity_cache[key] = fuzzy_similarity(
                units[key[0]].normalized_text,
                units[key[1]].normalized_text,
            )
            compared_pairs += 1
        return similarity_cache[key]

    scored_candidates = sorted(
        (
            unit_similarity(first, second),
            chunks[units[first].canonical_index].chunk_id,
            chunks[units[second].canonical_index].chunk_id,
            first,
            second,
        )
        for first, second in candidates
    )
    accepted_near_edges: list[tuple[int, int, float]] = []

    for similarity, _, _, first, second in reversed(scored_candidates):
        first_root = union_find.find(first)
        second_root = union_find.find(second)
        if first_root == second_root:
            continue

        cross_pairs = [
            (left, right)
            for left in union_find.members[first_root]
            for right in union_find.members[second_root]
        ]
        compatible = True
        for left, right in cross_pairs:
            left_chunk = chunks[units[left].canonical_index]
            right_chunk = chunks[units[right].canonical_index]
            if _length_ratio(
                units[left].normalized_text, units[right].normalized_text
            ) < configured.duplicate_detection.minimum_length_ratio or unit_similarity(
                left, right
            ) < _required_similarity(left_chunk, right_chunk, configured):
                compatible = False
                break
        if not compatible:
            continue

        union_find.union(first_root, second_root)
        accepted_near_edges.append((first, second, similarity))

    unit_components = sorted(
        union_find.members.values(),
        key=lambda component: min(
            chunks[units[unit].canonical_index].chunk_id for unit in component
        ),
    )
    duplicate_groups: list[DuplicateGroup] = []
    group_by_chunk_id: dict[str, str] = {}

    for component in unit_components:
        member_indexes = sorted(
            (
                member_index
                for unit_index in component
                for member_index in units[unit_index].member_indexes
            ),
            key=lambda index: chunks[index].chunk_id,
        )
        if len(member_indexes) < 2:
            continue

        member_chunks = [chunks[index] for index in member_indexes]
        member_ids = [chunk.chunk_id for chunk in member_chunks]
        component_has_near_edge = any(
            first in component and second in component for first, second, _ in accepted_near_edges
        )
        duplicate_type = DuplicateType.NEAR if component_has_near_edge else DuplicateType.EXACT

        if duplicate_type is DuplicateType.EXACT:
            similarities = [1.0]
        else:
            similarities = [
                unit_similarity(first, second)
                for first, second in combinations(sorted(component), 2)
            ]
            if any(len(units[unit].member_indexes) > 1 for unit in component):
                similarities.append(1.0)

        representative = select_representative(member_chunks)
        group_id = _duplicate_group_id(member_ids)
        notes = ["All member chunks are preserved; frequency is not a quality signal."]
        if any(
            _has_updated_statistics(first, second)
            for first, second in combinations(member_chunks, 2)
        ):
            notes.append("Contains updated-statistic variants; original values are preserved.")
        if all(_is_age_neutral(chunk) for chunk in member_chunks):
            notes.append("Theory/K representative selection is age-neutral.")

        duplicate_groups.append(
            DuplicateGroup(
                duplicate_group_id=group_id,
                member_chunk_ids=member_ids,
                representative_chunk_id=representative.chunk_id,
                duplicate_type=duplicate_type,
                similarity_min=round(min(similarities), 4),
                similarity_max=round(max(similarities), 4),
                notes=notes,
            )
        )
        group_by_chunk_id.update(dict.fromkeys(member_ids, group_id))

    duplicate_groups.sort(key=lambda group: group.duplicate_group_id)
    updated_chunks = [
        chunk.model_copy(update={"duplicate_group": group_by_chunk_id.get(chunk.chunk_id)})
        for chunk in chunks
    ]
    exact_groups = sum(group.duplicate_type is DuplicateType.EXACT for group in duplicate_groups)
    near_groups = len(duplicate_groups) - exact_groups
    grouped_chunks = len(group_by_chunk_id)
    possible_fuzzy_pairs = len(units) * (len(units) - 1) // 2

    return DuplicateDetectionResult(
        updated_chunks=updated_chunks,
        duplicate_groups=duplicate_groups,
        statistics=DuplicateStatistics(
            total_chunks=len(chunks),
            grouped_chunks=grouped_chunks,
            singleton_chunks=len(chunks) - grouped_chunks,
            duplicate_groups=len(duplicate_groups),
            exact_groups=exact_groups,
            near_groups=near_groups,
            possible_fuzzy_pairs=possible_fuzzy_pairs,
            candidate_pairs=len(candidates),
            compared_pairs=compared_pairs,
        ),
    )
