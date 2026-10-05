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

# Before anything imports zad_cli, because Rich decides per Console whether it may style and
# the CLI builds those at import time. A fixture is too late: by then the consoles exist and
# carry the answer the environment gave.
#
# The one that matters is `GITHUB_ACTIONS`. Rich treats it as a terminal that can style, so
# every assertion reading output for an option name failed there and nowhere else:
# `--mount-path` arrives as `\x1b[1m-\x1b[0m\x1b[1m-mount\x1b[0m\x1b[1m-path\x1b[0m`, and
# the styling sits *inside* the word. Thirteen tests hung on it. `NO_COLOR`, `TERM=dumb` and
# `TTY_COMPATIBLE=0` were all measured against it and none of them win -- that detection
# overrides them -- so the variable itself goes, which is true to what a test run is: not a
# terminal, whoever started it.
os.environ.pop("GITHUB_ACTIONS", None)
os.environ["NO_COLOR"] = "1"
os.environ.pop("FORCE_COLOR", None)

import pytest  # noqa: E402

from zad_cli.envfile import ENV_VARS  # noqa: E402

# Everything the CLI reads from the environment. Cleared per test so the developer's own
# shell cannot reach in.
# ZAD_VERSION_CHECK_INTERVAL is named here rather than in ENV_VARS, like the other
# variables with no `config` key: an exported one would decide whether a test fetches.
_ZAD_VARS = (*ENV_VARS.values(), "ZAD_SSO_ISSUER", "ZAD_SSO_CLIENT_ID", "ZAD_VERSION_CHECK_INTERVAL")


@pytest.fixture(autouse=True)
def _isolate_environment(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch):
    from zad_cli import update
    from zad_cli.api import registry

    home = tmp_path_factory.mktemp("zad-home")
    # The .env lives in the working directory, so this is what isolates the credentials
    # and the settings in one move.
    monkeypatch.chdir(tmp_path_factory.mktemp("zad-cwd"))
    monkeypatch.setattr(registry, "CACHE_DIR", home / "cache")
    # The release check keeps its stamps next to the catalog cache, and `Path.home()` is
    # not redirected here, so this is what keeps a test run out of the developer's own
    # cache -- and out of a state file that would decide whether the next test fetches.
    monkeypatch.setattr(update, "CACHE_DIR", home / "cache")
    monkeypatch.setattr(update, "_pending", None)
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
    # And no test asks GitHub whether there is a newer zadctl. The suppression rules
    # already cover a test run twice over (not a terminal, ZAD_CATALOG_OFFLINE set), but
    # the one thing worth being certain of is that the suite cannot reach github.com.
    monkeypatch.setenv("ZAD_VERSION_CHECK", "off")
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
