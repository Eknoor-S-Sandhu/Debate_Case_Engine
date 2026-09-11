"""Bounded Red Team → repair → scoring pipeline with human selection."""

import hashlib
import json

from debate_engine.agents.diagnostics import invalid_output, run_inference
from debate_engine.agents.evaluation_prompt import RED_TEAM, REPAIR, SCORE
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


class EvaluationAgent:
    def __init__(
        self, settings: Settings | None = None, *, provider: StrategyProvider | None = None
    ):
        self.settings = settings or get_settings()
        self.provider = provider

    def evaluate(self, packet: KnowledgePacket, strategy: StrategyResult) -> EvaluationResult:
        result = EvaluationResult(
            status="invalid_output",
            packet_fingerprint=fingerprint(packet),
            strategy_fingerprint=fingerprint(strategy),
            **inference_metadata(self.settings, self.provider is not None),
        )
        if not packet.plan.round_input.prep_rules.internet_allowed:
            result.status = "disabled_by_prep_rules"
            result.warnings = ["Evaluation is disabled for offline prep; no provider was called."]
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
                "Configure the selected provider API_KEY, MODEL, and remote access."
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
        for stage, instructions, schema in [
            ("red_team", RED_TEAM, CritiqueSet),
            ("repair", REPAIR, RepairSet),
            ("scoring", SCORE, EvaluationSet),
        ]:
            result.stage = stage
            encoded = json.dumps(data, ensure_ascii=False)
            if len(encoded) > config.max_input_characters:
                result.status = "invalid_output"
                result.warnings.append(f"{stage} input exceeds the configured size limit.")
                return result
            try:
                raw = run_inference(
                    provider, result, stage, instructions, encoded, schema.model_json_schema()
                )
            except Exception:
                result.status = "failed"
                result.warnings.append(f"{stage} provider failed or refused; evaluation stopped.")
                return result
            try:
                output = schema.model_validate(raw)
                if stage == "red_team":
                    require_all_ids(output.critiques)
                    for critique in output.critiques:
                        for finding in critique.findings:
                            if finding.contention_number is not None and (
                                finding.contention_number
                                > len(originals[critique.architecture_id].contentions)
                            ):
                                raise ValueError("Finding targets an absent contention.")
                    result.critiques = sorted(output.critiques, key=lambda c: c.architecture_id)
                    data["critiques"] = [c.model_dump(mode="json") for c in result.critiques]
                elif stage == "repair":
                    require_all_ids(output.repairs)
                    repairs = sorted(output.repairs, key=lambda r: r.architecture_id)
                    validate_architectures(
                        ArchitectureSet(architectures=[r.architecture for r in repairs]), context
                    )
                    for repair, critique in zip(repairs, result.critiques, strict=True):
                        if repair.architecture.name != originals[repair.architecture_id].name:
                            raise ValueError("Repair must preserve architecture identity.")
                        numbers = [r.finding_number for r in repair.responses]
                        if sorted(numbers) != list(range(1, len(critique.findings) + 1)):
                            raise ValueError("Repair must account for every finding exactly once.")
                    result.repairs = repairs
                    data["repairs"] = [r.model_dump(mode="json") for r in repairs]
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
