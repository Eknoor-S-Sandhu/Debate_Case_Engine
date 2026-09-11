"""Pydantic domain models for the debate knowledge base."""

from __future__ import annotations

from debate_engine.schemas.chunk import ChunkingMetadata, ChunkLevel, DebateChunk, Freshness
from debate_engine.schemas.document import (
    DebateDocument,
    DocumentType,
    RoundType,
    Side,
    SourceGroup,
)
from debate_engine.schemas.duplicate import (
    DuplicateDetectionResult,
    DuplicateGroup,
    DuplicateStatistics,
    DuplicateType,
)
from debate_engine.schemas.parsed import (
    DocumentFormat,
    ParsedBlock,
    ParsedDocument,
    ParseStatus,
)
from debate_engine.schemas.retrieval import (
    GeneratedQuery,
    JudgeCategory,
    QueryFamily,
    RetrievalCandidate,
    RetrievalRequest,
    RetrievalResult,
    RetrievalStatistics,
    SupportLevel,
)
from debate_engine.schemas.structure import StructuredDocument, StructuredSection

__all__ = [
    "DebateChunk",
    "DebateDocument",
    "ChunkLevel",
    "ChunkingMetadata",
    "DocumentType",
    "DuplicateDetectionResult",
    "DuplicateGroup",
    "DuplicateStatistics",
    "DuplicateType",
    "DocumentFormat",
    "Freshness",
    "GeneratedQuery",
    "JudgeCategory",
    "ParsedBlock",
    "ParsedDocument",
    "ParseStatus",
    "RoundType",
    "QueryFamily",
    "RetrievalCandidate",
    "RetrievalRequest",
    "RetrievalResult",
    "RetrievalStatistics",
    "Side",
    "SourceGroup",
    "StructuredDocument",
    "StructuredSection",
    "SupportLevel",
]
