"""Deterministic debate-heading detection and hierarchy construction."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from debate_engine.config import StructureDetectionSettings, get_settings
from debate_engine.ingestion.structure_rules import HeadingRuleMatch, match_debate_heading
from debate_engine.schemas import (
    ParsedBlock,
    ParsedDocument,
    ParseStatus,
    StructuredDocument,
    StructuredSection,
)

_MARKDOWN_HEADING = re.compile(r"^(?P<marks>#{1,6})\s+(?P<text>.+?)\s*#*\s*$")

_CONTAINER_TYPES = frozenset(
    {
        "advantage",
        "disadvantage",
        "contention",
        "theory_shell",
        "kritik",
    }
)
_THEORY_CHILD_TYPES = frozenset(
    {
        "answer",
        "competing_interpretations",
        "counter_interpretation",
        "counter_standards",
        "drop_the_argument",
        "drop_the_team",
        "interpretation",
        "reasonability",
        "standards",
        "violation",
        "voters",
        "weighing_mechanism",
    }
)
_KRITIK_CHILD_TYPES = frozenset(
    {
        "alternative",
        "framework",
        "impact",
        "internal_link",
        "link",
        "permutation",
        "role_of_the_ballot",
        "root_cause",
        "thesis",
    }
)
_CASE_CHILD_TYPES = frozenset(
    {
        "claim",
        "comparative",
        "counterplan",
        "defense",
        "framework",
        "harms",
        "impact",
        "inherency",
        "internal_link",
        "link",
        "mechanism",
        "offense",
        "plan",
        "problem",
        "solvency",
        "uniqueness",
        "warrant",
    }
)


@dataclass(frozen=True, slots=True)
class _HeadingCandidate:
    section_type: str
    normalized_heading: str
    confidence: float
    detection_method: str
    style_level: int | None = None
    outline_depth: int | None = None


def _is_short_heading(text: str, settings: StructureDetectionSettings) -> bool:
    words = text.rstrip(":").split()
    return (
        bool(words)
        and "\n" not in text
        and len(text) <= settings.max_heading_characters
        and len(words) <= settings.max_heading_words
    )


def _has_terminal_sentence_punctuation(text: str) -> bool:
    return text.rstrip().endswith((".", "?", "!", ";"))


def _generic_candidate(
    text: str,
    block: ParsedBlock,
    settings: StructureDetectionSettings,
    *,
    markdown_level: int | None,
) -> _HeadingCandidate | None:
    if not _is_short_heading(text, settings):
        return None

    normalized = text.rstrip(":").strip()
    style_level = block.heading_level or markdown_level
    if style_level is not None:
        method = "docx_heading_style" if block.heading_level else "markdown_heading"
        return _HeadingCandidate(
            section_type="heading",
            normalized_heading=normalized,
            confidence=settings.style_heading_confidence,
            detection_method=method,
            style_level=style_level,
        )

    formatted = block.contains_bold or block.contains_underline or block.contains_highlight
    if formatted and not _has_terminal_sentence_punctuation(text):
        signals = [
            label
            for enabled, label in (
                (block.contains_bold, "bold"),
                (block.contains_underline, "underline"),
                (block.contains_highlight, "highlight"),
            )
            if enabled
        ]
        return _HeadingCandidate(
            section_type="heading",
            normalized_heading=normalized,
            confidence=settings.formatted_heading_confidence,
            detection_method=f"formatted_short_line:{'+'.join(signals)}",
        )

    letters = [character for character in text if character.isalpha()]
    if (
        letters
        and all(character.isupper() for character in letters)
        and not _has_terminal_sentence_punctuation(text)
    ):
        return _HeadingCandidate(
            section_type="heading",
            normalized_heading=normalized,
            confidence=settings.uppercase_heading_confidence,
            detection_method="uppercase_short_line",
        )

    if text.endswith(":"):
        return _HeadingCandidate(
            section_type="heading",
            normalized_heading=normalized,
            confidence=settings.colon_heading_confidence,
            detection_method="short_colon_line",
        )
    return None


def _detect_heading(
    block: ParsedBlock,
    settings: StructureDetectionSettings,
) -> _HeadingCandidate | None:
    original_text = block.text.strip()
    if not original_text:
        return None

    markdown_match = _MARKDOWN_HEADING.fullmatch(original_text)
    markdown_level = len(markdown_match.group("marks")) if markdown_match else None
    heading_text = markdown_match.group("text") if markdown_match else original_text
    if not _is_short_heading(heading_text, settings):
        return None

    semantic_match: HeadingRuleMatch | None = match_debate_heading(heading_text)
    if semantic_match:
        methods: list[str] = []
        is_plain_subpoint = semantic_match.section_type == "subpoint"
        confidence = (
            settings.numbered_heading_confidence
            if is_plain_subpoint
            else settings.keyword_heading_confidence
        )
        style_level = block.heading_level or markdown_level
        if block.heading_level is not None:
            methods.append("docx_heading_style")
            confidence = max(confidence, settings.style_heading_confidence)
        elif markdown_level is not None:
            methods.append("markdown_heading")
            confidence = max(confidence, settings.style_heading_confidence)
        if not is_plain_subpoint:
            methods.append("debate_keyword")
        if semantic_match.outline_depth is not None:
            methods.append("numbering")
            confidence = max(confidence, settings.numbered_heading_confidence)
        return _HeadingCandidate(
            section_type=semantic_match.section_type,
            normalized_heading=semantic_match.normalized_heading,
            confidence=confidence,
            detection_method="+".join(methods),
            style_level=style_level,
            outline_depth=semantic_match.outline_depth,
        )

    return _generic_candidate(
        heading_text,
        block,
        settings,
        markdown_level=markdown_level,
    )


def _compatible_parent(
    candidate: _HeadingCandidate,
    stack: list[StructuredSection],
) -> StructuredSection | None:
    if candidate.section_type in _THEORY_CHILD_TYPES:
        accepted_parents = {"theory_shell"}
    elif candidate.section_type in _KRITIK_CHILD_TYPES:
        accepted_parents = {"kritik", "advantage", "disadvantage", "contention"}
    elif candidate.section_type in _CASE_CHILD_TYPES:
        accepted_parents = {"advantage", "disadvantage", "contention", "kritik"}
    else:
        return None

    return next(
        (section for section in reversed(stack) if section.section_type in accepted_parents),
        None,
    )


def _desired_level(
    candidate: _HeadingCandidate,
    stack: list[StructuredSection],
) -> tuple[int, StructuredSection | None]:
    if candidate.outline_depth is not None:
        outline_anchor = next(
            (section for section in reversed(stack) if section.section_type != "subpoint"),
            None,
        )
        base_level = outline_anchor.level if outline_anchor else 0
        # Numeric depth and the active stack together identify the direct
        # parent (e.g. ``a.`` remains under the current ``1.`` subpoint).
        return base_level + candidate.outline_depth, None

    semantic_parent = _compatible_parent(candidate, stack)
    if semantic_parent is not None:
        return semantic_parent.level + 1, semantic_parent

    if candidate.style_level is not None:
        return candidate.style_level, None

    if candidate.section_type == "heading" and stack and stack[-1].section_type != "heading":
        return stack[-1].level + 1, stack[-1]

    if candidate.section_type in _CONTAINER_TYPES:
        return 1, None
    return 1, None


def _append_body(
    section: StructuredSection,
    block: ParsedBlock,
    body_parts: dict[str, list[str]],
) -> None:
    section.source_block_indexes.append(block.index)
    body_parts[section.section_id].append(block.text)


def _warn_once(warnings: list[str], message: str) -> None:
    if message not in warnings:
        warnings.append(message)


def detect_structure(
    document: ParsedDocument,
    *,
    settings: StructureDetectionSettings | None = None,
) -> StructuredDocument:
    """Detect debate sections while preserving all source blocks and text."""
    configured = settings or get_settings().structure_detection
    source_key = document.source_path.resolve().as_posix()
    document_id = hashlib.sha256(source_key.encode("utf-8")).hexdigest()[:16]
    roots: list[StructuredSection] = []
    stack: list[StructuredSection] = []
    orphan_blocks: list[ParsedBlock] = []
    warnings: list[str] = []
    body_parts: dict[str, list[str]] = {}
    detected_title: str | None = None
    section_count = 0

    if document.parse_status is not ParseStatus.SUCCESS:
        _warn_once(
            warnings,
            f"Source parse status is {document.parse_status.value}; structure may be incomplete.",
        )

    for block in document.blocks:
        candidate = _detect_heading(block, configured)
        if candidate is None or candidate.confidence < configured.minimum_section_confidence:
            if stack:
                _append_body(stack[-1], block, body_parts)
            else:
                orphan_blocks.append(block)
            continue

        desired_level, preferred_parent = _desired_level(candidate, stack)
        while stack and stack[-1].level >= desired_level:
            stack.pop()

        if preferred_parent is not None:
            while stack and stack[-1].section_id != preferred_parent.section_id:
                stack.pop()

        if stack and desired_level > stack[-1].level + 1:
            _warn_once(
                warnings,
                (
                    f"Heading at source block {block.index} jumped from level "
                    f"{stack[-1].level} to {desired_level}; normalized to "
                    f"level {stack[-1].level + 1}."
                ),
            )
            desired_level = stack[-1].level + 1
        elif not stack and desired_level > 1:
            _warn_once(
                warnings,
                (
                    f"Heading at source block {block.index} begins at level "
                    f"{desired_level} without a detected parent; preserved as a root."
                ),
            )

        parent = stack[-1] if stack and stack[-1].level < desired_level else None
        section_id = f"{document_id}:section:{section_count:04d}"
        section = StructuredSection(
            section_id=section_id,
            section_type=candidate.section_type,
            original_heading=block.text,
            normalized_heading=candidate.normalized_heading,
            level=desired_level,
            order_index=section_count,
            parent_section_id=parent.section_id if parent else None,
            source_block_indexes=[block.index],
            confidence=candidate.confidence,
            detection_method=candidate.detection_method,
            heading_style_name=block.style_name,
            heading_contains_bold=block.contains_bold,
            heading_contains_italic=block.contains_italic,
            heading_contains_underline=block.contains_underline,
            heading_contains_highlight=block.contains_highlight,
        )
        body_parts[section_id] = []
        if parent:
            parent.children.append(section)
        else:
            roots.append(section)
        stack.append(section)
        section_count += 1

        if detected_title is None and (
            candidate.style_level == 1 or candidate.detection_method.startswith("markdown_heading")
        ):
            detected_title = candidate.normalized_heading

    all_sections = [section for root in roots for section in root.iter_sections()]
    for section in all_sections:
        section.text = "\n".join(body_parts[section.section_id])

    nonempty_orphans = [block for block in orphan_blocks if block.text.strip()]
    if nonempty_orphans:
        _warn_once(
            warnings,
            f"{len(nonempty_orphans)} non-empty source block(s) precede any detected heading.",
        )
    if not all_sections:
        _warn_once(
            warnings,
            "No reliable debate structure was detected; all source blocks remain unstructured.",
        )

    confidence = (
        sum(section.confidence for section in all_sections) / len(all_sections)
        if all_sections
        else 0.0
    )
    return StructuredDocument(
        document_id=document_id,
        source_path=document.source_path,
        filename=document.filename,
        title=detected_title or document.source_path.stem,
        sections=roots,
        unstructured_text="\n".join(block.text for block in orphan_blocks),
        orphan_blocks=orphan_blocks,
        detection_warnings=warnings,
        overall_structure_confidence=round(confidence, 4),
    )
