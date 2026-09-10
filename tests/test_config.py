"""Settings tests: loading, paths, source weights, and masterfile names."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from debate_engine.config import (
    MINIMUM_PYTHON_VERSION,
    Settings,
    check_python_version,
    get_settings,
)

# --- 7. Config loads -------------------------------------------------------


def test_settings_load_with_defaults() -> None:
    settings = Settings()

    assert settings.embedding_model_name == "BAAI/bge-small-en-v1.5"
    assert settings.embedding_dimension == 384
    assert settings.default_top_k == 20
    assert settings.duplicate_similarity_threshold == pytest.approx(0.92)


def test_get_settings_is_cached() -> None:
    assert get_settings() is get_settings()


def test_paths_are_absolute_and_anchored_under_the_project_root() -> None:
    settings = Settings()

    assert settings.project_root.is_absolute()
    assert settings.data_dir == settings.project_root / "data"
    assert settings.raw_data_dir == settings.data_dir / "raw"
    assert settings.parsed_data_dir == settings.data_dir / "parsed"
    assert settings.index_dir == settings.data_dir / "indexes"
    assert settings.model_cache_dir == settings.data_dir / "models"


def test_project_root_override_moves_relative_directories(tmp_path: Path) -> None:
    settings = Settings(project_root=tmp_path)

    assert settings.raw_data_dir == (tmp_path / "data/raw").resolve()


def test_absolute_directory_override_is_honoured(tmp_path: Path) -> None:
    external = tmp_path / "elsewhere" / "library"
    settings = Settings(raw_data_dir=external)

    assert settings.raw_data_dir == external.resolve()


def test_environment_variables_override_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEBATE_ENGINE_DEFAULT_TOP_K", "5")
    monkeypatch.setenv("DEBATE_ENGINE_SOURCE_WEIGHTS__PERSONAL", "1.5")

    settings = Settings()

    assert settings.default_top_k == 5
    assert settings.source_weights.personal == pytest.approx(1.5)


# --- 8. Source weights are available ---------------------------------------


def test_source_weights_have_the_expected_defaults() -> None:
    weights = Settings().source_weights

    assert weights.personal_masterfile == pytest.approx(1.15)
    assert weights.personal == pytest.approx(1.10)
    assert weights.past_case == pytest.approx(1.05)
    assert weights.other == pytest.approx(0.90)


def test_personal_material_outranks_collected_material() -> None:
    weights = Settings().source_weights

    assert weights.personal_masterfile > weights.personal > weights.past_case > weights.other


def test_scoring_placeholders_are_present() -> None:
    settings = Settings()

    assert settings.motion_similarity_boosts.exact_motion_match > 0
    assert settings.freshness_modifiers.current > 0
    assert 0.0 <= settings.duplicate_similarity_threshold <= 1.0


def test_structure_detection_thresholds_are_configured() -> None:
    detection = Settings().structure_detection

    assert detection.style_heading_confidence == pytest.approx(0.98)
    assert detection.minimum_section_confidence == pytest.approx(0.55)
    assert detection.max_heading_words == 12


# --- 9. Special masterfile names are configured ----------------------------


def test_special_masterfiles_are_configured() -> None:
    special = Settings().special_masterfiles

    assert "Case File Sandhu" in special
    assert "Theory File - Sandhu" in special


# --- Python version guard --------------------------------------------------


def test_minimum_python_version_is_312() -> None:
    assert MINIMUM_PYTHON_VERSION == (3, 12)


def test_version_check_passes_on_the_running_interpreter() -> None:
    assert sys.version_info >= MINIMUM_PYTHON_VERSION
    check_python_version()


def test_version_check_raises_a_readable_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "version_info", (3, 9, 6, "final", 0))

    with pytest.raises(RuntimeError, match="requires Python 3.12 or newer"):
        check_python_version()
