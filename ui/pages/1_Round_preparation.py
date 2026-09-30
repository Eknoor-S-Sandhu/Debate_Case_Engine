"""Round preparation with judge adaptation and permission-gated research."""

from time import monotonic

import streamlit as st

from debate_engine.agents import RoundDirector
from debate_engine.agents.case_writer import evidence_notes, render_case
from debate_engine.agents.evaluation import EvaluationAgent, select_architecture
from debate_engine.agents.strategy_provider import inference_ready, provider_settings
from debate_engine.config import ProviderName, get_settings
from debate_engine.schemas import JudgeCategory, RoundType, Side
from debate_engine.schemas.case import SpeechBudget
from debate_engine.schemas.evaluation import RUBRIC
from debate_engine.schemas.rounds import PrepRules, RoundInput
from ui.workflow import invalidate, load_checkpoint, remaining_seconds, timed, unresolved_findings


def render_diagnostics(result):
    if result.inference_calls:
        with st.expander("Request diagnostics"):
            for call in result.inference_calls:
                input_count = call.input_tokens if call.input_tokens is not None else "unknown"
                output_count = call.output_tokens if call.output_tokens is not None else "unknown"
                st.text(
                    f"{call.stage}: {call.status} · {call.elapsed_seconds:.2f}s · "
                    f"Input tokens: {input_count} · "
                    f"Output tokens: {output_count}"
                )
                if call.error_code:
                    st.text(
                        f"Error: {call.error_code} · HTTP: {call.http_status or 'not reported'}"
                    )


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
        if contention.construction is not None:
            analysis = contention.construction
            st.caption("Construction analysis")
            if analysis.status_quo_barrier:
                st.text(f"Status-quo barrier: {analysis.status_quo_barrier}")
            st.text(f"Proposed change or comparison: {analysis.proposed_change}")
            for number, route in enumerate(analysis.causal_routes, 1):
                st.text(f"Route {number}: {route.explanation}")
                st.caption(f"Supporting warrant numbers: {route.warrant_numbers}")
                st.caption(
                    f"Archive: {route.archive_chunk_ids}; research: {route.research_source_ids}"
                )
                for item in route.assumptions:
                    st.text(f"Assumption: {item}")
                for item in route.dependencies:
                    st.text(f"Dependency: {item}")
            for outcome in analysis.terminal_outcomes:
                st.text(f"Terminal outcome: {outcome.consequence}")
                for field in (
                    "problem_population",
                    "reachable_population",
                    "attributable_change",
                    "severity",
                    "duration",
                ):
                    st.text(
                        f"{field.replace('_', ' ').title()}: {getattr(outcome, field) or 'Unknown'}"
                    )
                for gap in outcome.evidence_gaps:
                    st.text(f"Evidence gap: {gap}")
            for dependency in analysis.shared_dependencies:
                st.text(f"Shared dependency: {dependency}")
            st.text(f"Surviving ballot argument: {analysis.surviving_ballot_argument}")
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


def render_summary(architecture, index, *, repaired=False):
    with st.container(border=True):
        st.caption(f"OPTION {index}" + (" · REPAIRED" if repaired else ""))
        st.subheader(architecture.name)
        st.caption("Why this wins")
        st.write(architecture.why_this_can_win)
        st.caption("Proposed collapse options")
        for contention in architecture.contentions:
            st.markdown(f"**{contention.title}**")
            st.write(
                contention.construction.surviving_ballot_argument
                if contention.construction
                else " ".join(contention.impacts)
            )
        st.caption("Main vulnerability")
        st.write(architecture.main_vulnerability)
        needs = list(
            dict.fromkeys(need for c in architecture.contentions for need in c.needs_verification)
        )
        if needs:
            with st.expander("Unresolved evidence"):
                for need in needs:
                    st.write(need)
        with st.expander(f"Architecture {index}: details"):
            render_architecture(architecture)


