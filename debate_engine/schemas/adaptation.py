"""Judge adaptation and cited research handoff schemas."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from debate_engine.schemas.retrieval import JudgeCategory


class JudgeProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: JudgeCategory | None = None
    classification_source: Literal["explicit", "notes", "unknown"] = "unknown"
    original_notes: str | None = None
    matched_signals: list[str] = Field(default_factory=list)
    preferences: list[str] = Field(default_factory=list)
    guidance: list[str] = Field(default_factory=list)
    exclude_theory: bool = False
    exclude_kritiks: bool = False
    warnings: list[str] = Field(default_factory=list)


class ResearchSource(BaseModel):
    """Provider search excerpt, not verified evidence or a generated factual claim."""

    model_config = ConfigDict(extra="forbid")

    source_id: str
    title: str
    url: str
    excerpt: str
    published_date: date | None = None
    retrieved_at: datetime
    query_matches: list[str] = Field(default_factory=list)
    verification_status: Literal["unverified_search_excerpt"] = "unverified_search_excerpt"
    notes: list[str] = Field(default_factory=list)


class ResearchPacket(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal[
        "disabled_by_prep_rules",
        "missing_credentials",
        "completed",
        "partial",
        "failed",
        "no_results",
    ]
    queries: list[str] = Field(default_factory=list)
    sources: list[ResearchSource] = Field(default_factory=list)
    queries_attempted: int = 0
    queries_completed: int = 0
    verification_chunk_ids: list[str] = Field(default_factory=list)
    coverage_gaps: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
