"""Selected strategy → draft → optional trim → one improvement, with local timing."""

import json
import re

from debate_engine.agents.case_prompt import DRAFT_CASE, IMPROVE_CASE, TRIM_CASE
from debate_engine.agents.diagnostics import invalid_output, run_inference
from debate_engine.agents.evaluation import fingerprint
from debate_engine.agents.strategy import StrategyProvider, build_context, validate_architectures
from debate_engine.agents.strategy_provider import (
    create_provider,
    inference_metadata,
    inference_ready,
)
from debate_engine.config import Settings, get_settings
from debate_engine.schemas import RoundType, Side
from debate_engine.schemas.case import CaseDocument, CaseResult, SpeechBudget
from debate_engine.schemas.evaluation import EvaluationResult
from debate_engine.schemas.rounds import KnowledgePacket
from debate_engine.schemas.strategy import ArchitectureSet, StrategyResult


def case_points(case):
    yield from case.observations
    yield from case.definitions
    yield from case.inherency
    yield from case.solvency
    for contention in case.contentions:
        for field in ("uniqueness", "links", "internal_links", "warrants", "impacts", "preempts"):
            yield from getattr(contention, field)


def validate_case(case, context, selected):
    kind = context["round"]["round_type"]
    if [c.title for c in case.contentions] != [c.title for c in selected.contentions]:
        raise ValueError("Case must preserve the selected contention titles and order.")
    if kind == "policy":
        if context["round"]["side"] in {"aff", "gov"} and case.plan is None:
            raise ValueError("Government policy requires a plan.")
        for c in case.contentions:
            if not (3 <= len(c.uniqueness) <= 5 and 2 <= len(c.links) <= 3) or c.warrants:
                raise ValueError("Policy requires UQ/L/IL/IMPX structure.")
    else:
        if case.plan is not None or case.inherency or case.solvency or not case.observations:
            raise ValueError("Value/fact require observations and prohibit policy sections.")
        if kind == "value" and (not case.value or not case.criterion):
            raise ValueError("Value and criterion are required.")
        for c in case.contentions:
            if c.uniqueness or c.links or c.internal_links or not 3 <= len(c.warrants) <= 5:
                raise ValueError("Value/fact require claim, 3–5 warrants, and impacts.")
    for point in case_points(case):
        for key, ids in [
            ("archive", point.archive_chunk_ids),
            ("research", point.research_source_ids),
        ]:
            if not set(ids) <= context[key].keys():
                raise ValueError("Unsupplied case source.")
        if (
            point.research_source_ids
            or any(
                context["archive"][i]["verification_notes"]
                or context["archive"][i]["freshness"] in {"possibly_stale", "stale_empirics"}
                for i in point.archive_chunk_ids
            )
        ) and not case.needs_verification:
            raise ValueError("Unverified evidence must retain verification needs.")
        for quote in point.quotes:
            key = "archive" if quote.source_type == "archive" else "research"
            ids = point.archive_chunk_ids if key == "archive" else point.research_source_ids
            if (
                quote.source_id not in ids
                or quote.text not in point.text
                or quote.text not in context[key][quote.source_id]["text"]
            ):
                raise ValueError("Quote must match the cited excerpt and occur in the point.")