@st.fragment(run_every="1s")
def prep_clock(minutes):
    remaining = remaining_seconds(st.session_state, minutes)
    if remaining is not None:
        st.metric("Prep remaining", f"{remaining // 60:02d}:{remaining % 60:02d}")
        st.caption("Elapsed-time guide. Does not cancel requests or extend the round deadline.")
        if remaining == 0:
            st.warning("Prep time has elapsed.")


def render_sources(packet, plan):
    with st.expander("Round plan and settings"):
        st.json(plan.model_dump(mode="json"))
    if plan.judge_profile:
        with st.expander("Judge guidance"):
            st.subheader("Judge adaptation")
            for guidance in plan.judge_profile.guidance:
                st.text(guidance)
            for warning in plan.judge_profile.warnings:
                st.warning(warning)
    if packet is None:
        st.info("Prepare a knowledge packet to view sources.")
        return
    st.subheader("Your evidence library")
    st.caption(
        f"{len(packet.items)} archive excerpts. Retrieval scores are not factual verification."
    )
    with st.expander("Archive excerpts and provenance"):
        for category, ids in packet.groups.items():
            if not ids:
                continue
            st.markdown(f"**{category.value.replace('_', ' ').title()}**")
            for chunk_id in ids:
                item = packet.items[chunk_id]
                chunk = item.candidate.chunk
                with st.expander(f"{chunk.source_file} · {' > '.join(chunk.heading_path)}"):
                    st.text(chunk.text)
                    st.text(chunk.source_path)
                    for note in item.verification_notes:
                        st.caption(note)
                    st.json(item.model_dump(mode="json"), expanded=False)
    research = packet.research
    if research:
        st.subheader("Live research")
        st.caption(f"{research.status} · {len(research.sources)} sources")
        for warning in research.warnings:
            st.warning(warning)
        for source in research.sources:
            with st.expander(source.title):
                st.link_button("Open source", source.url)
                st.caption(f"Published: {source.published_date or 'unknown'} · Unverified excerpt")
                st.text(source.excerpt)
                for note in source.notes:
                    st.caption(note)
    if packet.warnings:
        with st.expander("Retrieval notes"):
            for warning in packet.warnings:
                st.write(warning)
    st.download_button(
        "Download Knowledge Packet",
        packet.model_dump_json(indent=2),
        file_name="knowledge_packet.json",
        mime="application/json",
    )


