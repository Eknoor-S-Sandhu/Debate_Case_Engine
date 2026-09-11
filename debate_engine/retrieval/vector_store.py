"""Derived Chroma vector index synchronized from authoritative SQLite chunks."""

from __future__ import annotations

import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

import chromadb

from debate_engine.config import Settings, get_settings
from debate_engine.logging import get_logger
from debate_engine.retrieval.embeddings import (
    EmbeddingService,
    build_embedding_text,
    embedding_fingerprint,
)
from debate_engine.schemas import DebateChunk
from debate_engine.storage import (
    database_connection,
    get_chunk,
    list_chunks,
    list_duplicate_groups,
    resolve_database_path,
)

LOGGER = get_logger("retrieval.vector_store")

_FILTER_FIELDS = frozenset(
    {
        "source_group",
        "document_type",
        "section_type",
        "chunk_level",
        "side",
        "round_type",
        "special_masterfile",
    }
)


class CollectionLike(Protocol):
    name: str
    metadata: Mapping[str, object] | None

    def count(self) -> int: ...

    def get(self, **kwargs: object) -> Mapping[str, Any]: ...

    def upsert(self, **kwargs: object) -> None: ...

    def delete(self, **kwargs: object) -> object: ...

    def query(self, **kwargs: object) -> Mapping[str, Any]: ...


class ClientLike(Protocol):
    def list_collections(self) -> Sequence[object]: ...

    def get_collection(self, name: str, **kwargs: object) -> CollectionLike: ...

    def create_collection(self, name: str, **kwargs: object) -> CollectionLike: ...

    def delete_collection(self, name: str) -> None: ...


class VectorIndexConfigurationError(RuntimeError):
    """Raised when an existing collection has incompatible embedding settings."""


@dataclass(frozen=True, slots=True)
class SyncFailure:
    chunk_ids: tuple[str, ...]
    detail: str


@dataclass(slots=True)
class VectorSyncReport:
    sqlite_chunks_found: int = 0
    eligible_chunks: int = 0
    duplicate_members_skipped: int = 0
    invalid_chunks_skipped: int = 0
    vectors_already_current: int = 0
    vectors_embedded: int = 0
    vectors_updated: int = 0
    stale_vectors_deleted: int = 0
    failures: list[SyncFailure] = field(default_factory=list)
    elapsed_seconds: float = 0.0

    @property
    def failed_chunks(self) -> int:
        return sum(len(failure.chunk_ids) for failure in self.failures)


@dataclass(frozen=True, slots=True)
class VectorIndexStatus:
    collection_name: str
    vector_count: int
    sqlite_chunks: int
    eligible_chunks: int
    duplicate_members_skipped: int
    stale_vectors: int
    model_name: str
    embedding_dimension: int
    normalized: bool
    embedding_schema_version: str
    chroma_path: Path


@dataclass(frozen=True, slots=True)
class SemanticSearchHit:
    chunk_id: str
    distance: float
    similarity: float
    metadata: dict[str, str | int | float | bool]
    chunk: DebateChunk | None = None


def vector_metadata(
    chunk: DebateChunk,
    *,
    fingerprint: str,
) -> dict[str, str | int | float | bool]:
    """Convert query-useful metadata to Chroma-supported scalar values."""
    metadata: dict[str, str | int | float | bool] = {
        "chunk_id": chunk.chunk_id,
        "document_id": chunk.document_id,
        "source_group": chunk.source_group.value,
        "document_type": chunk.document_type.value,
        "section_type": chunk.section_type,
        "chunk_level": chunk.chunk_level.value,
        "side": chunk.side.value,
        "round_type": chunk.round_type.value,
        "freshness": chunk.freshness.value,
        "priority_weight": chunk.priority_weight,
        "special_masterfile": chunk.is_special_masterfile,
        "embedding_fingerprint": fingerprint,
    }
    if chunk.year is not None:
        metadata["year"] = chunk.year
    if chunk.duplicate_group is not None:
        metadata["duplicate_group"] = chunk.duplicate_group
    return metadata


