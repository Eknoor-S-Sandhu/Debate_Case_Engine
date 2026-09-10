"""Lazy, explicit SentenceTransformers embeddings for debate chunks."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Callable, Sequence
from typing import Any, Protocol

from debate_engine.config import Settings, get_settings
from debate_engine.schemas import DebateChunk

_SPACE = re.compile(r"\s+")


class EmbeddingModel(Protocol):
    """Small subset of SentenceTransformer used by the service."""

    def get_sentence_embedding_dimension(self) -> int | None: ...

    def encode(self, inputs: Sequence[str], **kwargs: object) -> Any: ...


ModelFactory = Callable[..., EmbeddingModel]


def _comparison_text(value: str) -> str:
    return _SPACE.sub(" ", unicodedata.normalize("NFKC", value).casefold()).strip()


def build_embedding_text(chunk: DebateChunk) -> str:
    """Construct deterministic debate context followed by untouched chunk text.

    Context headings already visible near the start of the chunk are not
    repeated. Ranking metadata such as source priority, freshness, and duplicate
    status is deliberately excluded.
    """
    text = chunk.text
    leading = _comparison_text(text[:500])
    context: list[str] = []

    path = [heading.strip() for heading in chunk.heading_path if heading.strip()]
    unseen_path = [heading for heading in path if _comparison_text(heading) not in leading]
    if unseen_path:
        context.append(f"[Path: {' > '.join(unseen_path)}]")

    path_values = {_comparison_text(heading) for heading in path}
    if (
        chunk.argument_heading
        and _comparison_text(chunk.argument_heading) not in leading
        and _comparison_text(chunk.argument_heading) not in path_values
    ):
        context.append(f"[Argument: {chunk.argument_heading.strip()}]")

    if (
        chunk.original_heading
        and _comparison_text(chunk.original_heading) not in leading
        and _comparison_text(chunk.original_heading) not in path_values
        and _comparison_text(chunk.original_heading)
        != _comparison_text(chunk.argument_heading or "")
    ):
        context.append(f"[Heading: {chunk.original_heading.strip()}]")

    context.append(f"[Section: {chunk.section_type}]")
    return "\n".join([*context, "", text])


def embedding_fingerprint(text: str, *, schema_version: str) -> str:
    """Hash the exact embedding input and its representation schema."""
    payload = f"{schema_version}\0{text}".encode()
    return hashlib.sha256(payload).hexdigest()


class EmbeddingDimensionError(ValueError):
    """Raised when a model returns vectors with an incompatible dimension."""


class EmbeddingService:
    """Lazily load and call the configured SentenceTransformer model.

    Both passage and query vectors are L2-normalized for cosine distance. BGE's
    retrieval instruction is applied to queries only; document chunks use the
    explicit contextual representation from :func:`build_embedding_text`.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        model_factory: ModelFactory | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._model_factory = model_factory
        self._model: EmbeddingModel | None = None

    @property
    def is_loaded(self) -> bool:
        """Report whether the transformer model has been instantiated."""
        return self._model is not None

    @property
    def model_name(self) -> str:
        return self.settings.embedding_model_name

    @property
    def dimension(self) -> int:
        return self.settings.embedding_dimension

    def _load_model(self) -> EmbeddingModel:
        if self._model is not None:
            return self._model
        factory = self._model_factory
        if factory is None:
            # Importing this package initializes PyTorch, so keep it behind the
            # first actual embedding call rather than module import.
            from sentence_transformers import SentenceTransformer

            factory = SentenceTransformer
        model_kwargs = {
            "cache_folder": str(self.settings.model_cache_dir),
            "device": "cpu",
        }
        try:
            model = factory(self.model_name, local_files_only=True, **model_kwargs)
        except Exception as cache_error:
            try:
                model = factory(self.model_name, local_files_only=False, **model_kwargs)
            except Exception as download_error:
                raise download_error from cache_error
        dimension_getter = getattr(model, "get_embedding_dimension", None)
        model_dimension = (
            dimension_getter()
            if callable(dimension_getter)
            else model.get_sentence_embedding_dimension()
        )
        if model_dimension != self.dimension:
            raise EmbeddingDimensionError(
                f"Configured dimension is {self.dimension}, but {self.model_name!r} "
                f"reports {model_dimension}. Fix configuration and rebuild the index."
            )
        self._model = model
        return model

    def _encode(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        model = self._load_model()
        encoded = model.encode(
            list(texts),
            batch_size=min(len(texts), self.settings.vector_index.embedding_batch_size),
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=self.settings.vector_index.normalize_embeddings,
        )
        raw_vectors = encoded.tolist() if hasattr(encoded, "tolist") else list(encoded)
        vectors = [[float(value) for value in vector] for vector in raw_vectors]
        for vector in vectors:
            if len(vector) != self.dimension:
                raise EmbeddingDimensionError(
                    f"Expected {self.dimension} values, received {len(vector)}."
                )
        if len(vectors) != len(texts):
            raise ValueError(
                f"Embedding model returned {len(vectors)} vectors for {len(texts)} texts."
            )
        return vectors

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed document representations without a query instruction."""
        return self._encode(texts)

    def embed_query(self, text: str) -> list[float]:
        """Embed one query with the BGE retrieval instruction."""
        query = text.strip()
        if not query:
            raise ValueError("semantic search query must not be empty")
        instruction = self.settings.vector_index.query_instruction
        return self._encode([f"{instruction}{query}"])[0]
