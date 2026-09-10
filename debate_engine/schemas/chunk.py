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
    original_heading: str | None = None
    parent_argument_id: str | None = None

    side: Side = Side.UNKNOWN
    round_type: RoundType = RoundType.UNKNOWN

    text: str
    token_count: int = Field(default=0, ge=0)

    freshness: Freshness = Freshness.UNKNOWN
    duplicate_group: str | None = None
    priority_weight: float = Field(default=1.0, ge=0.0)

    @field_validator("section_type")
    @classmethod
    def _clean_section_type(cls, value: str) -> str:
        """Trim surrounding whitespace while preserving debate casing."""
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("section_type must not be empty")
        return cleaned
