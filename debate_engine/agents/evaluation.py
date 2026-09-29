"""Bounded Red Team → repair → scoring pipeline with human selection."""

import hashlib
import json

from debate_engine.agents.diagnostics import invalid_output, run_inference
from debate_engine.agents.evaluation_prompt import (
    EVALUATION_PROMPT_VERSION,
    RED_TEAM,
    REPAIR,
    SCORE,
)
from debate_engine.agents.round_rules import profile_instructions
from debate_engine.agents.strategy import StrategyProvider, build_context, validate_architectures
from debate_engine.agents.strategy_provider import (
    create_provider,
    inference_metadata,
    inference_ready,
)
from debate_engine.config import Settings, get_settings
from debate_engine.schemas import RoundType, Side
from debate_engine.schemas.evaluation import (
    CritiqueSet,
    EvaluationResult,
    EvaluationSet,
    RankedArchitecture,
    RepairSet,
)
from debate_engine.schemas.rounds import KnowledgePacket
from debate_engine.schemas.strategy import ArchitectureSet, StrategyResult


def fingerprint(value) -> str:
    # Provider metadata was absent in Milestones 12–14. Preserve their fingerprint bytes.
    exclude = {"provider"} if hasattr(value, "provider") and value.provider is None else set()
    if hasattr(value, "inference_calls") and not value.inference_calls:
        exclude.add("inference_calls")
    return hashlib.sha256(value.model_dump_json(exclude=exclude).encode()).hexdigest()


def require_all_ids(rows) -> None:
    if len(rows) != 3 or {row.architecture_id for row in rows} != {1, 2, 3}:
        raise ValueError("Each architecture ID must occur exactly once.")


def select_architecture(result: EvaluationResult, architecture_id: int) -> EvaluationResult:
    """Record an explicit user choice without another provider call or case writing."""
    result = EvaluationResult.model_validate(result.model_dump())
    if result.status != "completed":
        raise ValueError("Complete evaluation before selecting an architecture.")
    selected = result.model_dump()
    selected["selected_architecture_id"] = architecture_id
    return EvaluationResult.model_validate(selected)


def validate_critiques(output, originals):
    require_all_ids(output.critiques)
    for critique in output.critiques:
        for finding in critique.findings:
            if finding.contention_number is not None and finding.contention_number > len(
                originals[critique.architecture_id].contentions
            ):
                raise ValueError("Finding targets an absent contention.")
    return sorted(output.critiques, key=lambda c: c.architecture_id)


def validate_repairs(output, originals, critiques, context):
    require_all_ids(output.repairs)
    repairs = sorted(output.repairs, key=lambda r: r.architecture_id)
    validate_architectures(
        ArchitectureSet(architectures=[r.architecture for r in repairs]), context
    )
    for repair, critique in zip(repairs, critiques, strict=True):
        if repair.architecture.name != originals[repair.architecture_id].name:
            raise ValueError("Repair must preserve architecture identity.")
        numbers = [r.finding_number for r in repair.responses]
        if sorted(numbers) != list(range(1, len(critique.findings) + 1)):
            raise ValueError("Repair must account for every finding exactly once.")
    return repairs