def render_strategies(packet, settings):
    st.subheader("Choose your route to the ballot")
    st.caption("Compare independent offense and evidence gaps before confirming your choice.")
    preferences = st.text_area(
        "Strategy preferences",
        key="strategy_preferences",
        placeholder="Example: poverty + environment, each with its own ballot story",
    )
    allowed = packet.plan.round_input.prep_rules.inference_permitted
    if not allowed:
        st.info("Enable cloud model access in Round setup to generate a case.")
    if st.button("Generate three architectures", key="generate_strategies", disabled=not allowed):
        invalidate(st.session_state, "strategy_output")
        with st.spinner("Generating three approaches…"):
            st.session_state["strategy_output"] = timed(
                st.session_state,
                "strategy",
                lambda: RoundDirector(settings).strategize(packet, preferences=preferences),
            )
    strategy = st.session_state.get("strategy_output")
    if strategy is None:
        return
    st.caption(f"Generation: {strategy.status} · {strategy.provider or 'legacy OpenAI'}")
    for warning in strategy.warnings:
        st.caption(warning)
    render_diagnostics(strategy)
    for i, (column, architecture) in enumerate(
        zip(st.columns(3), strategy.architectures, strict=False), 1
    ):
        with column:
            render_summary(architecture, i)
    if strategy.status != "completed":
        return
    st.download_button(
        "Download architectures",
        strategy.model_dump_json(indent=2),
        file_name="strategy_architectures.json",
        mime="application/json",
    )
    st.divider()
    st.subheader("Pressure-test and select")
    st.caption("Critique → repair → scoring. You make the final choice.")
    if st.button("Evaluate three architectures", key="evaluate_strategies", disabled=not allowed):
        invalidate(st.session_state, "evaluation_output")
        with st.spinner("Critiquing, repairing, and scoring…"):
            st.session_state["evaluation_output"] = timed(
                st.session_state,
                "evaluation",
                lambda: RoundDirector(settings).evaluate(packet, strategy),
            )
        st.session_state["decision_started"] = monotonic()
    evaluation = st.session_state.get("evaluation_output")
    if evaluation is None:
        return
    if (
        evaluation.status in {"failed", "invalid_output"}
        and evaluation.stage == "scoring"
        and st.button("Retry scoring only", key="resume_scoring", disabled=not allowed)
    ):
        with st.spinner("Scoring the saved repairs…"):
            evaluation = timed(
                st.session_state,
                "scoring_retry",
                lambda: EvaluationAgent(settings).evaluate(packet, strategy, checkpoint=evaluation),
            )
        st.session_state["evaluation_output"] = evaluation
        if evaluation.status == "completed":
            st.session_state["decision_started"] = monotonic()
    st.caption(f"Evaluation: {evaluation.status} · {evaluation.stage}")
    for warning in evaluation.warnings:
        st.caption(warning)
    render_diagnostics(evaluation)
    for column, repair in zip(st.columns(3), evaluation.repairs, strict=False):
        with column:
            render_summary(repair.architecture, repair.architecture_id, repaired=True)
            for finding, response in unresolved_findings(evaluation, repair.architecture_id):
                kind = (finding.gap_kind or "unclassified").replace("_", " ")
                location = (
                    f"Contention {finding.contention_number}"
                    if finding.contention_number
                    else "Architecture"
                )
                status = response.status.replace("_", " ") if response else "not repaired"
                st.warning(f"{location} · {kind} · {status}: {finding.weakness}")
                if response:
                    st.caption(response.explanation)
            for risk in repair.remaining_risks:
                st.caption(risk)
    with st.expander("Critiques and repair record"):
        for critique in evaluation.critiques:
            st.markdown(f"**Architecture {critique.architecture_id}**")
            for finding in critique.findings:
                st.text(f"{finding.weakness} → {finding.repair_goal}")
        for repair in evaluation.repairs:
            for change in repair.changes:
                st.text(change)
    if evaluation.status != "completed":
        return
    for row in evaluation.rankings:
        with st.expander(f"Rank {row.rank} · Architecture {row.architecture_id} · {row.total}/100"):
            st.write(row.tradeoffs)
            for key, maximum in RUBRIC.items():
                score = getattr(row.scores, key)
                st.text(
                    f"{key.replace('_', ' ').title()}: {score.points}/{maximum} — {score.rationale}"
                )
    st.caption("Warnings identify unresolved risks; you may still select a practice strategy.")
    names = {r.architecture_id: r.architecture.name for r in evaluation.repairs}
    choice = st.selectbox(
        "Your architecture choice",
        [None, 1, 2, 3],
        key="architecture_choice",
        format_func=lambda i: "Choose an architecture" if i is None else f"{i}: {names[i]}",
    )
    if st.button("Confirm architecture choice", disabled=choice is None):
        if choice != evaluation.selected_architecture_id:
            invalidate(st.session_state, "case_output")
            st.info("Architecture changed. Any previous final case has been cleared.")
        evaluation = select_architecture(evaluation, choice)
        st.session_state["evaluation_output"] = evaluation
        started = st.session_state.pop("decision_started", None)
        if started is not None:
            st.session_state["decision_seconds"] = monotonic() - started
    if evaluation.selected_architecture_id is not None:
        st.success(
            f"Confirmed: {names[evaluation.selected_architecture_id]}. Open Final case to write it."
        )
    st.download_button(
        "Download evaluation and choice",
        evaluation.model_dump_json(indent=2),
        file_name="strategy_evaluation.json",
        mime="application/json",
    )


