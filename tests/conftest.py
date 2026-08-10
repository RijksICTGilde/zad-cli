"""Shared test isolation.

Two things must never leak into a test run: the developer's own `.env`, and a real API.
Both are switched off here for every test, so an individual test cannot forget.

Since everything the CLI writes goes to the `.env` in the working directory, isolation is
a temporary working directory. That also covers the variables the developer has exported:
they are cleared, so a shell that is pointed at a sandbox does not decide what the suite
tests.
"""

from __future__ import annotations

import pytest

from zad_cli.envfile import ENV_VARS

# Everything the CLI reads from the environment. Cleared per test so the developer's own
# shell cannot reach in.
_ZAD_VARS = (*ENV_VARS.values(), "ZAD_SSO_ISSUER", "ZAD_SSO_CLIENT_ID")


@pytest.fixture(autouse=True)
def _isolate_environment(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch):
    from zad_cli.api import registry

    home = tmp_path_factory.mktemp("zad-home")
    # The .env lives in the working directory, so this is what isolates the credentials
    # and the settings in one move.
    monkeypatch.chdir(tmp_path_factory.mktemp("zad-cwd"))
    monkeypatch.setattr(registry, "CACHE_DIR", home / "cache")
    for var in _ZAD_VARS:
        monkeypatch.delenv(var, raising=False)
    # The service catalog falls back to the snapshot shipped with the CLI, so no test
    # reaches out for it. Tests that exercise fetching clear this themselves.
    monkeypatch.setenv("ZAD_CATALOG_OFFLINE", "1")
    yield
