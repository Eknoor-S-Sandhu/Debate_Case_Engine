"""Embedding representation and lazy service tests without model downloads."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from debate_engine.config import Settings
from debate_engine.retrieval.embeddings import (
    EmbeddingDimensionError,
    EmbeddingService,
    build_embedding_text,
    embedding_fingerprint,
)
from debate_engine.schemas import ChunkLevel, DebateChunk


def make_chunk(**overrides: object) -> DebateChunk:
    fields: dict[str, object] = {
        "chunk_id": "chunk-1",
        "document_id": "doc-1",
        "source_file": "case.md",
        "source_path": "/archive/case.md",
        "section_type": "internal_link",
        "chunk_level": ChunkLevel.SUBMODULE,
        "argument_heading": "Economy",
        "original_heading": "Investor Confidence",
        "heading_path": ["Contention 1", "Economy", "Investor Confidence"],
        "text": "Regulatory uncertainty can delay private investment.",
        "token_count": 7,
    }
    fields.update(overrides)
    return DebateChunk(**fields)  # type: ignore[arg-type]


class FakeArray:
    def __init__(self, values: list[list[float]]) -> None:
        self.values = values

    def tolist(self) -> list[list[float]]:
        return self.values


class FakeModel:
    def __init__(self, dimension: int = 3) -> None:
        self.dimension = dimension
        self.calls: list[tuple[list[str], dict[str, object]]] = []

    def get_sentence_embedding_dimension(self) -> int:
        return self.dimension

    def encode(self, inputs, **kwargs):
        self.calls.append((list(inputs), kwargs))
        return FakeArray([[float(index + 1) for index in range(self.dimension)] for _ in inputs])


def fake_settings(tmp_path: Path, *, dimension: int = 3) -> Settings:
    return Settings(
        project_root=tmp_path,
        embedding_model_name="fake/bge",
        embedding_dimension=dimension,
        vector_index={"embedding_batch_size": 2},
    )


def test_embedding_service_accepts_batches_and_normalizes_consistently(tmp_path: Path) -> None:
    model = FakeModel()
    service = EmbeddingService(fake_settings(tmp_path), model_factory=lambda *args, **kwargs: model)

    vectors = service.embed_texts(["first", "second"])

    assert vectors == [[1.0, 2.0, 3.0], [1.0, 2.0, 3.0]]
    assert model.calls[0][0] == ["first", "second"]
    assert model.calls[0][1]["normalize_embeddings"] is True
    assert model.calls[0][1]["batch_size"] == 2


def test_embedding_service_is_lazy(tmp_path: Path) -> None:
    loads = 0
    model = FakeModel()
    load_options: list[dict[str, object]] = []

    def factory(*args, **kwargs):
        nonlocal loads
        loads += 1
        load_options.append(kwargs)
        return model

    service = EmbeddingService(fake_settings(tmp_path), model_factory=factory)
    assert not service.is_loaded
    assert loads == 0

    service.embed_texts(["text"])

    assert service.is_loaded
    assert loads == 1
    assert load_options[0]["local_files_only"] is True
    service.embed_texts(["again"])
    assert loads == 1


def test_model_dimension_is_validated_before_encoding(tmp_path: Path) -> None:
    service = EmbeddingService(
        fake_settings(tmp_path, dimension=3),
        model_factory=lambda *args, **kwargs: FakeModel(dimension=2),
    )

    with pytest.raises(EmbeddingDimensionError, match="reports 2"):
        service.embed_texts(["text"])


def test_model_download_is_used_only_after_cache_miss(tmp_path: Path) -> None:
    attempts: list[bool] = []
    model = FakeModel()

    def factory(*args, **kwargs):
        local_only = kwargs["local_files_only"]
        attempts.append(local_only)
        if local_only:
            raise OSError("not cached")
        return model

    service = EmbeddingService(fake_settings(tmp_path), model_factory=factory)

    assert service.embed_texts(["text"]) == [[1.0, 2.0, 3.0]]
    assert attempts == [True, False]


def test_returned_vector_dimension_is_validated(tmp_path: Path) -> None:
    model = FakeModel(dimension=3)

    def wrong_encode(inputs, **kwargs):
        return [[1.0, 2.0] for _ in inputs]

    model.encode = wrong_encode  # type: ignore[method-assign]
    service = EmbeddingService(fake_settings(tmp_path), model_factory=lambda *args, **kwargs: model)

    with pytest.raises(EmbeddingDimensionError, match="received 2"):
        service.embed_texts(["text"])


def test_bge_query_instruction_is_query_only(tmp_path: Path) -> None:
    model = FakeModel()
    settings = fake_settings(tmp_path)
    service = EmbeddingService(settings, model_factory=lambda *args, **kwargs: model)

    service.embed_texts(["document passage"])
    service.embed_query("economic growth")

    assert model.calls[0][0] == ["document passage"]
    assert model.calls[1][0] == [
        "Represent this sentence for searching relevant passages: economic growth"
    ]


def test_embedding_input_is_deterministic_contextual_and_excludes_ranking_data() -> None:
    chunk = make_chunk(priority_weight=9.0, duplicate_group="dup-1")

    first = build_embedding_text(chunk)
    second = build_embedding_text(chunk)

    assert first == second
    assert "[Path: Contention 1 > Economy > Investor Confidence]" in first
    assert "[Section: internal_link]" in first
    assert first.endswith(chunk.text)
    assert "9.0" not in first
    assert "dup-1" not in first


def test_embedding_input_avoids_repeating_headings_already_in_text() -> None:
    chunk = make_chunk(
        text="Economy\nInvestor Confidence\nRegulation delays investment.",
    )

    representation = build_embedding_text(chunk)

    assert "[Argument: Economy]" not in representation
    assert "[Heading: Investor Confidence]" not in representation
    assert "[Path: Contention 1]" in representation


def test_embedding_fingerprint_is_deterministic_and_schema_sensitive() -> None:
    first = embedding_fingerprint("same text", schema_version="v1")

    assert first == embedding_fingerprint("same text", schema_version="v1")
    assert first != embedding_fingerprint("changed text", schema_version="v1")
    assert first != embedding_fingerprint("same text", schema_version="v2")
    assert len(first) == 64


def test_import_does_not_load_sentence_transformers_or_torch() -> None:
    command = (
        "import sys; import debate_engine.retrieval.embeddings; "
        "assert 'sentence_transformers' not in sys.modules; "
        "assert 'torch' not in sys.modules"
    )
    result = subprocess.run(
        [sys.executable, "-c", command],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
