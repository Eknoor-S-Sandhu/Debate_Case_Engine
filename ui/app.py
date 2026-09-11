"""Milestone 9: local Streamlit tester for the Milestone 8 retriever."""

from pathlib import Path

import streamlit as st

from debate_engine.config import get_settings
from debate_engine.retrieval import HierarchicalRetriever
from debate_engine.schemas import (
    DebateChunk,
    JudgeCategory,
    RetrievalCandidate,
    RetrievalRequest,
    RoundType,
    Side,
    SourceGroup,
)


def show_chunk(chunk: DebateChunk) -> None:
    """Render archive text literally, including its original provenance."""
    st.text(chunk.text)
    st.caption("Source file")
    st.text(chunk.source_path)
    st.json(
        chunk.model_dump(mode="json", exclude={"text"}),
        expanded=False,
    )


def show_candidate(candidate: RetrievalCandidate) -> None:
    chunk = candidate.chunk
    heading = " > ".join(chunk.heading_path) or chunk.original_heading or chunk.section_type
    with st.container(border=True):
        st.subheader(f"{candidate.rank or '—'}. {chunk.source_file}")
        st.text(heading)
        st.caption(
            f"Score {candidate.final_score:.4f} · Support {candidate.support_level.value} · "
            f"{chunk.source_group.value} · {chunk.section_type} · {chunk.chunk_level.value}"
        )
        show_chunk(chunk)
        with st.expander("Score breakdown and ranking reasons"):
            st.json(
                candidate.model_dump(
                    mode="json",
                    exclude={"chunk", "parent_argument", "related_children"},
                )
            )
        if candidate.parent_argument:
            with st.expander("Parent argument"):
                show_chunk(candidate.parent_argument)
        if candidate.related_children:
            with st.expander("Related submodules"):
                for child in candidate.related_children:
                    st.text(" > ".join(child.heading_path) or child.section_type)
                    show_chunk(child)


def main() -> None:
    st.set_page_config(page_title="Debate retrieval tester", page_icon="📚", layout="wide")
    st.title("Debate retrieval tester")
    st.caption("Search your debate library for full arguments and reusable submodules.")
    settings = get_settings()
    with st.form("retrieval"):
        motion = st.text_area("Motion or search query", key="motion")
        left, middle, right = st.columns(3)
        with left:
            side = st.selectbox("Side context", [None, *Side], key="side")
            source = st.selectbox("Source filter", [None, *SourceGroup], key="source")
        with middle:
            round_type = st.selectbox("Round type", [None, *RoundType], key="round_type")
            judge = st.selectbox("Judge category", [None, *JudgeCategory], key="judge")
        with right:
            arguments = st.number_input(
                "Full arguments",
                min_value=0,
                value=settings.retrieval.default_argument_results,
                step=1,
                key="arguments",
            )
            modules = st.number_input(
                "Submodules",
                min_value=0,
                value=settings.retrieval.default_submodule_results,
                step=1,
                key="modules",
            )
        st.caption(
            "None uses the default rules. Side and round type guide ranking; "
            "the source filter restricts results."
        )
        with st.expander("Additional search options"):
            theory = st.selectbox("Include theory", [None, True, False], key="theory")
            kritiks = st.selectbox("Include kritiks", [None, True, False], key="kritiks")
            concepts = st.text_area("Extra concepts (one per line)", key="concepts")
            queries = st.text_area("Extra queries (one per line)", key="queries")
            database = st.text_input("SQLite database", str(settings.storage.database_path))
            st.caption(f"Vector index: {settings.vector_index.chroma_path}")
        submitted = st.form_submit_button("Retrieve", type="primary")

    if submitted:
        # A failed new search must never leave old results looking current.
        st.session_state.pop("retrieval_result", None)
        try:
            request = RetrievalRequest(
                motion=motion,
                side=side,
                round_type=round_type,
                judge_category=judge,
                source_group=source,
                desired_arguments=int(arguments),
                desired_submodules=int(modules),
                include_theory=theory,
                include_kritiks=kritiks,
                explicit_concepts=[line.strip() for line in concepts.splitlines() if line.strip()],
                user_queries=[line.strip() for line in queries.splitlines() if line.strip()],
            )
            if arguments == 0 and modules == 0:
                raise ValueError("Request at least one full argument or submodule.")
            path = Path(database).expanduser()
            if not path.is_absolute():
                path = settings.project_root / path
            if not path.is_file():
                raise ValueError(
                    f"SQLite database does not exist: {path}. Build the database first."
                )
            with st.spinner("Searching your debate library…"):
                result = HierarchicalRetriever(settings, database=path).retrieve(request)
            st.session_state["retrieval_result"] = result
        except Exception as exc:
            st.error(f"Retrieval could not finish: {exc}")
            st.info("Check the database and vector index. See the README setup instructions.")

    result = st.session_state.get("retrieval_result")
    if result is None:
        st.info("Enter a motion and select Retrieve to search your existing indexes.")
        return
    st.subheader("Results for")
    st.text(result.request.motion)
    st.caption("Results reflect the last submitted search. Submit again to apply edited options.")
    for warning in result.warnings:
        st.warning(warning)
    if not result.full_arguments and not result.submodules:
        st.info(
            "No matching material. Try a broader query or different source and eligibility options."
        )
    arguments_tab, modules_tab, details_tab = st.tabs(
        ["Full arguments", "Submodules", "Search details"]
    )
    with arguments_tab:
        if not result.full_arguments:
            st.info("No full arguments met the retrieval rules.")
        for candidate in result.full_arguments:
            show_candidate(candidate)
    with modules_tab:
        if not result.submodules:
            st.info("No submodules met the retrieval rules.")
        for candidate in result.submodules:
            show_candidate(candidate)
    with details_tab:
        st.caption("Support is a retrieval signal, not a probability that an argument is correct.")
        st.write("Submitted request")
        st.json(result.request.model_dump(mode="json"))
        st.write("Generated queries")
        st.json([query.model_dump(mode="json") for query in result.generated_queries])
        st.write("Retrieval statistics")
        st.json(result.statistics.model_dump(mode="json"))


if __name__ == "__main__":
    main()
