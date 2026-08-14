"""The spec the CLI reads is the one the API publishes, where it can be reached.

The vendored copy is a snapshot of the day it was fetched, and what it lacks is exactly
what a reader wants: the platform annotated a dozen fields with `x-choices` -- the values
it accepts, with a label per value -- after this CLI's spec was taken. `describe` answering
from that snapshot is a command whose whole job is "what does this platform offer" going
stale between releases.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import httpx
import pytest
import respx
from typer.testing import CliRunner

from zad_cli.api import spec
from zad_cli.cli import app

API = "https://api.example.com/api"
SPEC_URL = "https://api.example.com/openapi.json"
runner = CliRunner()


@pytest.fixture(autouse=True)
def _fetching_allowed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """These tests exercise fetching, so they opt out of the global offline default."""
    monkeypatch.setattr(spec, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.delenv("ZAD_CATALOG_OFFLINE", raising=False)
    monkeypatch.setenv("ZAD_API_URL", API)
    spec.load_live_spec.cache_clear()
    yield
    spec.load_live_spec.cache_clear()


def _mock_catalog() -> None:
    """The registry too: one flag means offline, so a test that fetches fetches both."""
    from zad_cli.api import registry

    payload = json.loads(registry.SNAPSHOT_PATH.read_text())
    respx.get(f"{API}/v2/services").mock(return_value=httpx.Response(200, json=payload))
    # `describe` also asks for the one service in detail; a 404 there is a documented
    # fallback to the catalog entry, which is all these tests need.
    respx.get(url__regex=rf"{API}/v2/services/.+").mock(return_value=httpx.Response(404))


def _spec_with_choices() -> dict:
    """The vendored spec, plus the annotation the live one has and it does not."""
    document = copy.deepcopy(spec.load_spec())
    field = document["components"]["schemas"]["SleepModeConfig"]["properties"]["sleep-after-deploy"]
    field["x-choices"] = [
        {"const": "5m", "title": "5 minuten (alleen sandbox, voor tests)"},
        {"const": "48h", "title": "2 dagen"},
        {"const": "168h", "title": "7 dagen"},
    ]
    return document


def test_the_spec_url_sits_next_to_the_api_not_under_it():
    assert spec.live_url("https://zad.example.dev/api") == "https://zad.example.dev/openapi.json"
    assert spec.live_url("https://zad.example.dev/api/") == "https://zad.example.dev/openapi.json"
    assert spec.live_url("https://zad.example.dev") == "https://zad.example.dev/openapi.json"


@respx.mock
def test_describe_shows_the_values_the_live_api_states():
    """`sleep-after-deploy` is a plain string in the vendored spec, so it could only be
    described as `<text>`. The platform now states its eight durations."""
    respx.get(SPEC_URL).mock(return_value=httpx.Response(200, json=_spec_with_choices()))
    _mock_catalog()

    result = runner.invoke(app, ["-o", "json", "service", "describe", "sleep-mode"])
    assert result.exit_code == 0, result.output
    rows = {r["option"]: r for r in json.loads(result.stdout)["settings"]["project"][0]["fields"]}
    assert rows["sleep-after-deploy"]["values"] == "5m | 48h | 168h"
    # The label is what the platform calls the value; json has no width to be short for.
    assert rows["sleep-after-deploy"]["choices"][0] == {
        "value": "5m",
        "label": "5 minuten (alleen sandbox, voor tests)",
    }


@respx.mock
def test_the_spec_is_fetched_once_and_then_cached():
    route = respx.get(SPEC_URL).mock(return_value=httpx.Response(200, json=_spec_with_choices()))

    first = spec.load_live_spec(API)
    spec.load_live_spec.cache_clear()  # a fresh process, same cache directory
    second = spec.load_live_spec(API)

    assert route.call_count == 1
    assert first == second


@respx.mock
def test_an_unreachable_api_falls_back_to_the_vendored_spec():
    """`describe` is the first command anyone runs and has to keep working on a train."""
    respx.get(SPEC_URL).mock(return_value=httpx.Response(503))
    _mock_catalog()

    result = runner.invoke(app, ["-o", "json", "service", "describe", "sleep-mode"])
    assert result.exit_code == 0, result.output
    rows = {r["option"]: r for r in json.loads(result.stdout)["settings"]["project"][0]["fields"]}
    # No x-choices in the bundled copy, so it says what it can and nothing it cannot.
    assert rows["sleep-after-deploy"]["values"] == "<text>"
    assert "choices" not in rows["sleep-after-deploy"]


@respx.mock
def test_a_spec_that_is_not_a_spec_is_refused():
    """A login page answering 200 at that URL must not become the CLI's map of the API."""
    respx.get(SPEC_URL).mock(return_value=httpx.Response(200, json={"detail": "Not Found"}))
    assert spec.load_live_spec(API) is None


def test_offline_never_reaches_out(monkeypatch: pytest.MonkeyPatch):
    """The flag the test suite itself relies on: set, and nothing touches the network."""
    monkeypatch.setenv("ZAD_CATALOG_OFFLINE", "1")
    spec.load_live_spec.cache_clear()
    with respx.mock:
        route = respx.get(SPEC_URL).mock(return_value=httpx.Response(200, json=_spec_with_choices()))
        assert spec.load_live_spec(API) is None
        assert route.call_count == 0
