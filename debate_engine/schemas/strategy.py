"""Validated, unranked case architectures for the Strategy Agent handoff."""

from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_serializer,
    model_validator,
)

from debate_engine.schemas.diagnostics import InferenceCall

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=3000)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceQuote(StrictModel):
    source_type: Literal["archive", "research"]
    source_id: Text
    text: Text


class CausalRoute(StrictModel):
    explanation: Text
    warrant_numbers: list[Annotated[int, Field(strict=True, ge=1, le=5)]] = Field(
        min_length=1, max_length=5
    )
    archive_chunk_ids: list[Text] = Field(max_length=8)
    research_source_ids: list[Text] = Field(max_length=8)
    assumptions: list[Text] = Field(max_length=5)
    dependencies: list[Text] = Field(max_length=5)


class TerminalOutcome(StrictModel):
    consequence: Text
    problem_population: Text | None
    reachable_population: Text | None
    attributable_change: Text | None
    severity: Text
    duration: Text | None
    evidence_gaps: list[Text] = Field(max_length=5)


class ConstructionAnalysis(StrictModel):
    status_quo_barrier: Text | None
    proposed_change: Text
    causal_routes: list[CausalRoute] = Field(min_length=1, max_length=3)
    terminal_outcomes: list[TerminalOutcome] = Field(min_length=1, max_length=3)
    shared_dependencies: list[Text] = Field(max_length=5)
    surviving_ballot_argument: Text


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

    construction: ConstructionAnalysis | None = None

    @classmethod
    def __get_pydantic_json_schema__(cls, core_schema, handler):
        schema = handler(core_schema)
        # Providers require every property in strict JSON schemas. Legacy parsing
        # still accepts absent metadata; new responses must supply it or null.
        schema.setdefault("required", []).append("construction")
        schema["properties"]["construction"].pop("default", None)
        return schema

    @model_serializer(mode="wrap")
    def serialize_compatible(self, handler):
        data = handler(self)
        if self.construction is None:
            data.pop("construction", None)
        return data

    @model_validator(mode="after")
    def validate_construction(self):
        if self.construction is not None:
            for route in self.construction.causal_routes:
                if any(n > len(self.warrants) for n in route.warrant_numbers):
                    raise ValueError("Construction references a missing contention warrant.")
                if len(set(route.warrant_numbers)) != len(route.warrant_numbers):
                    raise ValueError("Construction warrant references must be unique.")
                if not set(route.archive_chunk_ids) <= set(self.archive_chunk_ids):
                    raise ValueError("Route archive sources must be cited by the contention.")
                if not set(route.research_source_ids) <= set(self.research_source_ids):
                    raise ValueError("Route research sources must be cited by the contention.")
        return self

    @model_validator(mode="after")
    def validate_basis(self):
        archive, research = bool(self.archive_chunk_ids), bool(self.research_source_ids)
        if self.basis == "archive_adaptation" and (not archive or research):
            raise ValueError(
                "Archive adaptation requires only archive sources; use mixed for both."
            )
        if self.basis == "research_informed" and (not research or archive):
            raise ValueError(
                "Research-informed reasoning requires only research sources; use mixed for both."
            )
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
    inference_calls: list[InferenceCall] = Field(default_factory=list)
    model: str | None = None
    provider: Literal["openai", "anthropic", "gemini", "codex_cli", "injected"] | None = None
    prompt_version: str = "milestone-12-v1"
    # Only the sources actually supplied to the model; supports later citation inspection.
    supplied_archive_ids: list[str] = Field(default_factory=list)
    supplied_research_ids: list[str] = Field(default_factory=list)
