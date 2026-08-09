"""Shared test isolation.

Two things must never leak into a test run: the developer's own credentials file, and a
real API. Both are switched off here for every test, so an individual test cannot forget.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolate_environment(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch):
    from zad_cli import credentials
    from zad_cli.api import registry

    home: Path = tmp_path_factory.mktemp("zad-home")
    monkeypatch.setattr(credentials, "CONFIG_DIR", home / "config")
    monkeypatch.setattr(credentials, "CREDENTIALS_PATH", home / "config" / "credentials.toml")
    monkeypatch.setattr(registry, "CACHE_DIR", home / "cache")
    # The service catalog falls back to the snapshot shipped with the CLI, so no test
    # reaches out for it. Tests that exercise fetching clear this themselves.
    monkeypatch.setenv("ZAD_CATALOG_OFFLINE", "1")
    monkeypatch.delenv("ZAD_SSO_TOKEN", raising=False)
    yield
