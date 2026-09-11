"""Structured case text and locally measured speech budgets."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from debate_engine.schemas.diagnostics import InferenceCall
from debate_engine.schemas.strategy import SourceQuote, StrictModel, Text


class SpeechBudget(StrictModel):
    words_per_minute: Annotated[int, Field(strict=True, ge=80, le=400)] = 150
    reserve_seconds: Annotated[int, Field(strict=True, ge=0, le=120)] = 30


class CasePoint(StrictModel):
    tagline: Text
    text: Text
    archive_chunk_ids: list[Text] = Field(max_length=8)
    research_source_ids: list[Text] = Field(max_length=8)
    quotes: list[SourceQuote] = Field(max_length=3)


class PlanText(StrictModel):
    action: Text
    actor: Text
    enforcement_actor: Text
    funding: Text
    timeframe: Text
    enforcement: Text


class CaseContention(StrictModel):
    title: Text
    claim: Text
    uniqueness: list[CasePoint] = Field(max_length=5)
    links: list[CasePoint] = Field(max_length=3)
    internal_links: list[CasePoint] = Field(max_length=3)
    warrants: list[CasePoint] = Field(max_length=5)
    impacts: list[CasePoint] = Field(min_length=1, max_length=2)
    preempts: list[CasePoint] = Field(min_length=1, max_length=3)


class CaseDocument(StrictModel):
    weighing_mechanism: Text
    value: Text | None
    criterion: Text | None
    observations: list[CasePoint] = Field(max_length=3)
    definitions: list[CasePoint] = Field(max_length=5)
    inherency: list[CasePoint] = Field(max_length=3)
    plan: PlanText | None
    solvency: list[CasePoint] = Field(max_length=3)
    contentions: list[CaseContention] = Field(min_length=2, max_length=3)
    assumptions: list[Text] = Field(min_length=1, max_length=12)
    needs_verification: list[Text] = Field(max_length=12)


class CaseResult(StrictModel):
    status: Literal[
        "completed",
        "disabled_by_prep_rules",
        "not_configured",
        "failed",
        "invalid_output",
        "over_budget",
    ]
    stage: Literal["input", "draft", "trim", "improve", "completed"] = "input"
    packet_fingerprint: str
    strategy_fingerprint: str
    evaluation_fingerprint: str
    selected_architecture_id: int | None = None
    selected_strategy_score: int | None = None
    inference_calls: list[InferenceCall] = Field(default_factory=list)
    model: str | None = None
    provider: Literal["openai", "anthropic", "gemini", "codex_cli", "injected"] | None = None
    prompt_version: str = "milestone-14-v1"
    speech_minutes: int = 0
    budget: SpeechBudget = Field(default_factory=SpeechBudget)
    word_limit: int = 0
    word_count: int = 0
    estimated_seconds: float = 0
    case: CaseDocument | None = None
    markdown: str | None = None
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_final(self):
        if self.status == "completed":
            if (
                self.stage != "completed"
                or self.case is None
                or not self.markdown
                or self.selected_architecture_id not in {1, 2, 3}
                or self.speech_minutes not in {7, 8}
            ):
                raise ValueError(
                    "Completed cases require a selection, final text and speech budget."
                )
            limit = (
                (self.speech_minutes * 60 - self.budget.reserve_seconds)
                * self.budget.words_per_minute
                // 60
            )
            seconds = round(self.word_count * 60 / self.budget.words_per_minute, 1)
            if (
                self.word_limit != limit
                or not 0 < self.word_count <= limit
                or self.estimated_seconds != seconds
            ):
                raise ValueError("Completed case must fit its measured budget.")
        elif self.case is not None or self.markdown is not None:
            raise ValueError("Unfinished cases cannot expose final text.")
        return self
