"""Package existing retrieval results without rewriting or inventing archive text."""

from pathlib import Path
from typing import Protocol

from debate_engine.config import Settings, get_settings
from debate_engine.retrieval import HierarchicalRetriever
from debate_engine.retrieval.embeddings import EmbeddingService
from debate_engine.retrieval.queries import infer_query_intents
from debate_engine.retrieval.scoring import candidate_is_eligible, is_kritik_chunk, is_theory_chunk
from debate_engine.retrieval.vector_store import VectorStore
from debate_engine.schemas import (
    ChunkLevel,
    Freshness,
    RetrievalCandidate,
    RetrievalRequest,
    RetrievalResult,
    RoundType,
)
from debate_engine.schemas.rounds import (
    KnowledgeCategory as Category,
)
from debate_engine.schemas.rounds import (
    KnowledgeItem,
    KnowledgePacket,
    RoundPlan,
)


class Retriever(Protocol):
    def retrieve(self, request: RetrievalRequest) -> RetrievalResult: ...


class LocalSemanticSearch:
    """Search existing indexes with cached models only, including online prep.

    Never initialize an absent collection or download a model during a round.
    Errors are handled by the existing retriever's lexical fallback.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.store: VectorStore | None = None
        self.failure: str | None = None

    def semantic_search(self, query: str, **kwargs):
        if self.failure:
            raise RuntimeError(self.failure)
        if self.store is None:
            try:
                if not (self.settings.vector_index.chroma_path / "chroma.sqlite3").is_file():
                    raise RuntimeError("Vector index missing; build it before round preparation.")
                import chromadb

                client = chromadb.PersistentClient(
                    path=str(self.settings.vector_index.chroma_path),
                    settings=chromadb.Settings(anonymized_telemetry=False),
                )
                names = {
                    item if isinstance(item, str) else item.name
                    for item in client.list_collections()
                }
                if self.settings.vector_index.collection_name not in names:
                    raise RuntimeError("Vector collection missing; build it before preparation.")
                self.store = VectorStore(
                    self.settings,
                    client=client,
                    embedding_service=EmbeddingService(self.settings, allow_download=False),
                )
            except Exception as exc:
                self.failure = str(exc)
                raise
        try:
            return self.store.semantic_search(query, **kwargs)
        except Exception as exc:
            self.failure = str(exc)
            raise


_SECTION_CATEGORIES = {
    "uniqueness": Category.UNIQUENESS,
    "uq": Category.UNIQUENESS,
    "link": Category.LINKS,
    "l": Category.LINKS,
    "internal_link": Category.INTERNAL_LINKS,
    "il": Category.INTERNAL_LINKS,
    "warrant": Category.WARRANTS,
    "claim": Category.WARRANTS,
    "solvency": Category.SOLVENCY,
    "harms": Category.UNIQUENESS,
    "impact": Category.IMPACTS,
    "impx": Category.IMPACTS,
    "preempt": Category.PREEMPTS,
    "answer": Category.PREEMPTS,
    "response": Category.PREEMPTS,
    "rebuttal": Category.PREEMPTS,
    "framework": Category.FRAMEWORKS,
    "framing": Category.FRAMEWORKS,
    "impact_calculus": Category.FRAMEWORKS,
    "value": Category.FRAMEWORKS,
    "value_criterion": Category.FRAMEWORKS,
}
_EMPIRICAL = {"uniqueness", "uq", "harms", "solvency", "example", "empirics", "fact"}


def categorize(candidate: RetrievalCandidate) -> Category:
    chunk = candidate.chunk
    if is_theory_chunk(chunk) or is_kritik_chunk(chunk):
        return Category.THEORY_K_OPTIONS
    if chunk.chunk_level is ChunkLevel.ARGUMENT:
        return Category.RELATED_ARGUMENTS
    return _SECTION_CATEGORIES.get(chunk.section_type.casefold(), Category.OTHER_MODULES)


def verification_notes(candidate: RetrievalCandidate, current_year: int) -> list[str]:
    chunk = candidate.chunk
    notes = []
    if chunk.freshness in {Freshness.POSSIBLY_STALE, Freshness.STALE_EMPIRICS}:
        notes.append(
            "Source flags potentially outdated empirics; verify before using as current fact."
        )
    empirical = chunk.section_type.casefold() in _EMPIRICAL
    if empirical and (chunk.year is None or chunk.year < current_year):
        notes.append("Empirical section is undated or from a prior year; currency is unverified.")
    if chunk.year is not None and chunk.year > current_year:
        notes.append("Source year is later than the round year; check its metadata.")
    if candidate.support_level.value == "low":
        notes.append("Low retrieval support; inspect relevance before using this material.")
    return notes


class KnowledgeAgent:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        database: Path | str | None = None,
        retriever: Retriever | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        path = (
            Path(database).expanduser()
            if database is not None
            else self.settings.storage.database_path
        )
        self.database = path if path.is_absolute() else self.settings.project_root / path
        self.retriever = retriever

    def retrieve(self, plan: RoundPlan) -> KnowledgePacket:
        retriever = self.retriever
        if retriever is None:
            if not self.database.is_file():
                raise FileNotFoundError(f"SQLite database does not exist: {self.database}")
            retriever = HierarchicalRetriever(
                self.settings,
                database=self.database,
                semantic_searcher=LocalSemanticSearch(self.settings),
            )
        result = retriever.retrieve(plan.retrieval_request.model_copy(deep=True))
        if result.request != plan.retrieval_request:
            raise ValueError("Retriever returned a result for a different round request.")
        groups = {category: [] for category in Category}
        items = {}
        warnings = list(result.warnings)
        intents = infer_query_intents(plan.retrieval_request, result.generated_queries)
        for candidate in [*result.full_arguments, *result.submodules]:
            if candidate.chunk_id != candidate.chunk.chunk_id:
                raise ValueError("Candidate and source chunk IDs disagree.")
            if candidate.chunk_id in items:
                continue
            eligible, reason = candidate_is_eligible(
                candidate.chunk, plan.retrieval_request, intents
            )
            if not eligible:
                warnings.append(f"Omitted {candidate.chunk_id}: {reason}.")
                continue
            category = categorize(candidate)
            # Nested context is not independently ranked or eligibility checked.
            # Keep its IDs in chunk metadata; do not silently promote it into evidence.
            evidence = candidate.model_copy(deep=True)
            evidence.parent_argument = None
            evidence.related_children = []
            items[candidate.chunk_id] = KnowledgeItem(
                candidate=evidence,
                category=category,
                verification_notes=verification_notes(candidate, plan.round_input.current_year),
            )
            groups[category].append(candidate.chunk_id)
        expected = {
            RoundType.POLICY: [
                Category.UNIQUENESS,
                Category.LINKS,
                Category.SOLVENCY,
                Category.IMPACTS,
            ],
            RoundType.VALUE: [Category.FRAMEWORKS, Category.WARRANTS, Category.IMPACTS],
            RoundType.FACT: [Category.WARRANTS],
        }.get(plan.retrieval_request.round_type, [])
        gaps = [category for category in expected if not groups[category]]
        if gaps:
            warnings.append(
                "Coverage gaps describe selected module categories, not missing archive content."
            )
        if not items:
            warnings.append("No eligible archive material was returned; no content was invented.")
        return KnowledgePacket(
            plan=plan.model_copy(deep=True),
            items=items,
            groups=groups,
            coverage_gaps=gaps,
            statistics=result.statistics.model_copy(deep=True),
            warnings=list(dict.fromkeys(warnings)),
        )
