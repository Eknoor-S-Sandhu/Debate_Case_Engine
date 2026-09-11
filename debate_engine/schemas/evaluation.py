"""Milestone 13 critique, repair, rubric, and explicit user selection contracts."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from debate_engine.schemas.strategy import Architecture, StrictModel, Text

ArchitectureId = Annotated[int, Field(strict=True, ge=1, le=3)]
RUBRIC = {
    "win_condition_strength": 20,
    "link_chain_quality": 20,
    "preemptive_value": 15,
    "uniqueness": 10,
    "diversity_of_offense": 10,
    "impact_quality": 10,
    "judge_fit": 10,
    "novelty_surprise": 5,
}


class Finding(StrictModel):
    criterion: Literal[
        "win_condition_strength",
        "link_chain_quality",
        "preemptive_value",
        "uniqueness",
        "diversity_of_offense",
        "impact_quality",
        "judge_fit",
        "novelty_surprise",
    ]
    contention_number: Annotated[int, Field(strict=True, ge=1, le=3)] | None
    severity: Literal["low", "medium", "high"]
    weakness: Text
    opponent_response: Text
    repair_goal: Text


class Critique(StrictModel):
    architecture_id: ArchitectureId
    findings: list[Finding] = Field(min_length=1, max_length=8)


class CritiqueSet(StrictModel):
    critiques: list[Critique] = Field(min_length=3, max_length=3)


class RepairResponse(StrictModel):
    finding_number: Annotated[int, Field(strict=True, ge=1, le=8)]
    status: Literal["addressed", "partially_addressed", "unresolved"]
    explanation: Text


class Repair(StrictModel):
    architecture_id: ArchitectureId
    architecture: Architecture
    changes: list[Text] = Field(min_length=1, max_length=8)
    responses: list[RepairResponse] = Field(min_length=1, max_length=8)
    remaining_risks: list[Text] = Field(min_length=1, max_length=8)


class RepairSet(StrictModel):
    repairs: list[Repair] = Field(min_length=3, max_length=3)


class Score20(StrictModel):
    points: Annotated[int, Field(strict=True, ge=0, le=20)]
    rationale: Text


class Score15(StrictModel):
    points: Annotated[int, Field(strict=True, ge=0, le=15)]
    rationale: Text


class Score10(StrictModel):
    points: Annotated[int, Field(strict=True, ge=0, le=10)]
    rationale: Text


class Score5(StrictModel):
    points: Annotated[int, Field(strict=True, ge=0, le=5)]
    rationale: Text


class RubricScores(StrictModel):
    win_condition_strength: Score20
    link_chain_quality: Score20
    preemptive_value: Score15
    uniqueness: Score10
    diversity_of_offense: Score10
    impact_quality: Score10
    judge_fit: Score10
    novelty_surprise: Score5

    @property
    def total(self) -> int:
        return sum(getattr(self, key).points for key in RUBRIC)


class Evaluation(StrictModel):
    architecture_id: ArchitectureId
    scores: RubricScores
    tradeoffs: Text


class EvaluationSet(StrictModel):
    evaluations: list[Evaluation] = Field(min_length=3, max_length=3)


class RankedArchitecture(Evaluation):
    rank: Annotated[int, Field(strict=True, ge=1, le=3)]
    total: Annotated[int, Field(strict=True, ge=0, le=100)]


class EvaluationResult(StrictModel):
    status: Literal[
        "completed", "disabled_by_prep_rules", "not_configured", "failed", "invalid_output"
    ]
    stage: Literal["input", "red_team", "repair", "scoring", "completed"] = "input"
    packet_fingerprint: str
    strategy_fingerprint: str
    model: str | None = None
    provider: Literal["openai", "anthropic", "gemini", "injected"] | None = None
    prompt_version: str = "milestone-13-v1"
    critiques: list[Critique] = Field(default_factory=list)
    repairs: list[Repair] = Field(default_factory=list)
    rankings: list[RankedArchitecture] = Field(default_factory=list)
    selected_architecture_id: ArchitectureId | None = None
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_completion(self):
        if self.status == "completed":
            for rows in (self.critiques, self.repairs, self.rankings):
                if len(rows) != 3 or {r.architecture_id for r in rows} != {1, 2, 3}:
                    raise ValueError("Completed evaluation requires all three architectures.")
            if self.stage != "completed":
                raise ValueError("Completed evaluation must finish scoring.")
            totals = [row.total for row in self.rankings]
            if totals != sorted(totals, reverse=True):
                raise ValueError("Rankings must be sorted by total.")
            for row in self.rankings:
                if row.total != row.scores.total or row.rank != 1 + sum(
                    total > row.total for total in totals
                ):
                    raise ValueError("Rank and total must match the rubric scores.")
        elif self.rankings or self.selected_architecture_id is not None:
            raise ValueError("Incomplete evaluations cannot rank or select architectures.")
        return self
