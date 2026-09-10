"""Local embeddings and raw vector-search inspection.

Hierarchical retrieval policy is intentionally deferred to Milestone 8.
"""

from debate_engine.retrieval.embeddings import (
    EmbeddingDimensionError,
    EmbeddingService,
    build_embedding_text,
    embedding_fingerprint,
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
    "SemanticSearchHit",
    "SyncFailure",
    "VectorIndexConfigurationError",
    "VectorIndexStatus",
    "VectorStore",
    "VectorSyncReport",
    "build_embedding_text",
    "build_where_filter",
    "embedding_fingerprint",
    "select_eligible_chunks",
    "vector_metadata",
]
