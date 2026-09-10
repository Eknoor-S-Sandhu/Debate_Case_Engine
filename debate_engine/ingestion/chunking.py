"""Debate-semantic argument, submodule, and fallback chunk generation."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from debate_engine.config import ChunkingSettings, Settings, get_settings
from debate_engine.ingestion.discovery import infer_source_group
from debate_engine.schemas import (
    ChunkingMetadata,
    ChunkLevel,
    DebateChunk,
    DebateDocument,
    DocumentType,
    Freshness,
    RoundType,
    Side,
    SourceGroup,
    StructuredDocument,
    StructuredSection,
)

_TOKEN_PATTERN = re.compile(r"\w+|[^\w\s]", re.UNICODE)

_STRONG_ARGUMENT_TYPES = frozenset(
    {
        "advantage",
        "answer",
        "contention",
        "disadvantage",
        "kritik",
        "theory_shell",
    }
)
_INHERITABLE_CONTEXT_TYPES = frozenset(
    {
        "alternative",
        "answer",
        "claim",
        "counter_interpretation",
        "counter_standards",
        "framework",
        "framing",
        "harms",
        "impact",
        "impact_calculus",
        "inherency",
        "internal_link",
        "interpretation",
        "link",
        "solvency",
        "standards",
        "uniqueness",
        "value",
        "value_criterion",
        "voters",
        "warrant",
    }
)


@dataclass(frozen=True, slots=True)
class _ResolvedMetadata:
    document_id: str
    source_group: SourceGroup
    document_type: DocumentType
    side: Side
    round_type: RoundType
    year: int | None
    priority_weight: float
    freshness: Freshness
    is_special_masterfile: bool
    special_masterfile_name: str | None


@dataclass(frozen=True, slots=True)
class _FallbackUnit:
    text: str
    source_block_indexes: tuple[int, ...]
    token_count: int


def approximate_token_count(text: str) -> int:
    """Count word and punctuation tokens without loading an embedding model."""
    return len(_TOKEN_PATTERN.findall(text))


def _all_section_types(document: StructuredDocument) -> list[str]:
    return [section.section_type for section in document.iter_sections()]


def _infer_document_type(document: StructuredDocument, *, special: bool) -> DocumentType:
    filename = document.filename.casefold()
    path_parts = {
        re.sub(r"[^a-z0-9]+", " ", part.casefold()).strip()
        for part in document.source_path.parts[:-1]
    }
    section_types = _all_section_types(document)
    root_types = [section.section_type for section in document.sections]

    if special or "case file" in filename or "theory file" in filename:
        return DocumentType.MASTERFILE
    if "fact sheet" in filename:
        return DocumentType.FACT_SHEET
    if any(part == "theory" or part.startswith("theory ") for part in path_parts):
        return DocumentType.THEORY
    if any(
        part in {"k", "ks", "kritik", "kritiks"} or part.startswith("kritik ")
        for part in path_parts
    ):
        return DocumentType.KRITIK
    if "theory_shell" in section_types:
        return DocumentType.THEORY
    if "kritik" in section_types:
        return DocumentType.KRITIK
    if root_types and all(section_type == "answer" for section_type in root_types):
        return DocumentType.BLOCK
    if any(
        section_type in {"advantage", "contention", "disadvantage"}
        for section_type in section_types
    ):
        return DocumentType.CASE
    return DocumentType.UNKNOWN


def _infer_side(path: Path) -> Side:
    tokens = set(re.findall(r"[a-z]+", path.as_posix().casefold()))
    detected: set[Side] = set()
    if tokens & {"aff", "affirmative"}:
        detected.add(Side.AFF)
    if tokens & {"neg", "negative"}:
        detected.add(Side.NEG)
    if tokens & {"gov", "government"}:
        detected.add(Side.GOV)
    if tokens & {"opp", "opposition"}:
        detected.add(Side.OPP)
    return next(iter(detected)) if len(detected) == 1 else Side.UNKNOWN


def _infer_round_type(document: StructuredDocument) -> RoundType:
    section_types = set(_all_section_types(document))
    if {"value", "value_criterion"} <= section_types:
        return RoundType.VALUE
    if "threshold_of_truth" in section_types:
        return RoundType.FACT
    if section_types & {
        "advantage",
        "counterplan",
        "disadvantage",
        "inherency",
        "internal_link",
        "plan",
        "uniqueness",
    }:
        return RoundType.POLICY
    return RoundType.UNKNOWN


def _special_masterfile_name(document: StructuredDocument, settings: Settings) -> str | None:
    stem = Path(document.filename).stem.casefold()
    return next(
        (name for name in settings.special_masterfiles if name.casefold() == stem),
        None,
    )


def _priority_weight(
    source_group: SourceGroup,
    *,
    special: bool,
    settings: Settings,
) -> float:
    if special:
        return settings.source_weights.personal_masterfile
    return {
        SourceGroup.PERSONAL: settings.source_weights.personal,
        SourceGroup.PAST_CASE: settings.source_weights.past_case,
        SourceGroup.OTHER: settings.source_weights.other,
    }[source_group]


def _resolve_metadata(
    document: StructuredDocument,
    metadata: ChunkingMetadata | DebateDocument | None,
    settings: Settings,
) -> _ResolvedMetadata:
    special_name = _special_masterfile_name(document, settings)
    special = special_name is not None

    if isinstance(metadata, DebateDocument):
        return _ResolvedMetadata(
            document_id=metadata.document_id,
            source_group=metadata.source_group,
            document_type=metadata.document_type,
            side=metadata.side,
            round_type=metadata.round_type,
            year=metadata.year,
            priority_weight=metadata.priority_weight,
            freshness=Freshness.UNKNOWN,
            is_special_masterfile=special,
            special_masterfile_name=special_name,
        )

    supplied = metadata or ChunkingMetadata()
    inferred_source_group = (
        SourceGroup.PERSONAL if special else infer_source_group(document.source_path)
    )
    source_group = supplied.source_group or inferred_source_group
    document_type = supplied.document_type or _infer_document_type(document, special=special)
    side = supplied.side or _infer_side(document.source_path)
    round_type = supplied.round_type or _infer_round_type(document)
    priority_weight = (
        supplied.priority_weight
        if supplied.priority_weight is not None
        else _priority_weight(source_group, special=special, settings=settings)
    )
    return _ResolvedMetadata(
        document_id=supplied.document_id or document.document_id,
        source_group=source_group,
        document_type=document_type,
        side=side,
        round_type=round_type,
        year=supplied.year,
        priority_weight=priority_weight,
        freshness=supplied.freshness or Freshness.UNKNOWN,
        is_special_masterfile=special,
        special_masterfile_name=special_name,
    )


def _section_heading(section: StructuredSection) -> str | None:
    return section.original_heading or section.normalized_heading


def _subtree_parts(section: StructuredSection) -> list[str]:
    parts: list[str] = []
    heading = _section_heading(section)
    if heading and heading.strip():
        parts.append(heading)
    if section.text.strip():
        parts.append(section.text)
    for child in section.children:
        parts.extend(_subtree_parts(child))
    return parts


def _subtree_source_indexes(section: StructuredSection) -> list[int]:
    indexes = set(section.source_block_indexes)
    for child in section.children:
        indexes.update(_subtree_source_indexes(child))
    return sorted(indexes)


def _section_paths(
    document: StructuredDocument,
) -> tuple[
    dict[str, list[StructuredSection]],
    dict[str, StructuredSection | None],
]:
    paths: dict[str, list[StructuredSection]] = {}
    parents: dict[str, StructuredSection | None] = {}

    def visit(
        section: StructuredSection,
        ancestors: list[StructuredSection],
        parent: StructuredSection | None,
    ) -> None:
        paths[section.section_id] = [*ancestors, section]
        parents[section.section_id] = parent
        for child in section.children:
            visit(child, [*ancestors, section], section)

    for root in document.sections:
        visit(root, [], None)
    return paths, parents


def _nearest_strong_argument_descendants(
    section: StructuredSection,
) -> list[StructuredSection]:
    matches: list[StructuredSection] = []
    for child in section.children:
        if child.section_type in _STRONG_ARGUMENT_TYPES:
            matches.append(child)
        else:
            matches.extend(_nearest_strong_argument_descendants(child))
    return matches


def _argument_nodes(document: StructuredDocument) -> list[StructuredSection]:
    arguments: list[StructuredSection] = []
    for root in document.sections:
        if root.section_type in _STRONG_ARGUMENT_TYPES:
            arguments.append(root)
            continue

        strong_descendants = _nearest_strong_argument_descendants(root)
        if strong_descendants:
            arguments.extend(strong_descendants)
            continue

        # Broad masterfile organizers often have no body of their own. Their
        # named child modules are more coherent arguments than one merged file.
        if (
            not root.text.strip()
            and root.children
            and (
                root.section_type == "heading"
                or any(child.section_type == "heading" for child in root.children)
            )
        ):
            arguments.extend(root.children)
            continue
        arguments.append(root)
    return sorted(arguments, key=lambda section: section.order_index)


def _chunk_id(document_id: str, level: ChunkLevel, node_key: str) -> str:
    digest = hashlib.sha256(f"{document_id}|{level.value}|{node_key}".encode()).hexdigest()[:24]
    return f"{document_id}:{level.value}:{digest}"


def _heading_path(path: list[StructuredSection]) -> list[str]:
    return [
        heading
        for section in path
        if (heading := _section_heading(section)) is not None and heading.strip()
    ]


def _assemble_contextual_text(
    section: StructuredSection,
    path: list[StructuredSection],
) -> str:
    context_headings = [
        heading
        for ancestor in path[:-1]
        if (heading := _section_heading(ancestor)) is not None and heading.strip()
    ]
    return "\n\n".join([*context_headings, *_subtree_parts(section)])


def _contextual_source_indexes(
    section: StructuredSection,
    path: list[StructuredSection],
) -> list[int]:
    indexes = set(_subtree_source_indexes(section))
    for ancestor in path[:-1]:
        if ancestor.source_block_indexes:
            # The detector always stores the heading block first.
            indexes.add(ancestor.source_block_indexes[0])
    return sorted(indexes)


def _base_chunk_fields(
    document: StructuredDocument,
    resolved: _ResolvedMetadata,
) -> dict[str, object]:
    return {
        "document_id": resolved.document_id,
        "source_file": document.filename,
        "source_path": str(document.source_path),
        "source_group": resolved.source_group,
        "document_type": resolved.document_type,
        "side": resolved.side,
        "round_type": resolved.round_type,
        "year": resolved.year,
        "freshness": resolved.freshness,
        "priority_weight": resolved.priority_weight,
        "is_special_masterfile": resolved.is_special_masterfile,
        "special_masterfile_name": resolved.special_masterfile_name,
    }


def _argument_chunk(
    section: StructuredSection,
    *,
    document: StructuredDocument,
    path: list[StructuredSection],
    resolved: _ResolvedMetadata,
) -> DebateChunk:
    text = _assemble_contextual_text(section, path)
    parent = path[-2] if len(path) > 1 else None
    return DebateChunk(
        **_base_chunk_fields(document, resolved),
        chunk_id=_chunk_id(resolved.document_id, ChunkLevel.ARGUMENT, section.section_id),
        section_type=_effective_submodule_type(section, path),
        chunk_level=ChunkLevel.ARGUMENT,
        original_heading=_section_heading(section),
        argument_heading=_section_heading(section),
        parent_heading=_section_heading(parent) if parent else None,
        heading_path=_heading_path(path),
        text=text,
        token_count=approximate_token_count(text),
        source_block_indexes=_contextual_source_indexes(section, path),
        structure_confidence=section.confidence,
    )


def _is_broad_organizer(section: StructuredSection) -> bool:
    return (
        not section.text.strip()
        and bool(section.children)
        and any(child.section_type == "heading" for child in section.children)
    )


def _effective_submodule_type(
    section: StructuredSection,
    path: list[StructuredSection],
) -> str:
    if section.section_type != "heading":
        return section.section_type
    return next(
        (
            ancestor.section_type
            for ancestor in reversed(path[:-1])
            if ancestor.section_type in _INHERITABLE_CONTEXT_TYPES
        ),
        section.section_type,
    )


def _descendants(section: StructuredSection) -> list[StructuredSection]:
    return [descendant for child in section.children for descendant in child.iter_sections()]


def _is_promoted_organizer_module(
    section: StructuredSection,
    path: list[StructuredSection],
) -> bool:
    """Identify a named module promoted out of a broad masterfile category."""
    return (
        section.section_type == "heading"
        and len(path) > 1
        and _effective_submodule_type(section, path) != "heading"
    )


def _submodule_chunk(
    section: StructuredSection,
    *,
    argument: StructuredSection,
    argument_chunk_id: str,
    document: StructuredDocument,
    path: list[StructuredSection],
    parent: StructuredSection | None,
    resolved: _ResolvedMetadata,
) -> DebateChunk:
    text = _assemble_contextual_text(section, path)
    return DebateChunk(
        **_base_chunk_fields(document, resolved),
        chunk_id=_chunk_id(resolved.document_id, ChunkLevel.SUBMODULE, section.section_id),
        section_type=_effective_submodule_type(section, path),
        chunk_level=ChunkLevel.SUBMODULE,
        original_heading=_section_heading(section),
        argument_heading=_section_heading(argument),
        parent_heading=_section_heading(parent) if parent else None,
        heading_path=_heading_path(path),
        parent_argument_id=argument_chunk_id,
        text=text,
        token_count=approximate_token_count(text),
        source_block_indexes=_contextual_source_indexes(section, path),
        structure_confidence=section.confidence,
    )


def _split_oversized_text(
    text: str,
    source_block_index: int,
    settings: ChunkingSettings,
) -> list[_FallbackUnit]:
    matches = list(_TOKEN_PATTERN.finditer(text))
    if not matches:
        return []

    units: list[_FallbackUnit] = []
    start = 0
    while start < len(matches):
        end = min(start + settings.fallback_max_tokens, len(matches))
        character_start = 0 if start == 0 else matches[start].start()
        character_end = len(text) if end == len(matches) else matches[end].start()
        segment = text[character_start:character_end].strip()
        if segment:
            units.append(
                _FallbackUnit(
                    text=segment,
                    source_block_indexes=(source_block_index,),
                    token_count=approximate_token_count(segment),
                )
            )
        if end == len(matches):
            break
        next_start = end - settings.fallback_overlap_tokens
        start = next_start if next_start > start else end
    return units


def _fallback_units(
    document: StructuredDocument,
    settings: ChunkingSettings,
) -> list[_FallbackUnit]:
    units: list[_FallbackUnit] = []
    for block in document.orphan_blocks:
        if not block.text.strip():
            continue
        token_count = approximate_token_count(block.text)
        if token_count > settings.fallback_max_tokens:
            units.extend(_split_oversized_text(block.text, block.index, settings))
        else:
            units.append(
                _FallbackUnit(
                    text=block.text,
                    source_block_indexes=(block.index,),
                    token_count=token_count,
                )
            )

    if not units and document.unstructured_text.strip():
        units.extend(
            _split_oversized_text(
                document.unstructured_text,
                0,
                settings,
            )
        )
    return units


def _overlap_tail(
    units: list[_FallbackUnit],
    overlap_tokens: int,
) -> list[_FallbackUnit]:
    if overlap_tokens <= 0:
        return []
    selected: list[_FallbackUnit] = []
    token_count = 0
    for unit in reversed(units):
        if token_count + unit.token_count > overlap_tokens:
            break
        selected.append(unit)
        token_count += unit.token_count
    return list(reversed(selected))


def _pack_fallback_units(
    units: list[_FallbackUnit],
    settings: ChunkingSettings,
) -> list[list[_FallbackUnit]]:
    groups: list[list[_FallbackUnit]] = []
    current: list[_FallbackUnit] = []
    current_tokens = 0

    for unit in units:
        if current and current_tokens + unit.token_count > settings.fallback_max_tokens:
            groups.append(current)
            current = _overlap_tail(current, settings.fallback_overlap_tokens)
            current_tokens = sum(item.token_count for item in current)
            if current_tokens + unit.token_count > settings.fallback_max_tokens:
                current = []
                current_tokens = 0
        current.append(unit)
        current_tokens += unit.token_count

    if current:
        groups.append(current)
    return groups


def _fallback_chunks(
    document: StructuredDocument,
    *,
    resolved: _ResolvedMetadata,
    settings: ChunkingSettings,
) -> list[DebateChunk]:
    groups = _pack_fallback_units(_fallback_units(document, settings), settings)
    chunks: list[DebateChunk] = []
    for index, group in enumerate(groups):
        text = "\n".join(unit.text for unit in group)
        if not text.strip():
            continue
        source_indexes = sorted(
            {block_index for unit in group for block_index in unit.source_block_indexes}
        )
        node_key = f"{index}|{','.join(str(item) for item in source_indexes)}|{text}"
        chunks.append(
            DebateChunk(
                **_base_chunk_fields(document, resolved),
                chunk_id=_chunk_id(resolved.document_id, ChunkLevel.FALLBACK, node_key),
                section_type="fallback",
                chunk_level=ChunkLevel.FALLBACK,
                text=text,
                token_count=approximate_token_count(text),
                source_block_indexes=source_indexes,
                structure_confidence=document.overall_structure_confidence,
            )
        )
    return chunks


def chunk_structured_document(
    structured_document: StructuredDocument,
    metadata: ChunkingMetadata | DebateDocument | None = None,
    *,
    settings: Settings | None = None,
) -> list[DebateChunk]:
    """Create deterministic debate-semantic chunks without persistence.

    Structured documents produce argument and descendant submodule chunks.
    Size-based fallback is used only when no reliable sections exist.
    """
    configured = settings or get_settings()
    resolved = _resolve_metadata(structured_document, metadata, configured)
    if not structured_document.sections:
        return _fallback_chunks(
            structured_document,
            resolved=resolved,
            settings=configured.chunking,
        )

    paths, parents = _section_paths(structured_document)
    argument_sections = _argument_nodes(structured_document)
    argument_chunks = [
        _argument_chunk(
            section,
            document=structured_document,
            path=paths[section.section_id],
            resolved=resolved,
        )
        for section in argument_sections
    ]
    argument_chunk_ids = {
        section.section_id: chunk.chunk_id
        for section, chunk in zip(argument_sections, argument_chunks, strict=True)
    }

    submodule_chunks: list[DebateChunk] = []
    for argument in argument_sections:
        argument_path = paths[argument.section_id]
        if _is_promoted_organizer_module(argument, argument_path):
            submodule_chunks.append(
                _submodule_chunk(
                    argument,
                    argument=argument,
                    argument_chunk_id=argument_chunk_ids[argument.section_id],
                    document=structured_document,
                    path=argument_path,
                    parent=parents[argument.section_id],
                    resolved=resolved,
                )
            )
        for section in _descendants(argument):
            if _is_broad_organizer(section):
                continue
            submodule_chunks.append(
                _submodule_chunk(
                    section,
                    argument=argument,
                    argument_chunk_id=argument_chunk_ids[argument.section_id],
                    document=structured_document,
                    path=paths[section.section_id],
                    parent=parents[section.section_id],
                    resolved=resolved,
                )
            )
    return [*argument_chunks, *submodule_chunks]
