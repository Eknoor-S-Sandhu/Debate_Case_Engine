"""Keep developer credentials and local configuration out of automated tests."""

import os

import pytest

from debate_engine.config import Settings, get_settings


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch):
    for key in os.environ:
        if key.startswith("DEBATE_ENGINE_"):
            monkeypatch.delenv(key)
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