class EvaluationAgent:
    def __init__(
        self, settings: Settings | None = None, *, provider: StrategyProvider | None = None
    ):
        self.settings = settings or get_settings()
        self.provider = provider

    def evaluate(
        self,
        packet: KnowledgePacket,
        strategy: StrategyResult,
        *,
        checkpoint: EvaluationResult | None = None,
    ) -> EvaluationResult:
        """Evaluate fresh, or retry only scoring from a validated failed-scoring checkpoint."""
        result = EvaluationResult(
            status="invalid_output",
            prompt_version=EVALUATION_PROMPT_VERSION,
            packet_fingerprint=fingerprint(packet),
            strategy_fingerprint=fingerprint(strategy),
            **inference_metadata(self.settings, self.provider is not None),
        )
        if not packet.plan.round_input.prep_rules.inference_permitted:
            result.status = "disabled_by_prep_rules"
            result.warnings = [
                "Evaluation is disabled by cloud-inference permission; no provider was called."
            ]
            return result
        try:
            if strategy.status != "completed" or strategy.packet_fingerprint != fingerprint(packet):
                raise ValueError("Use completed architectures generated from this exact packet.")
            request = packet.plan.retrieval_request
            if request.side in {None, Side.UNKNOWN} or request.round_type not in {
                RoundType.POLICY,
                RoundType.VALUE,
                RoundType.FACT,
            }:
                raise ValueError("A concrete side and policy/value/fact round type are required.")
            context, warnings = build_context(packet, self.settings, "")
            result.warnings.extend(warnings)
            # Never broaden the original generation's source pool during evaluation.
            for key, supplied in [
                ("archive", strategy.supplied_archive_ids),
                ("research", strategy.supplied_research_ids),
            ]:
                if not set(supplied) <= context[key].keys():
                    raise ValueError(
                        "Original sources are unavailable under current context limits."
                    )
                context[key] = {source_id: context[key][source_id] for source_id in supplied}
            original = ArchitectureSet(architectures=strategy.architectures)
            validate_architectures(original, context)
            originals = dict(enumerate(strategy.architectures, start=1))
            if checkpoint is not None:
                saved = EvaluationResult.model_validate(checkpoint.model_dump())
                if (
                    saved.status not in {"failed", "invalid_output"}
                    or saved.stage != "scoring"
                    or saved.packet_fingerprint != result.packet_fingerprint
                    or saved.strategy_fingerprint != result.strategy_fingerprint
                    or saved.provider != result.provider
                    or saved.model != result.model
                    or saved.prompt_version != result.prompt_version
                ):
                    raise ValueError("Use a matching failed-scoring checkpoint and provider.")
                result.critiques = validate_critiques(
                    CritiqueSet(critiques=saved.critiques), originals
                )
                result.repairs = validate_repairs(
                    RepairSet(repairs=saved.repairs), originals, result.critiques, context
                )
                result.inference_calls = [
                    call.model_copy(deep=True) for call in saved.inference_calls
                ]
                result.warnings.append("Resumed scoring; prior failed calls remain in diagnostics.")
        except ValueError:
            result.warnings.append(
                "Input validation failed. Use a completed strategy export with its original "
                "packet, eligible sources, and sufficient context limits."
            )
            return result
        config = self.settings.strategy
        if self.provider is None and not inference_ready(self.settings):
            result.status = "not_configured"
            result.warnings.append(
                "Configure the selected provider and enable remote access. "
                "Codex CLI needs ChatGPT login; API providers need a key and model."
            )
            return result
        provider = self.provider or create_provider(self.settings)
        originals = {
            i: architecture for i, architecture in enumerate(strategy.architectures, start=1)
        }
        data = {
            "context": context,
            "architectures": [
                {"architecture_id": i, "architecture": a.model_dump(mode="json")}
                for i, a in originals.items()
            ],
        }
        stages = [
            ("red_team", RED_TEAM, CritiqueSet),
            ("repair", REPAIR, RepairSet),
            ("scoring", SCORE, EvaluationSet),
        ]
        if checkpoint is not None:
            data["critiques"] = [c.model_dump(mode="json") for c in result.critiques]
            data["repairs"] = [r.model_dump(mode="json") for r in result.repairs]
            stages = stages[2:]
        for stage, instructions, schema in stages:
            result.stage = stage
            encoded = json.dumps(data, ensure_ascii=False)
            if len(encoded) > config.max_input_characters:
                result.status = "invalid_output"
                result.warnings.append(f"{stage} input exceeds the configured size limit.")
                return result
            try:
                raw = run_inference(
                    provider,
                    result,
                    stage,
                    profile_instructions(instructions, context),
                    encoded,
                    schema.model_json_schema(),
                )
            except Exception:
                result.status = "failed"
                result.warnings.append(f"{stage} provider failed or refused; evaluation stopped.")
                return result
            try:
                output = schema.model_validate(raw)
                if stage == "red_team":
                    result.critiques = validate_critiques(output, originals)
                    data["critiques"] = [c.model_dump(mode="json") for c in result.critiques]
                elif stage == "repair":
                    result.repairs = validate_repairs(output, originals, result.critiques, context)
                    data["repairs"] = [r.model_dump(mode="json") for r in result.repairs]
                else:
                    require_all_ids(output.evaluations)
                    rows = sorted(
                        output.evaluations, key=lambda e: (-e.scores.total, e.architecture_id)
                    )
                    result.rankings = [
                        RankedArchitecture(
                            **row.model_dump(),
                            total=row.scores.total,
                            rank=1 + sum(other.scores.total > row.scores.total for other in rows),
                        )
                        for row in rows
                    ]
            except ValueError:
                invalid_output(result)
                result.status = "invalid_output"
                result.warnings.append(f"{stage} output failed validation; evaluation stopped.")
                return result
        result.status = "completed"
        result.stage = "completed"
        result.warnings.append(
            "Scores are subjective rubric judgments, not win probabilities or verified facts. "
            "Ties share a rank. Choose an architecture explicitly; none is selected automatically."
        )
        return EvaluationResult.model_validate(result.model_dump())