def build_where_filter(
    filters: Mapping[str, str | bool | StrEnum | None] | None,
) -> dict[str, object] | None:
    """Build a safe Chroma equality filter from whitelisted metadata fields."""
    if not filters:
        return None
    conditions: list[dict[str, object]] = []
    for field_name, raw_value in filters.items():
        if raw_value is None:
            continue
        if field_name not in _FILTER_FIELDS:
            raise ValueError(f"{field_name!r} is not a supported vector-search filter")
        value = raw_value.value if isinstance(raw_value, StrEnum) else raw_value
        conditions.append({field_name: {"$eq": value}})
    if not conditions:
        return None
    if len(conditions) == 1:
        return conditions[0]
    return {"$and": conditions}


def select_eligible_chunks(
    chunks: Iterable[DebateChunk],
    representative_ids: set[str],
    *,
    include_duplicate_members: bool = False,
) -> tuple[list[DebateChunk], int, int]:
    """Select valid singleton chunks and preferred duplicate representatives."""
    eligible: list[DebateChunk] = []
    duplicate_skips = 0
    invalid_skips = 0
    for chunk in chunks:
        if not chunk.chunk_id.strip() or not chunk.document_id.strip() or not chunk.text.strip():
            invalid_skips += 1
            LOGGER.warning("Skipping invalid/empty chunk %r.", chunk.chunk_id)
            continue
        if (
            not include_duplicate_members
            and chunk.duplicate_group is not None
            and chunk.chunk_id not in representative_ids
        ):
            duplicate_skips += 1
            continue
        eligible.append(chunk)
    return eligible, duplicate_skips, invalid_skips