def render_case(case, packet):
    """Render speech text only; evidence and verification notes are separate."""
    request = packet.plan.retrieval_request
    policy = request.round_type == RoundType.POLICY
    lines = [
        f"**Topic**: {request.motion}",
        f"**Side**: {request.side.value.upper()}",
        f"**Round**: {request.round_type.value.title()}",
    ]
    if request.round_type == RoundType.VALUE:
        lines += [f"**Value**: {case.value}", f"**Value Criterion**: {case.criterion}"]
    else:
        label = "Weighing Mechanism" if policy else "Weighing Mechanism / Threshold of Truth"
        lines.append(f"**{label}**: {case.weighing_mechanism}")

    def section(label, points):
        lines.append(f"\n**{label}:**")
        lines.extend(f"{i}. **{p.tagline}:** {p.text}" for i, p in enumerate(points, 1))

    section("Observations", case.observations)
    section("Definitions", case.definitions)
    if policy:
        section("Inherency", case.inherency)
        lines.append("\n**Plan text/CP**: " + (case.plan.action if case.plan else ""))
        for label, field in [
            ("AoA", "actor"),
            ("AoE", "enforcement_actor"),
            ("Funding", "funding"),
            ("Timeframe", "timeframe"),
            ("Enforcement", "enforcement"),
        ]:
            lines.append(f"{label}: {getattr(case.plan, field) if case.plan else ''}")
        section("Solvency", case.solvency)
    for i, c in enumerate(case.contentions, 1):
        label = ("AD" if request.side in {Side.GOV, Side.AFF} else "DA") if policy else "Contention"
        lines.append(f"\n**{label} {i}: {c.title}**")
        if policy:
            for heading, points in [
                ("UQ", c.uniqueness),
                ("L", c.links),
                ("IL", c.internal_links),
                ("IMPX", c.impacts),
            ]:
                section(heading, points)
        else:
            lines.append(f"\n**Claim:** {c.claim}")
            section("Warrants", c.warrants)
            section("Impacts", c.impacts)
        section("Embedded Preempts", c.preempts)
    return "\n\n".join(lines)


def count_words(markdown):
    # Count headings and numeric points conservatively; formatting marks are not words.
    return len(re.findall(r"\b\w+(?:['’\-]\w+)*\b", markdown))


def evidence_notes(case, packet):
    lines = ["\n---\n\n**Preparation notes — not included in speech timing**"]
    lines += [f"- Assumption: {note}" for note in case.assumptions]
    lines += [f"- Verify: {note}" for note in case.needs_verification]
    archive = {i for p in case_points(case) for i in p.archive_chunk_ids}
    research = {i for p in case_points(case) for i in p.research_source_ids}
    for i in sorted(archive):
        chunk = packet.items[i].candidate.chunk
        lines.append(f"- Archive {i}: {chunk.source_file} — {' > '.join(chunk.heading_path)}")
    if packet.research:
        for source in packet.research.sources:
            if source.source_id in research:
                lines.append(f"- Research {source.source_id}: {source.title} — {source.url}")
    return "\n".join(lines)


