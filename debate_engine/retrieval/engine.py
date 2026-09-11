"""High-level deterministic semantic+lexical hierarchical retrieval pipeline."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from debate_engine.config import Settings, get_settings
from debate_engine.ingestion import fuzzy_similarity
from debate_engine.retrieval.queries import (
    concept_tokens,
    generate_retrieval_queries,
    infer_query_intents,
)
from debate_engine.retrieval.scoring import (
    CandidateSignals,
    candidate_is_eligible,
    diversify_candidates,
    score_candidate,
)
from debate_engine.retrieval.vector_store import SemanticSearchHit, VectorStore
from debate_engine.schemas import (
    ChunkLevel,
    GeneratedQuery,
    RetrievalCandidate,
    RetrievalRequest,
    RetrievalResult,
    RetrievalStatistics,
)
from debate_engine.storage import (
    LexicalSearchUnavailableError,
    database_connection,
    get_child_chunks,
    get_chunks_by_ids,
    list_duplicate_groups,
    resolve_database_path,
    search_chunks,
)


class SemanticSearcher(Protocol):
    def semantic_search(
        self,
        query: str,
        *,
        database: Path | str | None = None,
        top_k: int = 10,
        filters: dict[str, object] | None = None,
        hydrate: bool = True,
    ) -> list[SemanticSearchHit]: ...


@dataclass(slots=True)
class _Evidence:
    semantic_score: float = 0.0
    lexical_score: float = 0.0
    semantic_queries: set[str] = field(default_factory=set)
    lexical_queries: set[str] = field(default_factory=set)

    def merge(self, other: _Evidence) -> None:
        self.semantic_score = max(self.semantic_score, other.semantic_score)
        self.lexical_score = max(self.lexical_score, other.lexical_score)
        self.semantic_queries.update(other.semantic_queries)
        self.lexical_queries.update(other.lexical_queries)


class HierarchicalRetriever:
    """Generate queries, gather candidates, score, diversify, and hydrate context."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        semantic_searcher: SemanticSearcher | None = None,
        database: Path | str | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.semantic_searcher = semantic_searcher or VectorStore(self.settings)
        self.database = database

    @staticmethod
    def _canonical_id(chunk_id: str, representatives: dict[str, str]) -> str:
        return representatives.get(chunk_id, chunk_id)

    def _semantic_candidates(
        self,
        queries: list[GeneratedQuery],
        request: RetrievalRequest,
        intents: set[str],
        database: Path,
        representatives: dict[str, str],
        warnings: list[str],
    ) -> tuple[dict[str, _Evidence], int, set[str]]:
        evidence: dict[str, _Evidence] = {}
        raw_hits = 0
        suppressed: set[str] = set()
        requested_filter: dict[str, object] | None = (
            {"source_group": request.source_group.value}
            if request.source_group is not None
            else None
        )
        search_filters = [requested_filter]
        if request.source_group is None and intents & {"theory", "kritik"}:
            search_filters = [
                {"source_group": "personal"},
                {"special_masterfile": True},
            ]
        for search_filter in search_filters:
            for query in queries:
                try:
                    hits = self.semantic_searcher.semantic_search(
                        query.text,
                        database=database,
                        top_k=self.settings.retrieval.semantic_candidates_per_query,
                        filters=search_filter,
                        hydrate=False,
                    )
                except Exception as exc:
                    warnings.append(
                        f"Semantic search failed for {query.text!r}: {type(exc).__name__}: {exc}"
                    )
                    continue
                raw_hits += len(hits)
                for hit in hits:
                    canonical = self._canonical_id(hit.chunk_id, representatives)
                    if canonical != hit.chunk_id:
                        suppressed.add(hit.chunk_id)
                    item = evidence.setdefault(canonical, _Evidence())
                    item.semantic_score = max(item.semantic_score, hit.similarity)
                    item.semantic_queries.add(query.text)

        ranked_ids = sorted(
            evidence,
            key=lambda chunk_id: (-evidence[chunk_id].semantic_score, chunk_id),
        )
        keep = set(ranked_ids[: self.settings.retrieval.semantic_candidate_pool])
        return {key: value for key, value in evidence.items() if key in keep}, raw_hits, suppressed

    def _lexical_candidates(
        self,
        connection: sqlite3.Connection,
        queries: list[GeneratedQuery],
        representatives: dict[str, str],
        warnings: list[str],
    ) -> tuple[dict[str, _Evidence], int, set[str]]:
        evidence: dict[str, _Evidence] = {}
        raw_hits = 0
        suppressed: set[str] = set()
        for query in queries:
            lexical_query = " ".join(concept_tokens(query.text)[:8])
            if not lexical_query:
                continue
            try:
                hits = search_chunks(
                    connection,
                    lexical_query,
                    limit=self.settings.retrieval.lexical_candidates_per_query,
                )
            except (LexicalSearchUnavailableError, sqlite3.Error, ValueError) as exc:
                if not any("Lexical search unavailable" in warning for warning in warnings):
                    warnings.append(f"Lexical search unavailable: {exc}")
                break
            raw_hits += len(hits)
            for rank, hit in enumerate(hits, start=1):
                canonical = self._canonical_id(hit.chunk.chunk_id, representatives)
                if canonical != hit.chunk.chunk_id:
                    suppressed.add(hit.chunk.chunk_id)
                item = evidence.setdefault(canonical, _Evidence())
                rank_score = 1.0 / (1.0 + 0.25 * (rank - 1))
                item.lexical_score = max(item.lexical_score, rank_score)
                item.lexical_queries.add(query.text)

        ranked_ids = sorted(
            evidence,
            key=lambda chunk_id: (-evidence[chunk_id].lexical_score, chunk_id),
        )
        keep = set(ranked_ids[: self.settings.retrieval.lexical_candidate_pool])
        return {key: value for key, value in evidence.items() if key in keep}, raw_hits, suppressed

    @staticmethod
    def _merge_evidence(
        semantic: dict[str, _Evidence],
        lexical: dict[str, _Evidence],
    ) -> dict[str, _Evidence]:
        merged = {chunk_id: item for chunk_id, item in semantic.items()}
        for chunk_id, item in lexical.items():
            merged.setdefault(chunk_id, _Evidence()).merge(item)
        return merged

    def _result_limits(self, request: RetrievalRequest) -> tuple[int, int]:
        arguments = (
            request.desired_arguments
            if request.desired_arguments is not None
            else self.settings.retrieval.default_argument_results
        )
        submodules = (
            request.desired_submodules
            if request.desired_submodules is not None
            else self.settings.retrieval.default_submodule_results
        )
        if (
            request.desired_top_k is not None
            and request.desired_arguments is None
            and request.desired_submodules is None
        ):
            arguments = min(arguments, max(1, request.desired_top_k // 4))
            submodules = max(0, request.desired_top_k - arguments)
        return arguments, submodules

    def _hydrate_hierarchy(
        self,
        connection: sqlite3.Connection,
        candidates: list[RetrievalCandidate],
    ) -> list[RetrievalCandidate]:
        parent_ids = {
            candidate.chunk.parent_argument_id
            for candidate in candidates
            if candidate.chunk.parent_argument_id
        }
        parents = {chunk.chunk_id: chunk for chunk in get_chunks_by_ids(connection, parent_ids)}
        hydrated: list[RetrievalCandidate] = []
        for candidate in candidates:
            parent = (
                parents.get(candidate.chunk.parent_argument_id)
                if candidate.chunk.parent_argument_id
                else None
            )
            children = (
                get_child_chunks(
                    connection,
                    candidate.chunk.chunk_id,
                    limit=self.settings.retrieval.max_related_children,
                )
                if candidate.chunk.chunk_level is ChunkLevel.ARGUMENT
                and self.settings.retrieval.max_related_children
                else []
            )
            hydrated.append(
                candidate.model_copy(
                    update={"parent_argument": parent, "related_children": children}
                )
            )
        return hydrated

    def retrieve(self, request: RetrievalRequest) -> RetrievalResult:
        """Execute the complete Milestone 8 retrieval pipeline."""
        queries = generate_retrieval_queries(request, settings=self.settings)
        intents = infer_query_intents(request, queries)
        warnings: list[str] = []
        database = resolve_database_path(self.database, settings=self.settings)

        with database_connection(database, settings=self.settings) as connection:
            groups = list_duplicate_groups(connection)
            representatives = {
                member_id: group.representative_chunk_id
                for group in groups
                for member_id in group.member_chunk_ids
            }
            semantic, semantic_hits, semantic_suppressed = self._semantic_candidates(
                queries,
                request,
                intents,
                database,
                representatives,
                warnings,
            )
            lexical, lexical_hits, lexical_suppressed = self._lexical_candidates(
                connection,
                queries,
                representatives,
                warnings,
            )
            evidence = self._merge_evidence(semantic, lexical)
            chunks = {chunk.chunk_id: chunk for chunk in get_chunks_by_ids(connection, evidence)}

            scored: list[RetrievalCandidate] = []
            ineligible = 0
            below_threshold = 0
            for chunk_id in sorted(evidence):
                chunk = chunks.get(chunk_id)
                if chunk is None:
                    warnings.append(f"Candidate {chunk_id!r} is missing from SQLite.")
                    continue
                eligible, _ = candidate_is_eligible(chunk, request, intents)
                if not eligible:
                    ineligible += 1
                    continue
                item = evidence[chunk_id]
                candidate = score_candidate(
                    chunk,
                    CandidateSignals(
                        semantic_score=item.semantic_score,
                        lexical_score=item.lexical_score,
                        semantic_query_matches=len(item.semantic_queries),
                        lexical_query_matches=len(item.lexical_queries),
                    ),
                    request,
                    intents,
                    settings=self.settings,
                )
                if candidate.base_score < self.settings.retrieval.minimum_base_relevance:
                    below_threshold += 1
                    continue
                scored.append(candidate)

            argument_limit, submodule_limit = self._result_limits(request)
            argument_candidates = [
                candidate
                for candidate in scored
                if candidate.chunk.chunk_level is not ChunkLevel.SUBMODULE
            ]
            submodule_candidates = [
                candidate
                for candidate in scored
                if candidate.chunk.chunk_level is ChunkLevel.SUBMODULE
            ]
            full_arguments = diversify_candidates(
                argument_candidates,
                argument_limit,
                settings=self.settings,
            )
            selected_argument_texts = [candidate.chunk.text for candidate in full_arguments]
            nonredundant_submodules = [
                candidate
                for candidate in submodule_candidates
                if not any(
                    fuzzy_similarity(candidate.chunk.text, argument_text) >= 0.98
                    for argument_text in selected_argument_texts
                )
            ]
            redundant_suppressed = len(submodule_candidates) - len(nonredundant_submodules)
            submodules = diversify_candidates(
                nonredundant_submodules,
                submodule_limit,
                settings=self.settings,
            )
            full_arguments = self._hydrate_hierarchy(connection, full_arguments)
            submodules = self._hydrate_hierarchy(connection, submodules)

        if not full_arguments and not submodules:
            warnings.append("No archive material met the minimum relevance and eligibility rules.")
        duplicate_suppressed = len(semantic_suppressed | lexical_suppressed)
        return RetrievalResult(
            request=request,
            generated_queries=queries,
            full_arguments=full_arguments,
            submodules=submodules,
            statistics=RetrievalStatistics(
                semantic_hits=semantic_hits,
                lexical_hits=lexical_hits,
                merged_candidates=len(evidence),
                hydrated_candidates=len(chunks),
                ineligible_candidates=ineligible,
                duplicate_candidates_suppressed=duplicate_suppressed,
                redundant_candidates_suppressed=redundant_suppressed,
                below_relevance_threshold=below_threshold,
                full_arguments_returned=len(full_arguments),
                submodules_returned=len(submodules),
            ),
            warnings=warnings,
        )


def retrieve_for_round(
    request: RetrievalRequest,
    *,
    settings: Settings | None = None,
    semantic_searcher: SemanticSearcher | None = None,
    database: Path | str | None = None,
) -> RetrievalResult:
    """Convenience API for one deterministic hierarchical retrieval request."""
    return HierarchicalRetriever(
        settings,
        semantic_searcher=semantic_searcher,
        database=database,
    ).retrieve(request)
