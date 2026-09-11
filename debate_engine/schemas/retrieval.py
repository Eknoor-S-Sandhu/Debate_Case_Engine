"""Inspectable schemas for deterministic hierarchical retrieval."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from debate_engine.schemas.chunk import DebateChunk
from debate_engine.schemas.document import RoundType, Side, SourceGroup


class JudgeCategory(StrEnum):
    TECH = "tech"
    FLOW = "flow"
    FLAY = "flay"
    FULLY_LAY = "fully_lay"


class QueryFamily(StrEnum):
    FULL_MOTION = "full_motion"
    CORE_CONCEPT = "core_concept"
    MECHANISM = "mechanism"
    IMPACT = "impact"
    SIDE_AWARE = "side_aware"
    EXPLICIT = "explicit"


class SupportLevel(StrEnum):
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"


class RetrievalRequest(BaseModel):
    """Round context consumed directly by retrieval, independent of agents."""

    model_config = ConfigDict(extra="forbid")

    motion: str
    side: Side | None = None
    round_type: RoundType | None = None
    prep_format: str | None = None
    judge_category: JudgeCategory | None = None
    judge_notes: str | None = None
    desired_top_k: int | None = Field(default=None, ge=1)
    desired_arguments: int | None = Field(default=None, ge=0)
    desired_submodules: int | None = Field(default=None, ge=0)
    include_theory: bool | None = None
    include_kritiks: bool | None = None
    current_year: int | None = Field(default=None, ge=1900)
    explicit_concepts: list[str] = Field(default_factory=list)
    user_queries: list[str] = Field(default_factory=list)
    source_group: SourceGroup | None = None

    @field_validator("motion")
    @classmethod
    def _require_motion(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("motion must not be empty")
        return cleaned


class GeneratedQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    family: QueryFamily
    text: str


class RetrievalCandidate(BaseModel):
    """One hydrated chunk with every deterministic score component exposed."""

    model_config = ConfigDict(extra="forbid")

    chunk_id: str
    chunk: DebateChunk
    semantic_score: float = 0.0
    lexical_score: float = 0.0
    concept_score: float = 0.0
    heading_score: float = 0.0
    base_score: float = 0.0
    source_score: float = 0.0
    masterfile_score: float = 0.0
    motion_similarity_score: float = 0.0
    section_fit_score: float = 0.0
    compatibility_score: float = 0.0
    freshness_score: float = 0.0
    redundancy_penalty: float = 0.0
    final_score: float = 0.0
    support_score: float = Field(default=0.0, ge=0.0, le=1.0)
    support_level: SupportLevel = SupportLevel.LOW
    semantic_query_matches: int = Field(default=0, ge=0)
    lexical_query_matches: int = Field(default=0, ge=0)
    rank: int | None = Field(default=None, ge=1)
    reasons: list[str] = Field(default_factory=list)
    parent_argument: DebateChunk | None = None
    related_children: list[DebateChunk] = Field(default_factory=list)


class RetrievalStatistics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    semantic_hits: int = Field(default=0, ge=0)
    lexical_hits: int = Field(default=0, ge=0)
    merged_candidates: int = Field(default=0, ge=0)
    hydrated_candidates: int = Field(default=0, ge=0)
    ineligible_candidates: int = Field(default=0, ge=0)
    duplicate_candidates_suppressed: int = Field(default=0, ge=0)
    redundant_candidates_suppressed: int = Field(default=0, ge=0)
    below_relevance_threshold: int = Field(default=0, ge=0)
    full_arguments_returned: int = Field(default=0, ge=0)
    submodules_returned: int = Field(default=0, ge=0)


class RetrievalResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request: RetrievalRequest
    generated_queries: list[GeneratedQuery]
    full_arguments: list[RetrievalCandidate]
    submodules: list[RetrievalCandidate]
    statistics: RetrievalStatistics
    warnings: list[str] = Field(default_factory=list)
