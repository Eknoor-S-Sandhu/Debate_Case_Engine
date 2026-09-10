"""Chunk-level schema for retrievable pieces of a debate document."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from debate_engine.schemas.document import DocumentType, RoundType, Side, SourceGroup


class Freshness(StrEnum):
    """How time-sensitive the content of a chunk is."""

    CURRENT = "current"
    POSSIBLY_STALE = "possibly_stale"
    STALE_EMPIRICS = "stale_empirics"
    EVERGREEN = "evergreen"
    UNKNOWN = "unknown"


class ChunkLevel(StrEnum):
    """Retrieval granularity represented by a chunk."""

    ARGUMENT = "argument"
    SUBMODULE = "submodule"
    FALLBACK = "fallback"


class ChunkingMetadata(BaseModel):
    """Optional document metadata supplied to chunk generation.

    ``None`` means "infer conservatively"; explicit enum values, including
    ``unknown`` and ``other``, are preserved.
    """

    model_config = ConfigDict(extra="forbid")

    document_id: str | None = None
    source_group: SourceGroup | None = None
    document_type: DocumentType | None = None
    side: Side | None = None
    round_type: RoundType | None = None
    year: int | None = None
    priority_weight: float | None = Field(default=None, ge=0.0)
    freshness: Freshness | None = None


class DebateChunk(BaseModel):
    """An argument or submodule extracted from a debate document.

    ``section_type`` is deliberately a free-form string rather than an enum.
    Debate files label their structure inconsistently - UQ/L/IL/IMPX,
    Harms/Solvency/Impacts, Claim/Warrant/Impact - and a closed enum would
    reject perfectly good structure the moment a file uses a new convention.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    chunk_id: str
    document_id: str

    source_file: str
    source_path: str
    source_group: SourceGroup = SourceGroup.OTHER
    document_type: DocumentType = DocumentType.UNKNOWN

    section_type: str = "unknown"
    chunk_level: ChunkLevel = ChunkLevel.FALLBACK
    original_heading: str | None = None
    argument_heading: str | None = None
    parent_heading: str | None = None
    heading_path: list[str] = Field(default_factory=list)
    parent_argument_id: str | None = None

    side: Side = Side.UNKNOWN
    round_type: RoundType = RoundType.UNKNOWN
    year: int | None = None

    text: str
    token_count: int = Field(default=0, ge=0)

    freshness: Freshness = Freshness.UNKNOWN
    duplicate_group: str | None = None
    priority_weight: float = Field(default=1.0, ge=0.0)
    source_block_indexes: list[int] = Field(default_factory=list)
    structure_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    is_special_masterfile: bool = False
    special_masterfile_name: str | None = None

    @field_validator("section_type")
    @classmethod
    def _clean_section_type(cls, value: str) -> str:
        """Trim surrounding whitespace while preserving debate casing."""
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("section_type must not be empty")
        return cleaned

    @field_validator("text")
    @classmethod
    def _require_nonempty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("chunk text must not be empty")
        return value