def render_final(packet, settings):
    evaluation = st.session_state.get("evaluation_output")
    strategy = st.session_state.get("strategy_output")
    st.subheader("Your opening speech")
    if evaluation is None or evaluation.selected_architecture_id is None:
        st.info("Evaluate and confirm an architecture in Strategies before writing your case.")
        return
    st.caption(
        "Government: 7 minutes · Opposition: 8 minutes. Grace time is not added to the budget."
    )
    with st.expander("Delivery settings"):
        wpm = st.number_input("Reading speed (words per minute)", 80, 400, 150, key="case_wpm")
        reserve = st.number_input(
            "Reserve for pauses and POIs (seconds)", 0, 120, 30, key="case_reserve"
        )
    if st.button(
        "Write final case",
        key="write_case",
        disabled=not packet.plan.round_input.prep_rules.inference_permitted,
    ):
        invalidate(st.session_state, "case_output")
        with st.spinner("Writing and refining your selected case…"):
            st.session_state["case_output"] = timed(
                st.session_state,
                "case",
                lambda: RoundDirector(settings).write_case(
                    packet,
                    strategy,
                    evaluation,
                    budget=SpeechBudget(words_per_minute=wpm, reserve_seconds=reserve),
                ),
            )
    result = st.session_state.get("case_output")
    if result is None:
        return
    render_diagnostics(result)
    if result.status != "completed":
        st.error(f"Case not completed: {result.status}")
        for warning in result.warnings:
            st.warning(warning)
        return
    left, right = st.columns(2)
    left.metric("Speech length", f"{result.word_count} / {result.word_limit} words")
    right.metric("Estimated delivery", f"{result.estimated_seconds / 60:.1f} min")
    st.caption(
        f"Saved timing: {result.budget.words_per_minute} wpm, "
        f"{result.budget.reserve_seconds}s reserve. Rehearse aloud."
    )
    st.markdown(render_case(result.case, packet))
    with st.expander("Preparation notes and sources"):
        st.markdown(evidence_notes(result.case, packet))
        for warning in result.warnings:
            st.caption(warning)
    st.download_button(
        "Download case (Markdown)",
        result.markdown,
        file_name="debate_case.md",
        mime="text/markdown",
    )
    st.download_button(
        "Download case (JSON)",
        result.model_dump_json(indent=2),
        file_name="debate_case.json",
        mime="application/json",
    )


def restore_saved(settings):
    try:
        directory = settings.project_root / "data" / "parsed" / st.session_state["saved_run"]
        restored = load_checkpoint(directory)
        invalidate(st.session_state, "round_output")
        st.session_state.update(restored)
        context = restored["round_output"].plan.round_input
        st.session_state.update(
            {
                "motion": context.motion,
                "side": {Side.AFF: Side.GOV, Side.NEG: Side.OPP}.get(context.side, context.side),
                "infoslide": context.infoslide or "",
                "round_type": context.round_type,
                "judge": context.judge_category,
                "judge_notes": context.judge_notes or "",
                "round_concepts": "\n".join(context.explicit_concepts),
                "prep_minutes": context.prep_rules.minutes,
                "internet": context.prep_rules.internet_allowed,
                "cloud_inference": context.prep_rules.inference_permitted,
                "round_signature": context.model_dump_json(),
            }
        )
        evaluation = restored.get("evaluation_output")
        if evaluation and evaluation.status == "completed":
            st.session_state["architecture_choice"] = evaluation.selected_architecture_id
            st.session_state["decision_started"] = monotonic()
        st.session_state["checkpoint_notice"] = (
            "Checkpoint loaded locally. No provider request was made."
        )
    except (ValueError, OSError):
        st.session_state["checkpoint_notice"] = (
            "Could not load matching packet and strategy exports."
        )


