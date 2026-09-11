"""Generate three architectures, validate provenance, and stop before evaluation."""

import hashlib
import json
import re
from itertools import combinations
from typing import Protocol

from pydantic import ValidationError

from debate_engine.agents.diagnostics import invalid_output, run_inference
from debate_engine.agents.strategy_prompt import STRATEGY_INSTRUCTIONS
from debate_engine.agents.strategy_provider import (
    create_provider,
    inference_metadata,
    inference_ready,
)
from debate_engine.config import Settings, get_settings
from debate_engine.retrieval.queries import infer_query_intents
from debate_engine.retrieval.scoring import candidate_is_eligible, is_kritik_chunk, is_theory_chunk
from debate_engine.schemas import RoundType, Side
from debate_engine.schemas.rounds import KnowledgePacket
from debate_engine.schemas.strategy import ArchitectureSet, StrategyResult


class StrategyProvider(Protocol):
    def generate(self, instructions: str, context: str, schema: dict) -> dict: ...


def _normalized(text: str) -> str:
    return " ".join(re.findall(r"\w+", text.casefold()))


def build_context(
    packet: KnowledgePacket, settings: Settings, preferences: str
) -> tuple[dict, list[str]]:
    config = settings.strategy
    request = packet.plan.retrieval_request
    intents = infer_query_intents(request)
    archive = {}
    warnings = []
    for key, item in packet.items.items():
        chunk = item.candidate.chunk
        if key != chunk.chunk_id or item.candidate.chunk_id != key:
            raise ValueError("Packet source IDs disagree.")
        eligible, _ = candidate_is_eligible(chunk, request, intents)
        if not eligible:
            warnings.append("Ineligible archive material was omitted from strategy input.")
            continue
        if len(archive) >= config.max_archive_chunks:
            warnings.append("Archive source limit reached; some material was not sent.")
            break
        text = chunk.text[: config.excerpt_characters]
        if len(text) < len(chunk.text):
            warnings.append("Some source excerpts were shortened for the model context.")
        archive[key] = {
            "text": text,
            "heading_path": chunk.heading_path,
            "section_type": chunk.section_type,
            "source_group": chunk.source_group.value,
            "freshness": chunk.freshness.value,
            "verification_notes": item.verification_notes,
            "theory": is_theory_chunk(chunk),
            "kritik": is_kritik_chunk(chunk),
        }
    research = {}
    if packet.research:
        for source in packet.research.sources[: config.max_research_sources]:
            if source.source_id in research:
                raise ValueError("Duplicate research source IDs in packet.")
            research[source.source_id] = {
                "text": source.excerpt[: config.excerpt_characters],
                "title": source.title,
                "published_date": str(source.published_date) if source.published_date else None,
                "verification_status": source.verification_status,
                "notes": source.notes,
            }
        if len(research) < len(packet.research.sources):
            warnings.append("Research source limit reached; some sources were not sent.")
    context = {
        "round": request.model_dump(mode="json"),
        "prep_rules": packet.plan.round_input.prep_rules.model_dump(mode="json"),
        "judge": packet.plan.judge_profile.model_dump(mode="json")
        if packet.plan.judge_profile
        else None,
        "preferences": preferences,
        "archive": archive,
        "research": research,
        "coverage_gaps": [gap.value for gap in packet.coverage_gaps],
        "archive_warnings": packet.warnings,
        "research_status": packet.research.status if packet.research else None,
    }
    return context, list(dict.fromkeys(warnings))


