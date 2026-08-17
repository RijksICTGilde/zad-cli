"""Shared test isolation.

Two things must never leak into a test run: the developer's own `.env`, and a real API.
Both are switched off here for every test, so an individual test cannot forget.

Since everything the CLI writes goes to the `.env` in the working directory, isolation is
a temporary working directory. That also covers the variables the developer has exported:
they are cleared, so a shell that is pointed at a sandbox does not decide what the suite
tests. For the same reason the shell's proxy variables are cleared: respx's pass-through
honours them when it forwards the loopback callback, and a proxy that cannot reach
127.0.0.1 turns that test into a five-minute wait for a connection that never arrives.
"""

from __future__ import annotations

import os

# Before anything imports zad_cli, because Rich decides per Console whether it may colour
# and the CLI builds those at import time. A fixture is too late: by the time it runs, the
# consoles exist and carry the answer the environment gave. Set here so a test reads the
# same string everywhere -- CI has colour on, a developer's pytest run has it off, and the
# suite passed locally while failing there because a highlighted `--mount-path` is not the
# string `--mount-path`.
os.environ["NO_COLOR"] = "1"
os.environ.pop("FORCE_COLOR", None)

import pytest  # noqa: E402

from zad_cli.envfile import ENV_VARS  # noqa: E402

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
    for var in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "NO_PROXY",
        "no_proxy",
    ):
        monkeypatch.delenv(var, raising=False)
    # The service catalog falls back to the snapshot shipped with the CLI, so no test
    # reaches out for it. Tests that exercise fetching clear this themselves.
    monkeypatch.setenv("ZAD_CATALOG_OFFLINE", "1")
    # No colour, because a coloured message is a different string. Rich highlights
    # option-like tokens, and it does that *inside* the word: `--mount-path` comes out as
    # `\x1b[1;36m-\x1b[0m\x1b[1;36m-mount\x1b[0m...`, so an assertion looking for the option
    # by name stops matching. Locally there is no terminal and no colour, in CI there is, so
    # the suite passed here and failed there -- which is the worst place to find out. Pinned
    # rather than left to the environment: a test that reads output should get the same
    # output everywhere.
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    yield
