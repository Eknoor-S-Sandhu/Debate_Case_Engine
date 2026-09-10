"""Document-level metadata assembly for persistence.

Chunking already infers provenance for every chunk it emits. This module reuses
exactly that inference so a stored ``documents`` row can never disagree with
the ``chunks`` rows that belong to it.
"""

from __future__ import annotations

from debate_engine.config import Settings, get_settings
from debate_engine.ingestion.chunking import resolve_document_metadata
from debate_engine.schemas import (
    ChunkingMetadata,
    DebateDocument,
    ParsedDocument,
    SourceGroup,
    StructuredDocument,
)


def build_debate_document(
    parsed_document: ParsedDocument,
    structured_document: StructuredDocument,
    *,
    source_group: SourceGroup | None = None,
    year: int | None = None,
    settings: Settings | None = None,
) -> DebateDocument:
    """Assemble a persistable document from parser and structure output.

    ``source_group`` overrides folder-based inference, which matters when
    discovery resolved provenance relative to an archive root that the
    structure detector never saw. Original text is preserved verbatim.
    """
    resolved = resolve_document_metadata(
        structured_document,
        ChunkingMetadata(source_group=source_group, year=year),
        settings=settings or get_settings(),
    )
    return DebateDocument(
        document_id=resolved.document_id,
        filename=parsed_document.filename,
        full_path=str(parsed_document.source_path),
        source_group=resolved.source_group,
        document_type=resolved.document_type,
        side=resolved.side,
        round_type=resolved.round_type,
        year=resolved.year,
        title=structured_document.title,
        raw_text=parsed_document.raw_text,
        priority_weight=resolved.priority_weight,
    )