def validate_architectures(output: ArchitectureSet, context: dict) -> None:
    archive, research = context["archive"], context["research"]
    names = [_normalized(a.name) for a in output.architectures]
    if len(set(names)) != 3:
        raise ValueError("Architectures must have distinct names.")
    signatures = []
    for architecture in output.architectures:
        kind = context["round"]["round_type"]
        if kind == "value" and (not architecture.value or not architecture.criterion):
            raise ValueError("Value architectures need a value and criterion.")
        claims = [_normalized(c.claim) for c in architecture.contentions]
        if len(set(claims)) != len(claims):
            raise ValueError("Contentions must provide independent offense.")
        for contention in architecture.contentions:
            if (
                kind == "policy"
                and contention.argument_style == "substantive"
                and not all([contention.uniqueness, contention.link, contention.internal_link])
            ):
                raise ValueError("Policy contentions require uniqueness, link, and internal link.")
            if not set(contention.archive_chunk_ids) <= archive.keys():
                raise ValueError("Unknown or unsupplied archive citation.")
            if not set(contention.research_source_ids) <= research.keys():
                raise ValueError("Unknown or unsupplied research citation.")
            if contention.argument_style in {"theory", "kritik"} and not any(
                archive[key][contention.argument_style] for key in contention.archive_chunk_ids
            ):
                raise ValueError(
                    "Theory/K contentions require eligible archive material of that type."
                )
            for quote in contention.quotes:
                sources = archive if quote.source_type == "archive" else research
                cited = (
                    contention.archive_chunk_ids
                    if quote.source_type == "archive"
                    else contention.research_source_ids
                )
                if quote.source_id not in cited or quote.source_id not in sources:
                    raise ValueError("Quote must cite a supplied source used by its contention.")
                if quote.text not in sources[quote.source_id]["text"]:
                    raise ValueError("Quote does not match the supplied original excerpt.")
            unverified = bool(contention.research_source_ids) or any(
                archive[key]["verification_notes"]
                or archive[key]["freshness"] in {"possibly_stale", "stale_empirics"}
                for key in contention.archive_chunk_ids
            )
            if unverified and not contention.needs_verification:
                raise ValueError("Unverified source use must retain verification needs.")
            if contention.basis == "new_reasoning" and not contention.assumptions:
                raise ValueError("New reasoning must state its unsupported assumptions.")
        # Screen substantive text, excluding labels and self-reported diversity claims.
        body = " ".join(
            " ".join([c.claim, c.link or "", c.internal_link or "", *c.warrants, *c.impacts])
            for c in architecture.contentions
        )
        signatures.append(set(_normalized(body).split()))
    for (i, first), (j, second) in combinations(enumerate(signatures), 2):
        overlap = len(first & second) / max(1, len(first | second))
        if overlap >= 0.9:
            raise ValueError("Architectures repeat substantially the same argument text.")
        a, b = output.architectures[i], output.architectures[j]
        if _normalized(a.core_mechanism) == _normalized(b.core_mechanism) and _normalized(
            a.route_to_ballot
        ) == _normalized(b.route_to_ballot):
            raise ValueError("Architectures repeat the same mechanism and ballot route.")


class StrategyAgent:
    def __init__(
        self, settings: Settings | None = None, *, provider: StrategyProvider | None = None
    ):
        self.settings = settings or get_settings()
        self.provider = provider

    def generate(self, packet: KnowledgePacket, *, preferences: str = "") -> StrategyResult:
        fingerprint = hashlib.sha256(packet.model_dump_json().encode()).hexdigest()
        result = StrategyResult(
            status="not_configured",
            packet_fingerprint=fingerprint,
            **inference_metadata(self.settings, self.provider is not None),
        )
        # All providers honor the offline rule. Local generation can be added explicitly later.
        if not packet.plan.round_input.prep_rules.internet_allowed:
            result.status = "disabled_by_prep_rules"
            result.warnings = [
                "Strategy generation is disabled for offline prep; no provider was called."
            ]
            return result
        config = self.settings.strategy
        if self.provider is None and not inference_ready(self.settings):
            result.warnings = [
                "Configure the selected provider and enable remote access. "
                "Codex CLI requires an installed CLI and ChatGPT login; "
                "API providers require a key and model."
            ]
            return result
        request = packet.plan.retrieval_request
        if (
            request.side is None
            or request.side is Side.UNKNOWN
            or request.round_type not in {RoundType.POLICY, RoundType.VALUE, RoundType.FACT}
        ):
            result.status = "invalid_output"
            result.warnings = [
                "Select a concrete side and policy, value, or fact round type before generation."
            ]
            return result
        try:
            if len(preferences) > 3000:
                raise ValueError("Strategy preferences exceed 3,000 characters.")
            context, warnings = build_context(packet, self.settings, preferences)
            encoded = json.dumps(context, ensure_ascii=False)
            if len(encoded) > config.max_input_characters:
                raise ValueError("Strategy input exceeds its configured size limit.")
            result.warnings.extend(warnings)
            result.supplied_archive_ids = list(context["archive"])
            result.supplied_research_ids = list(context["research"])
        except ValueError as exc:
            result.status = "invalid_output"
            result.warnings.append(str(exc))
            return result
        provider = self.provider or create_provider(self.settings)
        try:
            raw = run_inference(
                provider,
                result,
                "strategy",
                STRATEGY_INSTRUCTIONS,
                encoded,
                ArchitectureSet.model_json_schema(),
            )
        except Exception:
            result.status = "failed"
            result.warnings.append(
                "Strategy generation failed or was refused; no architectures were accepted."
            )
            return result
        try:
            output = ArchitectureSet.model_validate(raw)
            validate_architectures(output, context)
        except (ValueError, ValidationError):
            invalid_output(result)
            result.status = "invalid_output"
            result.warnings.append(
                "Model output failed structure, source, or diversity validation. "
                "No architectures were accepted."
            )
            return result
        result.status = "completed"
        result.architectures = output.architectures
        result.warnings.append(
            "Unranked proposals, not verified cases. "
            "Diversity checks detect text overlap, not strategic quality."
        )
        return result
