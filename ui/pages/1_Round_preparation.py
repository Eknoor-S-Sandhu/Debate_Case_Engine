"""Round preparation with judge adaptation and permission-gated research."""

import streamlit as st

from debate_engine.agents import RoundDirector
from debate_engine.agents.evaluation import select_architecture
from debate_engine.agents.strategy_provider import inference_ready, provider_settings
from debate_engine.config import ProviderName, get_settings
from debate_engine.schemas import JudgeCategory, RoundType, Side
from debate_engine.schemas.case import SpeechBudget
from debate_engine.schemas.evaluation import RUBRIC
from debate_engine.schemas.rounds import PrepRules, RoundInput


def render_architecture(architecture) -> None:
    st.text(architecture.framing)
    if architecture.value:
        st.text(f"Value: {architecture.value} · Criterion: {architecture.criterion}")
    st.caption("Core mechanism")
    st.text(architecture.core_mechanism)
    st.caption("Route to the ballot")
    st.text(architecture.route_to_ballot)
    st.caption("What makes this approach distinct")
    st.text(architecture.differs_from_others)
    for contention in architecture.contentions:
        st.text(contention.title)
        st.text(contention.claim)
        st.caption(f"Basis: {contention.basis}")
        for label, text in [
            ("Uniqueness", contention.uniqueness),
            ("Link", contention.link),
            ("Internal link", contention.internal_link),
        ]:
            if text:
                st.text(f"{label}: {text}")
        for label, values in [
            ("Warrant", contention.warrants),
            ("Impact", contention.impacts),
            ("Preempt", contention.preempts),
            ("Assumption", contention.assumptions),
            ("Verify", contention.needs_verification),
        ]:
            for text in values:
                st.text(f"{label}: {text}")
        st.text(f"Archive sources: {', '.join(contention.archive_chunk_ids) or 'none'}")
        st.text(f"Research sources: {', '.join(contention.research_source_ids) or 'none'}")
        for quote in contention.quotes:
            st.text(f'Quote ({quote.source_type}, {quote.source_id}): "{quote.text}"')
    st.caption("Judge adaptation")
    st.text(architecture.judge_adaptation)
    st.caption("Why this can win")
    st.text(architecture.why_this_can_win)
    st.caption("Initial vulnerability")
    st.text(architecture.main_vulnerability)
    with st.expander("Structured architecture data"):
        st.json(architecture.model_dump(mode="json"))


