"""Validated, unranked case architectures for the Strategy Agent handoff."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=3000)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceQuote(StrictModel):
    source_type: Literal["archive", "research"]
    source_id: Text
    text: Text


class Contention(StrictModel):
    title: Text
    argument_style: Literal["substantive", "theory", "kritik"]
    claim: Text
    uniqueness: Text | None
    link: Text | None
    internal_link: Text | None
    warrants: list[Text] = Field(min_length=1, max_length=5)
    impacts: list[Text] = Field(min_length=1, max_length=3)
    preempts: list[Text] = Field(min_length=1, max_length=3)
    basis: Literal["archive_adaptation", "research_informed", "mixed", "new_reasoning"]
    archive_chunk_ids: list[Text] = Field(max_length=8)
    research_source_ids: list[Text] = Field(max_length=8)
    quotes: list[SourceQuote] = Field(max_length=3)
    assumptions: list[Text] = Field(max_length=5)
    needs_verification: list[Text] = Field(max_length=5)

    @model_validator(mode="after")
    def validate_basis(self):
        archive, research = bool(self.archive_chunk_ids), bool(self.research_source_ids)
        if self.basis == "archive_adaptation" and not archive:
            raise ValueError("Archive adaptation requires archive sources.")
        if self.basis == "research_informed" and not research:
            raise ValueError("Research-informed reasoning requires research sources.")
        if self.basis == "mixed" and not (archive and research):
            raise ValueError("Mixed reasoning requires archive and research sources.")
        if self.basis == "new_reasoning" and (archive or research or self.quotes):
            raise ValueError("New reasoning must not claim source support.")
        return self


class Architecture(StrictModel):
    name: Text
    framing: Text
    value: Text | None
    criterion: Text | None
    core_mechanism: Text
    route_to_ballot: Text
    differs_from_others: Text
    contentions: list[Contention] = Field(min_length=2, max_length=3)
    judge_adaptation: Text
    why_this_can_win: Text
    main_vulnerability: Text


class ArchitectureSet(StrictModel):
    architectures: list[Architecture] = Field(min_length=3, max_length=3)


class StrategyResult(StrictModel):
    status: Literal[
        "completed", "disabled_by_prep_rules", "not_configured", "failed", "invalid_output"
    ]
    architectures: list[Architecture] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    packet_fingerprint: str
    model: str | None = None
    prompt_version: str = "milestone-12-v1"
    # Only the sources actually supplied to the model; supports later citation inspection.
    supplied_archive_ids: list[str] = Field(default_factory=list)
    supplied_research_ids: list[str] = Field(default_factory=list)
