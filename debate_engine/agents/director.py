"""Plan one round and orchestrate its knowledge handoff only."""

import re
from pathlib import Path

from debate_engine.config import Settings, get_settings
from debate_engine.retrieval.queries import generate_retrieval_queries
from debate_engine.schemas import RetrievalRequest, RoundType
from debate_engine.schemas.rounds import KnowledgePacket, RoundInput, RoundPlan


class RoundDirector:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

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
        if request.judge_category is None:
            notes.append("Judge category is unspecified; paradigm classification is deferred.")
        if request.judge_notes:
            notes.append("Judge notes preserved verbatim; no paradigm analysis performed.")
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
                "permitted_but_not_implemented"
                if context.prep_rules.internet_allowed
                else "disabled_by_prep_rules"
            ),
            notes=notes,
        )

    def prepare(
        self, round_input: RoundInput, *, database: Path | str | None = None
    ) -> KnowledgePacket:
        from debate_engine.agents.knowledge import KnowledgeAgent

        return KnowledgeAgent(self.settings, database=database).retrieve(self.plan(round_input))
