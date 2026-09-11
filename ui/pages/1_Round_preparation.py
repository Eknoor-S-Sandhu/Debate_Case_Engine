"""Milestone 10 round planning and Knowledge Packet inspection."""

import streamlit as st

from debate_engine.agents import RoundDirector
from debate_engine.schemas import JudgeCategory, RoundType, Side
from debate_engine.schemas.rounds import PrepRules, RoundInput


def main() -> None:
    st.set_page_config(page_title="Round preparation", page_icon="📚", layout="wide")
    st.title("Round preparation")
    st.caption("Organize archive material for your round. No case writing or live research yet.")
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
                "Research is deferred. This workflow uses local indexes and cached models only."
            )
        judge_notes = st.text_area("Judge notes (preserved for later adaptation)")
        concepts = st.text_area("Extra concepts (one per line)")
        theory = st.selectbox("Include theory", [None, True, False])
        kritiks = st.selectbox("Include kritiks", [None, True, False])
        preview = st.form_submit_button("Preview plan")
        prepare = st.form_submit_button("Prepare knowledge packet", type="primary")
    if preview or prepare:
        st.session_state.pop("round_output", None)
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
    st.download_button(
        "Download Knowledge Packet",
        packet.model_dump_json(indent=2),
        file_name="knowledge_packet.json",
        mime="application/json",
    )


if __name__ == "__main__":
    main()
