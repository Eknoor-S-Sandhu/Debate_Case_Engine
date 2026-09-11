"""Round planning and source-grounded knowledge handoff contracts."""

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from debate_engine.schemas.adaptation import JudgeProfile, ResearchPacket
from debate_engine.schemas.retrieval import (
    GeneratedQuery,
    RetrievalCandidate,
    RetrievalRequest,
    RetrievalStatistics,
)


class PrepRules(BaseModel):
    model_config = ConfigDict(extra="forbid")

    minutes: int = Field(default=15, ge=1, le=180)
    internet_allowed: bool = False
    notes: str | None = None


class RoundInput(RetrievalRequest):
    """Explicit round context; inherited retrieval overrides remain authoritative."""

    prep_rules: PrepRules = Field(default_factory=PrepRules)
    current_year: int = Field(default_factory=lambda: date.today().year, ge=1900)


class RoundPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    round_input: RoundInput
    retrieval_request: RetrievalRequest
    generated_queries: list[GeneratedQuery]
    research_permitted: bool
    research_status: str
    judge_profile: JudgeProfile | None = None
    notes: list[str] = Field(default_factory=list)


class KnowledgeCategory(StrEnum):
    RELATED_ARGUMENTS = "related_arguments"
    UNIQUENESS = "uniqueness"
    LINKS = "links"
    INTERNAL_LINKS = "internal_links"
    WARRANTS = "warrants"
    SOLVENCY = "solvency"
    IMPACTS = "impacts"
    PREEMPTS = "preempts"
    FRAMEWORKS = "frameworks"
    THEORY_K_OPTIONS = "theory_k_options"
    OTHER_MODULES = "other_modules"


class KnowledgeItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate: RetrievalCandidate
    category: KnowledgeCategory
    verification_notes: list[str] = Field(default_factory=list)


class KnowledgePacket(BaseModel):
    """Original text stored once per selected chunk, grouped by reference IDs.

    Related arguments are argument-level excerpts, not reconstructed full cases.
    Coverage gaps describe this retrieval, never the entire archive.
    """

    model_config = ConfigDict(extra="forbid")

    plan: RoundPlan
    items: dict[str, KnowledgeItem] = Field(default_factory=dict)
    groups: dict[KnowledgeCategory, list[str]] = Field(default_factory=dict)
    coverage_gaps: list[KnowledgeCategory] = Field(default_factory=list)
    statistics: RetrievalStatistics
    research: ResearchPacket | None = None
    warnings: list[str] = Field(default_factory=list)
