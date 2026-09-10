"""Duplicate-cluster output models."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from debate_engine.schemas.chunk import DebateChunk


class DuplicateType(StrEnum):
    """How members of a duplicate group were matched."""

    EXACT = "exact"
    NEAR = "near"


class DuplicateGroup(BaseModel):
    """A preserved set of interchangeable or near-interchangeable chunks."""

    model_config = ConfigDict(extra="forbid")

    duplicate_group_id: str
    member_chunk_ids: list[str]
    representative_chunk_id: str
    duplicate_type: DuplicateType
    similarity_min: float = Field(ge=0.0, le=1.0)
    similarity_max: float = Field(ge=0.0, le=1.0)
    notes: list[str] = Field(default_factory=list)


class DuplicateStatistics(BaseModel):
    """Audit counters for grouping and candidate-blocking effectiveness."""

    model_config = ConfigDict(extra="forbid")

    total_chunks: int = Field(ge=0)
    grouped_chunks: int = Field(ge=0)
    singleton_chunks: int = Field(ge=0)
    duplicate_groups: int = Field(ge=0)
    exact_groups: int = Field(ge=0)
    near_groups: int = Field(ge=0)
    possible_fuzzy_pairs: int = Field(ge=0)
    candidate_pairs: int = Field(ge=0)
    compared_pairs: int = Field(ge=0)


class DuplicateDetectionResult(BaseModel):
    """Non-destructive duplicate detection result."""

    model_config = ConfigDict(extra="forbid")

    updated_chunks: list[DebateChunk]
    duplicate_groups: list[DuplicateGroup]
    statistics: DuplicateStatistics
