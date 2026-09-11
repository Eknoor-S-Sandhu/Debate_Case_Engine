"""Plan one round and orchestrate its knowledge handoff only."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from debate_engine.agents.judge import JudgeAgent
from debate_engine.config import Settings, get_settings
from debate_engine.retrieval.queries import generate_retrieval_queries
from debate_engine.schemas import RetrievalRequest, RoundType
from debate_engine.schemas.rounds import KnowledgePacket, RoundInput, RoundPlan

if TYPE_CHECKING:
    from debate_engine.agents.research import ResearchProvider
    from debate_engine.agents.strategy import StrategyProvider
    from debate_engine.schemas.strategy import StrategyResult


class RoundDirector:
    def __init__(
        self, settings: Settings | None = None, *, research_provider: ResearchProvider | None = None
    ) -> None:
        self.settings = settings or get_settings()
        self.research_provider = research_provider

    def plan(self, round_input: RoundInput) -> RoundPlan:
        # Copy input so planning never mutates caller-owned context.
        context = round_input.model_copy(deep=True)
        request = RetrievalRequest.model_validate(context.model_dump(exclude={"prep_rules"}))
        notes = []
        if request.round_type is None:
            if re.match(r"^(THW\b|This House Would\b)", request.motion, re.IGNORECASE):
                request.round_type = RoundType.POLICY
                notes.append("Policy inferred from the explicit 'would' motion prefix.")
            elif re.match(
                r"^(TH[PR]\b|This House (Prefers|Regrets)\b)", request.motion, re.IGNORECASE
            ):
                request.round_type = RoundType.VALUE
                notes.append("Value inferred from the preference/regret motion prefix.")
            else:
                notes.append("Round type is unspecified; no policy/value/fact assumption applied.")
        judge = JudgeAgent().analyze(request.judge_notes, category=request.judge_category)
        request.judge_category = judge.category
        for field, exclude in [
            ("include_theory", judge.exclude_theory),
            ("include_kritiks", judge.exclude_kritiks),
        ]:
            if exclude and getattr(request, field) is None:
                setattr(request, field, False)
            elif exclude and getattr(request, field) is True:
                judge.warnings.append(
                    f"Explicit {field}=true overrides the judge's exclusion preference."
                )
        notes.extend(judge.warnings)
        if request.side is None:
            notes.append("No side supplied; retrieval remains side-neutral.")
        if not (
            request.desired_top_k is not None
            and request.desired_arguments is None
            and request.desired_submodules is None
        ):
            if request.desired_arguments is None:
                request.desired_arguments = self.settings.retrieval.default_argument_results
            if request.desired_submodules is None:
                request.desired_submodules = self.settings.retrieval.default_submodule_results
            if request.desired_arguments == 0 and request.desired_submodules == 0:
                raise ValueError("Request at least one argument or submodule.")
        notes.append("Prep duration is recorded; deadline scheduling is not implemented.")
        return RoundPlan(
            round_input=context,
            retrieval_request=request,
            generated_queries=generate_retrieval_queries(request, settings=self.settings),
            research_permitted=context.prep_rules.internet_allowed,
            research_status=(
                "disabled_by_prep_rules"
                if not context.prep_rules.internet_allowed
                else "ready"
                if self.research_provider is not None
                or (
                    self.settings.research.api_key is not None
                    and self.settings.research.api_key.get_secret_value().strip()
                )
                else "missing_credentials"
            ),
            judge_profile=judge,
            notes=notes,
        )

    def prepare(
        self, round_input: RoundInput, *, database: Path | str | None = None
    ) -> KnowledgePacket:
        from debate_engine.agents.knowledge import KnowledgeAgent
        from debate_engine.agents.research import ResearchAgent

        packet = KnowledgeAgent(self.settings, database=database).retrieve(self.plan(round_input))
        packet.research = ResearchAgent(self.settings, provider=self.research_provider).run(
            packet.plan.round_input, knowledge=packet
        )
        packet.plan.research_status = packet.research.status
        return packet

    def strategize(
        self,
        packet: KnowledgePacket,
        *,
        preferences: str = "",
        provider: StrategyProvider | None = None,
    ) -> StrategyResult:
        """Explicit generation stage; prepare() remains retrieval and research only."""
        from debate_engine.agents.strategy import StrategyAgent

        return StrategyAgent(self.settings, provider=provider).generate(
            packet, preferences=preferences
        )