class VectorStore:
    """Own collection compatibility, SQLite synchronization, and raw search."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        embedding_service: EmbeddingService | None = None,
        client: ClientLike | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.embedding_service = embedding_service or EmbeddingService(self.settings)
        self._client = client
        self._collection: CollectionLike | None = None

    @property
    def chroma_path(self) -> Path:
        return self.settings.vector_index.chroma_path

    @property
    def collection_name(self) -> str:
        return self.settings.vector_index.collection_name

    @property
    def expected_collection_metadata(self) -> dict[str, str | int | bool]:
        return {
            "model_name": self.settings.embedding_model_name,
            "embedding_dimension": self.settings.embedding_dimension,
            "normalized": self.settings.vector_index.normalize_embeddings,
            "embedding_schema_version": (self.settings.vector_index.embedding_text_schema_version),
            "hnsw:space": "cosine",
        }

    def _get_client(self) -> ClientLike:
        if self._client is None:
            self.chroma_path.mkdir(parents=True, exist_ok=True)
            self._client = chromadb.PersistentClient(path=str(self.chroma_path))
        return self._client

    def _collection_exists(self, client: ClientLike) -> bool:
        return self.collection_name in {
            item if isinstance(item, str) else getattr(item, "name", None)
            for item in client.list_collections()
        }

    def initialize_collection(self, *, rebuild: bool = False) -> CollectionLike:
        """Open a compatible collection or explicitly recreate it.

        ``embedding_function=None`` is passed on every Chroma collection call,
        preventing Chroma's default ONNX model from loading or downloading.
        """
        client = self._get_client()
        exists = self._collection_exists(client)
        if rebuild and exists:
            client.delete_collection(self.collection_name)
            exists = False
        if not exists:
            self._collection = client.create_collection(
                self.collection_name,
                metadata=self.expected_collection_metadata,
                embedding_function=None,
            )
            return self._collection

        collection = client.get_collection(self.collection_name, embedding_function=None)
        actual = collection.metadata or {}
        mismatches = {
            key: (expected, actual.get(key))
            for key, expected in self.expected_collection_metadata.items()
            if actual.get(key) != expected
        }
        if mismatches:
            details = ", ".join(
                f"{key}: expected {expected!r}, found {found!r}"
                for key, (expected, found) in sorted(mismatches.items())
            )
            raise VectorIndexConfigurationError(
                f"Collection {self.collection_name!r} is incompatible ({details}). "
                "Run the vector-index build with --rebuild."
            )
        self._collection = collection
        return collection

    def _representative_ids(self, connection: Any) -> set[str]:
        return {group.representative_chunk_id for group in list_duplicate_groups(connection)}

    def _sqlite_chunks(
        self,
        connection: Any,
        *,
        include_duplicate_members: bool,
    ) -> tuple[list[DebateChunk], int, int, int]:
        chunks = list_chunks(connection)
        eligible, duplicate_skips, invalid_skips = select_eligible_chunks(
            chunks,
            self._representative_ids(connection),
            include_duplicate_members=include_duplicate_members,
        )
        return eligible, len(chunks), duplicate_skips, invalid_skips

    def _index_state(
        self, collection: CollectionLike
    ) -> tuple[set[str], dict[str, Mapping[str, object]]]:
        result = collection.get(include=["metadatas"])
        ids = list(result.get("ids") or [])
        metadatas = list(result.get("metadatas") or [])
        return set(ids), {
            chunk_id: metadata or {} for chunk_id, metadata in zip(ids, metadatas, strict=True)
        }

    def _upsert_batch(
        self,
        collection: CollectionLike,
        chunks: Sequence[DebateChunk],
        *,
        new_ids: set[str],
        report: VectorSyncReport,
    ) -> None:
        texts = [build_embedding_text(chunk) for chunk in chunks]
        try:
            vectors = self.embedding_service.embed_texts(texts)
        except Exception as batch_error:
            if len(chunks) == 1:
                chunk = chunks[0]
                LOGGER.error("Embedding failed for %s: %s", chunk.chunk_id, batch_error)
                report.failures.append(
                    SyncFailure((chunk.chunk_id,), f"{type(batch_error).__name__}: {batch_error}")
                )
                return
            LOGGER.warning("Embedding batch failed; retrying each chunk: %s", batch_error)
            for chunk in chunks:
                self._upsert_batch(
                    collection,
                    [chunk],
                    new_ids=new_ids,
                    report=report,
                )
            return

        metadatas = [
            vector_metadata(
                chunk,
                fingerprint=embedding_fingerprint(
                    text,
                    schema_version=self.settings.vector_index.embedding_text_schema_version,
                ),
            )
            for chunk, text in zip(chunks, texts, strict=True)
        ]
        try:
            collection.upsert(
                ids=[chunk.chunk_id for chunk in chunks],
                embeddings=vectors,
                metadatas=metadatas,
            )
        except Exception as batch_error:
            if len(chunks) == 1:
                chunk = chunks[0]
                LOGGER.error("Vector upsert failed for %s: %s", chunk.chunk_id, batch_error)
                report.failures.append(
                    SyncFailure((chunk.chunk_id,), f"{type(batch_error).__name__}: {batch_error}")
                )
                return
            LOGGER.warning("Vector upsert batch failed; retrying each chunk: %s", batch_error)
            for chunk in chunks:
                self._upsert_batch(
                    collection,
                    [chunk],
                    new_ids=new_ids,
                    report=report,
                )
            return

        report.vectors_embedded += sum(chunk.chunk_id in new_ids for chunk in chunks)
        report.vectors_updated += sum(chunk.chunk_id not in new_ids for chunk in chunks)

    def sync(
        self,
        *,
        database: Path | str | None = None,
        rebuild: bool = False,
        include_duplicate_members: bool = False,
        batch_size: int | None = None,
        limit: int | None = None,
    ) -> VectorSyncReport:
        """Synchronize eligible SQLite chunks into Chroma incrementally."""
        started = time.perf_counter()
        collection = self.initialize_collection(rebuild=rebuild)
        configured_batch = batch_size or self.settings.vector_index.embedding_batch_size
        if configured_batch < 1:
            raise ValueError("batch_size must be at least 1")
        if limit is not None and limit < 1:
            raise ValueError("limit must be at least 1")

        report = VectorSyncReport()
        with database_connection(
            resolve_database_path(database, settings=self.settings),
            settings=self.settings,
        ) as connection:
            eligible, total, duplicate_skips, invalid_skips = self._sqlite_chunks(
                connection,
                include_duplicate_members=include_duplicate_members,
            )

        report.sqlite_chunks_found = total
        report.eligible_chunks = len(eligible)
        report.duplicate_members_skipped = duplicate_skips
        report.invalid_chunks_skipped = invalid_skips

        indexed_ids, indexed_metadata = self._index_state(collection)
        eligible_ids = {chunk.chunk_id for chunk in eligible}
        stale_ids = sorted(indexed_ids - eligible_ids)
        if stale_ids:
            collection.delete(ids=stale_ids)
        report.stale_vectors_deleted = len(stale_ids)

        selected = eligible[:limit] if limit is not None else eligible
        pending: list[DebateChunk] = []
        new_ids: set[str] = set()
        for chunk in selected:
            text = build_embedding_text(chunk)
            fingerprint = embedding_fingerprint(
                text,
                schema_version=self.settings.vector_index.embedding_text_schema_version,
            )
            if chunk.chunk_id not in indexed_ids:
                new_ids.add(chunk.chunk_id)
                pending.append(chunk)
            elif indexed_metadata[chunk.chunk_id].get("embedding_fingerprint") != fingerprint:
                pending.append(chunk)
            else:
                report.vectors_already_current += 1

        for start in range(0, len(pending), configured_batch):
            self._upsert_batch(
                collection,
                pending[start : start + configured_batch],
                new_ids=new_ids,
                report=report,
            )
        report.elapsed_seconds = time.perf_counter() - started
        return report

    def status(
        self,
        *,
        database: Path | str | None = None,
        include_duplicate_members: bool = False,
    ) -> VectorIndexStatus:
        """Compare collection IDs with currently eligible SQLite chunks."""
        collection = self.initialize_collection()
        with database_connection(
            resolve_database_path(database, settings=self.settings),
            settings=self.settings,
        ) as connection:
            eligible, total, duplicate_skips, _ = self._sqlite_chunks(
                connection,
                include_duplicate_members=include_duplicate_members,
            )
        indexed_ids, _ = self._index_state(collection)
        eligible_ids = {chunk.chunk_id for chunk in eligible}
        return VectorIndexStatus(
            collection_name=self.collection_name,
            vector_count=collection.count(),
            sqlite_chunks=total,
            eligible_chunks=len(eligible),
            duplicate_members_skipped=duplicate_skips,
            stale_vectors=len(indexed_ids - eligible_ids),
            model_name=self.settings.embedding_model_name,
            embedding_dimension=self.settings.embedding_dimension,
            normalized=self.settings.vector_index.normalize_embeddings,
            embedding_schema_version=self.settings.vector_index.embedding_text_schema_version,
            chroma_path=self.chroma_path,
        )

    def semantic_search(
        self,
        query: str,
        *,
        database: Path | str | None = None,
        top_k: int = 10,
        filters: Mapping[str, str | bool | StrEnum | None] | None = None,
        hydrate: bool = True,
    ) -> list[SemanticSearchHit]:
        """Run raw cosine vector search without any Milestone 8 reranking."""
        if top_k < 1:
            raise ValueError("top_k must be at least 1")
        collection = self.initialize_collection()
        count = collection.count()
        if count == 0:
            return []
        query_vector = self.embedding_service.embed_query(query)
        result = collection.query(
            query_embeddings=[query_vector],
            n_results=min(top_k, count),
            where=build_where_filter(filters),
            include=["metadatas", "distances"],
        )
        ids = (result.get("ids") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]

        hydrated: dict[str, DebateChunk | None] = dict.fromkeys(ids)
        if hydrate:
            with database_connection(
                resolve_database_path(database, settings=self.settings),
                settings=self.settings,
            ) as connection:
                hydrated = {chunk_id: get_chunk(connection, chunk_id) for chunk_id in ids}

        return [
            SemanticSearchHit(
                chunk_id=chunk_id,
                distance=float(distance),
                similarity=max(-1.0, min(1.0, 1.0 - float(distance))),
                metadata=dict(metadata or {}),
                chunk=hydrated[chunk_id],
            )
            for chunk_id, distance, metadata in zip(
                ids,
                distances,
                metadatas,
                strict=True,
            )
        ]