def main():
    st.set_page_config(page_title="Round preparation", layout="wide")
    st.markdown(
        """<style>
    .block-container { max-width: 1440px; padding-top: 4.5rem; }
    [data-testid="stText"] { white-space: pre-wrap; overflow-wrap: anywhere; }
    [data-testid="stMetricValue"] { font-size: 1.5rem; }
    @media (max-width: 760px) {
      [data-testid="stHorizontalBlock"] { flex-direction: column; }
      [data-testid="stColumn"] { width: 100% !important; flex: 1 1 100% !important; }
    }
    </style>""",
        unsafe_allow_html=True,
    )
    st.caption("DEBATE CASE ENGINE")
    st.title("Round preparation")
    st.write("Build a case you understand. Choose the strategy. Own the ballot story.")
    settings = get_settings().model_copy(deep=True)
    with st.expander("Advanced · model and connection"):
        providers = list(ProviderName)
        provider = st.selectbox(
            "Inference provider",
            providers,
            index=providers.index(settings.strategy.provider),
            key="inference_provider",
        )
        settings.strategy.provider = provider
        config = provider_settings(settings)
        st.caption(
            f"{provider.value} · {config.model or 'provider default'}. "
            "Selected archive excerpts, research and judge notes go to this provider."
        )
        st.caption("Tavily key: " + ("configured" if settings.research.api_key else "missing"))
        if not inference_ready(settings):
            st.info("Configure the selected provider and enable remote access before generation.")
    status = st.empty()
    setup_tab, source_tab, strategy_tab, final_tab = st.tabs(
        ["1 · Round setup", "2 · Sources", "3 · Strategies", "4 · Final case"]
    )
    with setup_tab:
        with st.form("round"):
            motion = st.text_area(
                "Motion", key="motion", placeholder="THW make public transport free"
            )
            infoslide = st.text_area("Infoslide (optional)", key="infoslide")
            left, right = st.columns(2)
            with left:
                side = st.selectbox(
                    "Side",
                    [Side.GOV, Side.OPP],
                    index=None,
                    format_func=lambda x: "Government" if x == Side.GOV else "Opposition",
                    key="side",
                )
                round_type = st.selectbox("Round type", [None, *RoundType], key="round_type")
                judge = st.selectbox(
                    "Judge category",
                    [
                        JudgeCategory.FULLY_LAY,
                        JudgeCategory.FLAY,
                        JudgeCategory.FLOW,
                        JudgeCategory.TECH,
                    ],
                    format_func=lambda x: {
                        "fully_lay": "Lay",
                        "flay": "Flay",
                        "flow": "Flow",
                        "tech": "Tech",
                    }[x],
                    key="judge",
                )
            with right:
                minutes = st.number_input("Prep minutes", 1, 180, 15, key="prep_minutes")
                internet = st.checkbox("Round rules permit internet research", key="internet")
                cloud = st.checkbox("Allow cloud model access", value=True, key="cloud_inference")
                st.caption(
                    "15 minutes + research off selects NYPDL: no theory, Ks or tricks. "
                    "Cloud model access is separate from web research."
                )
            judge_notes = st.text_area("Judge Paradigm/Notes", key="judge_notes")
            concepts = st.text_area("Extra concepts (one per line)", key="round_concepts")
            with st.expander("Advanced · general-format retrieval"):
                theory = st.selectbox("Include theory", [None, True, False])
                kritiks = st.selectbox("Include kritiks", [None, True, False])
                st.caption("NYPDL always excludes these, regardless of the selections above.")
            preview = st.form_submit_button("Preview plan")
            prepare = st.form_submit_button("Prepare knowledge packet", type="primary")
        if preview or prepare:
            try:
                context = RoundInput(
                    motion=motion,
                    infoslide=infoslide.strip() or None,
                    side=side,
                    round_type=round_type,
                    judge_category=judge,
                    judge_notes=judge_notes or None,
                    include_theory=theory,
                    include_kritiks=kritiks,
                    explicit_concepts=[
                        line.strip() for line in concepts.splitlines() if line.strip()
                    ],
                    prep_rules=PrepRules(
                        minutes=int(minutes),
                        internet_allowed=internet,
                        cloud_inference_allowed=cloud,
                    ),
                )
                signature = context.model_dump_json()
                previous = st.session_state.get("round_output")
                changed = st.session_state.get("round_signature") != signature
                if changed:
                    invalidate(st.session_state, "round_output")
                    st.session_state["round_signature"] = signature
                    if previous is not None:
                        st.info(
                            "Round settings changed. Previous sources, strategies and case cleared."
                        )
                current = st.session_state.get("round_output")
                if current is None or (prepare and not hasattr(current, "items")):
                    director = RoundDirector(settings)
                    with st.spinner("Preparing your round…"):
                        st.session_state["round_output"] = timed(
                            st.session_state,
                            "preparation",
                            lambda: (
                                director.prepare(context) if prepare else director.plan(context)
                            ),
                        )
                    if prepare:
                        st.session_state["preparation_timings"] = director.preparation_timings
                else:
                    st.info("Reused the unchanged round. Existing work is preserved.")
            except Exception:
                invalidate(st.session_state, "round_output")
                st.error("Round preparation failed. Check the motion, settings and local indexes.")
        saved_root = settings.project_root / "data" / "parsed"
        checkpoints = sorted(
            {
                path.parent.relative_to(saved_root).as_posix()
                for path in saved_root.glob("**/strategy.json")
            }
        )
        if checkpoints:
            with st.expander("Open a saved checkpoint"):
                st.selectbox("Saved run", checkpoints, key="saved_run")
                st.button(
                    "Load saved strategies",
                    key="load_checkpoint",
                    on_click=restore_saved,
                    args=(settings,),
                )
                if "checkpoint_notice" in st.session_state:
                    st.info(st.session_state["checkpoint_notice"])
        output = st.session_state.get("round_output")
        if output is not None:
            plan = output.plan if hasattr(output, "items") else output
            if plan.round_input.prep_rules.profile == "nypdl":
                st.caption(
                    "NYPDL adaptation: archive + AI, no web research. "
                    "Not a claim of full tournament compliance."
                )
            if st.button(
                "Confirm sides and start prep timer",
                key="start_prep",
                disabled=plan.retrieval_request.side in {None, Side.UNKNOWN},
            ):
                st.session_state["prep_started"] = monotonic()
            prep_clock(plan.round_input.prep_rules.minutes)
    output = st.session_state.get("round_output")
    if output is None:
        status.info("Start with your motion and round settings.")
        return
    packet = output if hasattr(output, "items") else None
    plan = packet.plan if packet is not None else output
    with source_tab:
        render_sources(packet, plan)
    with strategy_tab:
        if packet is not None:
            render_strategies(packet, settings)
        else:
            st.info("Prepare sources before generating architectures.")
    with final_tab:
        if packet is not None:
            render_final(packet, settings)
    phase = (
        "Final case"
        if st.session_state.get("case_output")
        else ("Strategies" if st.session_state.get("strategy_output") else "Sources")
    )
    status.info(
        f"{plan.round_input.prep_rules.profile.upper()} · "
        f"Research: {plan.research_status} · Stage: {phase}"
    )
    st.caption(f"Submitted motion: {plan.round_input.motion}. Submit Round setup to apply edits.")
    with st.expander("Session timing"):
        timing = st.session_state.get("timings", {})
        total = sum(sum(values) for values in timing.values())
        st.write(f"Engine time across this round's requests: {total:.1f}s")
        for stage, seconds in st.session_state.get("preparation_timings", {}).items():
            st.write(f"{stage.title()}: {seconds:.1f}s")
        if "decision_seconds" in st.session_state:
            st.write(f"Architecture review time: {st.session_state['decision_seconds']:.1f}s")


if __name__ == "__main__":
    main()
