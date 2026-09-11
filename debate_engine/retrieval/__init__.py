"""Local embeddings and raw vector-search inspection.

Hierarchical retrieval policy is intentionally deferred to Milestone 8.
"""

from debate_engine.retrieval.embeddings import (
    EmbeddingDimensionError,
    EmbeddingService,
    build_embedding_text,
    embedding_fingerprint,
)
from debate_engine.retrieval.engine import HierarchicalRetriever, retrieve_for_round
from debate_engine.retrieval.queries import (
    clean_motion,
    concept_tokens,
    generate_retrieval_queries,
    infer_query_intents,
)
from debate_engine.retrieval.scoring import (
    CandidateSignals,
    candidate_is_eligible,
    diversify_candidates,
    is_kritik_chunk,
    is_theory_chunk,
    score_candidate,
)
from debate_engine.retrieval.vector_store import (
    SemanticSearchHit,
    SyncFailure,
    VectorIndexConfigurationError,
    VectorIndexStatus,
    VectorStore,
    VectorSyncReport,
    build_where_filter,
    select_eligible_chunks,
    vector_metadata,
)

__all__ = [
    "EmbeddingDimensionError",
    "EmbeddingService",
    "CandidateSignals",
    "HierarchicalRetriever",
    "SemanticSearchHit",
    "SyncFailure",
    "VectorIndexConfigurationError",
    "VectorIndexStatus",
    "VectorStore",
    "VectorSyncReport",
    "build_embedding_text",
    "build_where_filter",
    "candidate_is_eligible",
    "clean_motion",
    "concept_tokens",
    "diversify_candidates",
    "embedding_fingerprint",
    "generate_retrieval_queries",
    "infer_query_intents",
    "is_kritik_chunk",
    "is_theory_chunk",
    "retrieve_for_round",
    "score_candidate",
    "select_eligible_chunks",
    "vector_metadata",
]
