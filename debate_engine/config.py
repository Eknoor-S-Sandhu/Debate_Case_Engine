"""Central configuration for the Debate Case Engine.

Every value here can be overridden through environment variables prefixed with
``DEBATE_ENGINE_`` or through a local ``.env`` file. Nested groups use a double
underscore, for example ``DEBATE_ENGINE_SOURCE_WEIGHTS__PERSONAL=1.2``.

Paths are always derived from the repository location, never hardcoded to a
particular machine. Relative path overrides are resolved against the project
root, and absolute overrides are honoured as given.
"""

from __future__ import annotations

import sys

MINIMUM_PYTHON_VERSION: tuple[int, int] = (3, 12)


def check_python_version() -> None:
    """Fail loudly and legibly on an unsupported interpreter.

    A bare ``python3`` on macOS is often the 3.9 system interpreter, which will
    otherwise fail much later with a confusing syntax or dependency error.
    """
    if sys.version_info < MINIMUM_PYTHON_VERSION:
        required = ".".join(str(part) for part in MINIMUM_PYTHON_VERSION)
        running = ".".join(str(part) for part in sys.version_info[:3])
        raise RuntimeError(
            f"Debate Case Engine requires Python {required} or newer, but this "
            f"process is running Python {running} from {sys.executable}.\n"
            "Activate the project virtual environment first:\n"
            "    source .venv/bin/activate"
        )


check_python_version()

from functools import lru_cache  # noqa: E402
from pathlib import Path  # noqa: E402

from pydantic import BaseModel, Field, model_validator  # noqa: E402
from pydantic_settings import BaseSettings, SettingsConfigDict  # noqa: E402

# The package lives at <project_root>/debate_engine/config.py
_PROJECT_ROOT = Path(__file__).resolve().parent.parent

_DIRECTORY_FIELDS = (
    "data_dir",
    "raw_data_dir",
    "parsed_data_dir",
    "index_dir",
    "model_cache_dir",
)


class SourceWeights(BaseModel):
    """Retrieval priority multipliers applied by provenance.

    Personally written material outranks collected material, and a personal
    masterfile outranks an ordinary personal file.
    """

    personal_masterfile: float = Field(default=1.15, ge=0.0)
    personal: float = Field(default=1.10, ge=0.0)
    past_case: float = Field(default=1.05, ge=0.0)
    other: float = Field(default=0.90, ge=0.0)


class MotionSimilarityBoosts(BaseModel):
    """Placeholder multipliers for how closely a chunk matches the motion.

    Values are not consumed yet; scoring lands with retrieval in Milestone 8.
    """

    exact_motion_match: float = Field(default=1.25, ge=0.0)
    same_topic_area: float = Field(default=1.10, ge=0.0)
    related_topic: float = Field(default=1.00, ge=0.0)
    unrelated_topic: float = Field(default=0.85, ge=0.0)


class FreshnessModifiers(BaseModel):
    """Placeholder multipliers keyed by the ``Freshness`` levels of a chunk.

    Values are not consumed yet; scoring lands with retrieval in Milestone 8.
    """

    current: float = Field(default=1.10, ge=0.0)
    evergreen: float = Field(default=1.00, ge=0.0)
    possibly_stale: float = Field(default=0.95, ge=0.0)
    stale_empirics: float = Field(default=0.85, ge=0.0)
    unknown: float = Field(default=1.00, ge=0.0)


class SourceGroupPatterns(BaseModel):
    """Normalized folder-name hints used during source-group inference.

    Discovery owns the matching behavior; configuration owns the vocabulary so
    archive-specific naming can be adjusted without editing parser code.
    """

    personal: tuple[str, ...] = (
        "personal",
        "personal files",
        "personal debate files",
        "my files",
        "my debate files",
    )
    past_case: tuple[str, ...] = (
        "past case",
        "past cases",
        "previous case",
        "previous cases",
        "old case",
        "old cases",
    )
    other: tuple[str, ...] = (
        "other",
        "other files",
        "other debate files",
        "non personal",
        "non personal files",
        "non personal debate files",
    )