class CaseWriter:
    def __init__(
        self, settings: Settings | None = None, *, provider: StrategyProvider | None = None
    ):
        self.settings = settings or get_settings()
        self.provider = provider

    def write(
        self,
        packet: KnowledgePacket,
        strategy: StrategyResult,
        evaluation: EvaluationResult,
        *,
        budget: SpeechBudget | None = None,
    ) -> CaseResult:
        budget = SpeechBudget.model_validate((budget or SpeechBudget()).model_dump())
        result = CaseResult(
            status="invalid_output",
            packet_fingerprint=fingerprint(packet),
            strategy_fingerprint=fingerprint(strategy),
            evaluation_fingerprint=fingerprint(evaluation),
            budget=budget,
            **inference_metadata(self.settings, self.provider is not None),
        )
        if not packet.plan.round_input.prep_rules.internet_allowed:
            result.status = "disabled_by_prep_rules"
            result.warnings = ["Cloud case writing is disabled for offline prep."]
            return result
        try:
            evaluation = EvaluationResult.model_validate(evaluation.model_dump())
            if (
                strategy.status != "completed"
                or evaluation.status != "completed"
                or evaluation.selected_architecture_id is None
                or strategy.packet_fingerprint != fingerprint(packet)
                or evaluation.packet_fingerprint != fingerprint(packet)
                or evaluation.strategy_fingerprint != fingerprint(strategy)
            ):
                raise ValueError("Completed matching inputs and explicit choice required.")
            request = packet.plan.retrieval_request
            if request.side not in {
                Side.AFF,
                Side.GOV,
                Side.NEG,
                Side.OPP,
            } or request.round_type not in {RoundType.POLICY, RoundType.VALUE, RoundType.FACT}:
                raise ValueError("Concrete side and round type required.")
            context, warnings = build_context(packet, self.settings, "")
            result.warnings.extend(warnings)
            for key, ids in [
                ("archive", strategy.supplied_archive_ids),
                ("research", strategy.supplied_research_ids),
            ]:
                if not set(ids) <= context[key].keys():
                    raise ValueError("Original source pool unavailable.")
                context[key] = {i: context[key][i] for i in ids}
            validate_architectures(ArchitectureSet(architectures=strategy.architectures), context)
            repairs = sorted(evaluation.repairs, key=lambda r: r.architecture_id)
            validate_architectures(
                ArchitectureSet(architectures=[r.architecture for r in repairs]), context
            )
            selected = repairs[evaluation.selected_architecture_id - 1]
        except ValueError:
            result.warnings.append(
                "Use matching packet, strategy and completed evaluation exports "
                "with an explicit architecture choice and available sources."
            )
            return result
        result.selected_architecture_id = selected.architecture_id
        result.selected_strategy_score = next(
            r.total for r in evaluation.rankings if r.architecture_id == selected.architecture_id
        )
        result.speech_minutes = 7 if request.side in {Side.GOV, Side.AFF} else 8
        result.word_limit = (
            (result.speech_minutes * 60 - budget.reserve_seconds) * budget.words_per_minute // 60
        )
        config = self.settings.strategy
        if self.provider is None and not inference_ready(self.settings):
            result.status = "not_configured"
            result.warnings.append(
                "Configure the selected provider API_KEY, MODEL, and remote access."
            )
            return result
        provider = self.provider or create_provider(self.settings)
        data = {
            "context": context,
            "selected_architecture": selected.model_dump(mode="json"),
            "word_limit": result.word_limit,
            "budget": budget.model_dump(),
            "strategy_score": result.selected_strategy_score,
        }
        for stage, prompt in [
            ("draft", DRAFT_CASE),
            ("trim", TRIM_CASE),
            ("improve", IMPROVE_CASE),
        ]:
            if stage == "trim" and result.word_count <= result.word_limit:
                continue
            result.stage = stage
            encoded = json.dumps(data, ensure_ascii=False)
            if len(encoded) > config.max_input_characters:
                result.status = "invalid_output"
                result.warnings.append(f"{stage} input exceeds configured size limit.")
                return result
            try:
                raw = run_inference(
                    provider, result, stage, prompt, encoded, CaseDocument.model_json_schema()
                )
            except Exception:
                result.status = "failed"
                result.warnings.append(
                    f"{stage} provider failed or refused; no final case accepted."
                )
                return result
            try:
                case = CaseDocument.model_validate(raw)
                validate_case(case, context, selected.architecture)
            except ValueError:
                invalid_output(result)
                result.status = "invalid_output"
                result.warnings.append(f"{stage} case failed structure or source validation.")
                return result
            speech = render_case(case, packet)
            result.word_count = count_words(speech)
            result.estimated_seconds = round(result.word_count * 60 / budget.words_per_minute, 1)
            # Drafts remain internal; only a successful final pass exposes a case.
            data["case"] = case.model_dump(mode="json")
            data["measured_word_count"] = result.word_count
        if result.word_count > result.word_limit:
            result.status = "over_budget"
            result.warnings.append(
                "Revised case still exceeds the speech budget; no final case accepted."
            )
            return result
        result.status = "completed"
        result.stage = "completed"
        result.case = case
        result.markdown = speech + "\n" + evidence_notes(case, packet)
        result.warnings.append(
            "Timing is an estimate at your chosen reading speed; rehearse aloud. "
            "Source checks do not establish factual truth."
        )
        return CaseResult.model_validate(result.model_dump())