def main() -> None:
    st.set_page_config(page_title="Round preparation", page_icon="📚", layout="wide")
    st.title("Round preparation")
    st.caption("Prepare archive material, judge guidance, and research for your round.")
    settings = get_settings().model_copy(deep=True)
    providers = list(ProviderName)
    provider = st.selectbox(
        "Inference provider",
        providers,
        index=providers.index(settings.strategy.provider),
        key="inference_provider",
    )
    settings.strategy.provider = provider
    selected_config = provider_settings(settings)
    st.caption(
        f"Next generation request: {provider.value} · "
        f"Model: {selected_config.model or 'not configured'}. "
        "Selected archive excerpts and judge notes are sent to this provider."
    )
    if not inference_ready(settings):
        st.info(
            "Configure this provider's API key, model and remote access in your local environment."
        )
    with st.form("round"):
        motion = st.text_area("Motion", key="motion")
        left, right = st.columns(2)
        with left:
            side = st.selectbox("Side", [None, *Side], key="side")
            round_type = st.selectbox("Round type", [None, *RoundType], key="round_type")
            judge = st.selectbox("Judge category", [None, *JudgeCategory], key="judge")
        with right:
            minutes = st.number_input("Prep minutes", min_value=1, max_value=180, value=15)
            internet = st.checkbox("Round rules permit internet research", key="internet")
            st.caption(
                "Live research requires a configured Tavily key. "
                "Only motion and concepts are sent to search."
            )
        judge_notes = st.text_area("Judge paradigm or notes")
        concepts = st.text_area("Extra concepts (one per line)")
        theory = st.selectbox("Include theory", [None, True, False])
        kritiks = st.selectbox("Include kritiks", [None, True, False])
        preview = st.form_submit_button("Preview plan")
        prepare = st.form_submit_button("Prepare knowledge packet", type="primary")
    if preview or prepare:
        st.session_state.pop("round_output", None)
        st.session_state.pop("strategy_output", None)
        st.session_state.pop("case_output", None)
        st.session_state.pop("evaluation_output", None)
        st.session_state.pop("architecture_choice", None)
        try:
            context = RoundInput(
                motion=motion,
                side=side,
                round_type=round_type,
                judge_category=judge,
                judge_notes=judge_notes or None,
                include_theory=theory,
                include_kritiks=kritiks,
                explicit_concepts=[line.strip() for line in concepts.splitlines() if line.strip()],
                prep_rules=PrepRules(minutes=int(minutes), internet_allowed=internet),
            )
            director = RoundDirector(settings)
            with st.spinner("Preparing your round…"):
                output = director.plan(context) if preview else director.prepare(context)
            st.session_state["round_output"] = output
        except Exception as exc:
            st.error(f"Round preparation could not finish: {exc}")
    output = st.session_state.get("round_output")
    if output is None:
        st.info("Preview the retrieval plan or prepare a packet from your existing indexes.")
        return
    packet = output if hasattr(output, "items") else None
    plan = packet.plan if packet is not None else output
    st.subheader("Submitted motion")
    st.text(plan.round_input.motion)
    st.caption("Shown results belong to the last submission. Submit again to apply edits.")
    with st.expander("Round plan", expanded=packet is None):
        st.json(plan.model_dump(mode="json"))
    if plan.judge_profile:
        profile = plan.judge_profile
        st.subheader("Judge adaptation")
        st.caption(
            f"Category: {profile.category or 'unspecified'} · {profile.classification_source}"
        )
        for guidance in profile.guidance:
            st.text(guidance)
        for warning in profile.warnings:
            st.warning(warning)
        if profile.preferences:
            with st.expander("Specific preferences"):
                for preference in profile.preferences:
                    st.text(preference)
    if packet is None:
        return
    st.subheader(f"Knowledge packet · {len(packet.items)} unique chunks")
    for warning in packet.warnings:
        st.warning(warning)
    for category, ids in packet.groups.items():
        if not ids:
            continue
        st.subheader(category.value.replace("_", " ").title())
        for chunk_id in ids:
            item = packet.items[chunk_id]
            candidate = item.candidate
            chunk = candidate.chunk
            with st.container(border=True):
                st.text(chunk.source_file)
                st.text(" > ".join(chunk.heading_path))
                st.caption(
                    f"Score {candidate.final_score:.4f} · Support {candidate.support_level.value}"
                )
                st.text(chunk.text)
                st.text(chunk.source_path)
                for note in item.verification_notes:
                    st.warning(note)
                with st.expander("Source metadata and scores"):
                    st.json(item.model_dump(mode="json"))
    if packet.research is not None:
        research = packet.research
        st.subheader("Live research")
        st.caption(f"Status: {research.status} · {len(research.sources)} sources")
        for warning in research.warnings:
            st.warning(warning)
        for source in research.sources:
            with st.container(border=True):
                st.text(source.title)
                st.link_button("Open source", source.url)
                st.caption(
                    f"Published: {source.published_date or 'unknown'} · Unverified search excerpt"
                )
                st.text(source.excerpt)
                for note in source.notes:
                    st.caption(note)
    st.subheader("Three case architectures")
    st.caption(
        "Generation sends selected archive excerpts, judge notes, and research to the "
        "selected inference provider. It requires internet-permitted prep and explicit cloud setup."
    )
    preferences = st.text_area("Strategy preferences", key="strategy_preferences")
    if st.button("Generate three architectures", key="generate_strategies"):
        st.session_state.pop("strategy_output", None)
        st.session_state.pop("case_output", None)
        st.session_state.pop("evaluation_output", None)
        st.session_state.pop("architecture_choice", None)
        with st.spinner("Generating architectures…"):
            st.session_state["strategy_output"] = RoundDirector(settings).strategize(
                packet, preferences=preferences
            )
    strategy = st.session_state.get("strategy_output")
    if strategy is not None:
        st.caption(
            f"Strategy status: {strategy.status} · {strategy.provider or 'legacy OpenAI'} · "
            f"{strategy.model or 'unspecified model'}. Results reflect the last generation request."
        )
        for warning in strategy.warnings:
            st.warning(warning)
        for index, architecture in enumerate(strategy.architectures, start=1):
            with st.expander(f"Architecture {index}: {architecture.name}", expanded=True):
                render_architecture(architecture)
        if strategy.status == "completed":
            st.download_button(
                "Download architectures",
                strategy.model_dump_json(indent=2),
                file_name="strategy_architectures.json",
                mime="application/json",
            )
    if strategy is not None and strategy.status == "completed":
        st.subheader("Evaluate and choose a strategy")
        st.caption(
            "Run Red Team, one repair pass, and rubric scoring. This makes up to three "
            "additional model requests using the same cloud settings. You make the final choice."
        )
        if st.button("Evaluate three architectures", key="evaluate_strategies"):
            st.session_state.pop("case_output", None)
            st.session_state.pop("evaluation_output", None)
            st.session_state.pop("architecture_choice", None)
            with st.spinner("Critiquing, repairing, and scoring…"):
                st.session_state["evaluation_output"] = RoundDirector(settings).evaluate(
                    packet, strategy
                )
        evaluation = st.session_state.get("evaluation_output")
        if evaluation is not None:
            st.caption(
                f"Evaluation: {evaluation.status} · Stage: {evaluation.stage} · "
                f"{evaluation.provider or 'legacy OpenAI'} · "
                f"{evaluation.model or 'unspecified model'}"
            )
            for warning in evaluation.warnings:
                st.warning(warning)
            for critique in evaluation.critiques:
                with st.expander(f"Red Team · Architecture {critique.architecture_id}"):
                    for number, finding in enumerate(critique.findings, start=1):
                        st.text(f"{number}. [{finding.severity}] {finding.weakness}")
                        st.text(f"Opponent response: {finding.opponent_response}")
                        st.text(f"Repair goal: {finding.repair_goal}")
            for repair in evaluation.repairs:
                with st.expander(f"Repaired architecture {repair.architecture_id}"):
                    for change in repair.changes:
                        st.text(f"Change: {change}")
                    for response in repair.responses:
                        st.text(
                            f"Finding {response.finding_number}: "
                            f"{response.status} — {response.explanation}"
                        )
                    for risk in repair.remaining_risks:
                        st.text(f"Remaining risk: {risk}")
                    render_architecture(repair.architecture)
            if evaluation.status == "completed":
                for row in evaluation.rankings:
                    with st.expander(
                        f"Rank {row.rank} · Architecture {row.architecture_id} · {row.total}/100",
                        expanded=True,
                    ):
                        for key, maximum in RUBRIC.items():
                            score = getattr(row.scores, key)
                            st.text(
                                f"{key.replace('_', ' ').title()}: "
                                f"{score.points}/{maximum} — {score.rationale}"
                            )
                        st.text(f"Tradeoffs: {row.tradeoffs}")
                names = {r.architecture_id: r.architecture.name for r in evaluation.repairs}
                choice = st.selectbox(
                    "Your architecture choice",
                    [None, 1, 2, 3],
                    key="architecture_choice",
                    format_func=lambda i: (
                        "Choose an architecture" if i is None else (f"{i}: {names[i]}")
                    ),
                )
                if st.button("Confirm architecture choice", disabled=choice is None):
                    st.session_state.pop("case_output", None)
                    evaluation = select_architecture(evaluation, choice)
                    st.session_state["evaluation_output"] = evaluation
                if evaluation.selected_architecture_id is not None:
                    st.success(
                        f"Your confirmed choice: Architecture {evaluation.selected_architecture_id}"
                    )
                if evaluation.selected_architecture_id is not None:
                    st.subheader("Write your case")
                    st.caption(
                        "Uses the confirmed choice. Government/affirmative: 7 minutes; "
                        "opposition/negative: 8 minutes. Two model requests, or three if trimming "
                        "is needed, using the existing cloud settings."
                    )
                    wpm = st.number_input(
                        "Reading speed (words per minute)", 80, 400, 150, key="case_wpm"
                    )
                    reserve = st.number_input(
                        "Reserve for pauses (seconds)", 0, 120, 30, key="case_reserve"
                    )
                    if st.button("Write final case", key="write_case"):
                        st.session_state.pop("case_output", None)
                        with st.spinner("Writing and refining your case…"):
                            st.session_state["case_output"] = RoundDirector(settings).write_case(
                                packet,
                                strategy,
                                evaluation,
                                budget=SpeechBudget(words_per_minute=wpm, reserve_seconds=reserve),
                            )
                    final_case = st.session_state.get("case_output")
                    if final_case is not None:
                        for warning in final_case.warnings:
                            st.warning(warning)
                        if final_case.status == "completed":
                            st.caption(
                                f"{final_case.provider or 'legacy OpenAI'} · "
                                f"{final_case.model or 'unspecified model'} · "
                                f"Selected strategy: {final_case.selected_strategy_score}/100 · "
                                f"{final_case.word_count}/{final_case.word_limit} words · "
                                f"Estimated {final_case.estimated_seconds / 60:.1f} minutes "
                                f"at {final_case.budget.words_per_minute} wpm. "
                                "Results use the last submitted timing settings."
                            )
                            st.markdown(final_case.markdown)
                            st.download_button(
                                "Download case (Markdown)",
                                final_case.markdown,
                                file_name="debate_case.md",
                                mime="text/markdown",
                            )
                            st.download_button(
                                "Download case (JSON)",
                                final_case.model_dump_json(indent=2),
                                file_name="debate_case.json",
                                mime="application/json",
                            )
                        else:
                            st.error(f"Case not completed: {final_case.status}")
                st.download_button(
                    "Download evaluation and choice",
                    evaluation.model_dump_json(indent=2),
                    file_name="strategy_evaluation.json",
                    mime="application/json",
                )
    st.download_button(
        "Download Knowledge Packet",
        packet.model_dump_json(indent=2),
        file_name="knowledge_packet.json",
        mime="application/json",
    )


if __name__ == "__main__":
    main()