class StructureDetectionSettings(BaseModel):
    """Thresholds for deterministic heading and structure detection."""

    style_heading_confidence: float = Field(default=0.98, ge=0.0, le=1.0)
    keyword_heading_confidence: float = Field(default=0.88, ge=0.0, le=1.0)
    numbered_heading_confidence: float = Field(default=0.80, ge=0.0, le=1.0)
    formatted_heading_confidence: float = Field(default=0.68, ge=0.0, le=1.0)
    uppercase_heading_confidence: float = Field(default=0.62, ge=0.0, le=1.0)
    colon_heading_confidence: float = Field(default=0.58, ge=0.0, le=1.0)
    minimum_section_confidence: float = Field(default=0.55, ge=0.0, le=1.0)
    max_heading_words: int = Field(default=12, ge=1)
    max_heading_characters: int = Field(default=120, ge=1)


class ChunkingSettings(BaseModel):
    """Limits used only when a document has no reliable semantic structure."""

    fallback_max_tokens: int = Field(default=450, ge=20)
    fallback_overlap_tokens: int = Field(default=45, ge=0)

    @model_validator(mode="after")
    def _validate_overlap(self) -> ChunkingSettings:
        if self.fallback_overlap_tokens >= self.fallback_max_tokens:
            raise ValueError("fallback_overlap_tokens must be smaller than fallback_max_tokens")
        return self


class Settings(BaseSettings):
    """Runtime settings for the knowledge and retrieval foundation."""

    model_config = SettingsConfigDict(
        env_prefix="DEBATE_ENGINE_",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Paths -------------------------------------------------------------
    project_root: Path = _PROJECT_ROOT
    data_dir: Path = Path("data")
    raw_data_dir: Path = Path("data/raw")
    parsed_data_dir: Path = Path("data/parsed")
    index_dir: Path = Path("data/indexes")
    model_cache_dir: Path = Path("data/models")

    # --- Embeddings --------------------------------------------------------
    embedding_model_name: str = "BAAI/bge-small-en-v1.5"
    embedding_dimension: int = Field(default=384, gt=0)

    # --- Retrieval ---------------------------------------------------------
    default_top_k: int = Field(default=20, gt=0)

    # --- Scoring -----------------------------------------------------------
    source_weights: SourceWeights = Field(default_factory=SourceWeights)
    motion_similarity_boosts: MotionSimilarityBoosts = Field(default_factory=MotionSimilarityBoosts)
    freshness_modifiers: FreshnessModifiers = Field(default_factory=FreshnessModifiers)
    source_group_patterns: SourceGroupPatterns = Field(default_factory=SourceGroupPatterns)
    structure_detection: StructureDetectionSettings = Field(
        default_factory=StructureDetectionSettings
    )
    chunking: ChunkingSettings = Field(default_factory=ChunkingSettings)

    # --- Deduplication -----------------------------------------------------
    duplicate_similarity_threshold: float = Field(default=0.92, ge=0.0, le=1.0)

    # --- Special masterfiles -----------------------------------------------
    special_masterfiles: tuple[str, ...] = (
        "Case File Sandhu",
        "Theory File - Sandhu",
    )

    @model_validator(mode="after")
    def _anchor_directories_to_project_root(self) -> Settings:
        """Resolve relative directory settings against the configured root.

        Anchoring happens after all fields are set so that overriding
        ``project_root`` also moves every directory that was left relative.
        """
        root = self.project_root.resolve()
        object.__setattr__(self, "project_root", root)
        for name in _DIRECTORY_FIELDS:
            value: Path = getattr(self, name)
            resolved = value if value.is_absolute() else root / value
            object.__setattr__(self, name, resolved.resolve())
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings instance."""
    return Settings()
