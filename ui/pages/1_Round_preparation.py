"""Round preparation with judge adaptation and permission-gated research."""

import streamlit as st

from debate_engine.agents import RoundDirector
from debate_engine.schemas import JudgeCategory, RoundType, Side
from debate_engine.schemas.rounds import PrepRules, RoundInput


def main() -> None:
    st.set_page_config(page_title="Round preparation", page_icon="📚", layout="wide")
    st.title("Round preparation")
    st.caption("Prepare archive material, judge guidance, and research for your round.")
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
            director = RoundDirector()
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
        "configured OpenAI model. It requires internet-permitted prep and explicit cloud setup."
    )
    preferences = st.text_area("Strategy preferences", key="strategy_preferences")
    if st.button("Generate three architectures", key="generate_strategies"):
        st.session_state.pop("strategy_output", None)
        with st.spinner("Generating architectures…"):
            st.session_state["strategy_output"] = RoundDirector().strategize(
                packet, preferences=preferences
            )
    strategy = st.session_state.get("strategy_output")
    if strategy is not None:
        st.caption(
            f"Strategy status: {strategy.status}. Results reflect the last generation request."
        )
        for warning in strategy.warnings:
            st.warning(warning)
        for index, architecture in enumerate(strategy.architectures, start=1):
            with st.expander(f"Architecture {index}: {architecture.name}", expanded=True):
                st.text(architecture.framing)
                st.text(architecture.route_to_ballot)
                st.caption("What makes this approach distinct")
                st.text(architecture.differs_from_others)
                for contention in architecture.contentions:
                    st.text(contention.title)
                    st.text(contention.claim)
                    st.caption(f"Basis: {contention.basis}")
                st.caption("Judge adaptation")
                st.text(architecture.judge_adaptation)
                st.caption("Initial vulnerability")
                st.text(architecture.main_vulnerability)
                st.json(architecture.model_dump(mode="json"))
        if strategy.status == "completed":
            st.download_button(
                "Download architectures",
                strategy.model_dump_json(indent=2),
                file_name="strategy_architectures.json",
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
