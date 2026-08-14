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
    # "e.g." because the field has no enum: the list is what the portal offers, not a rule.
    assert rows["sleep-after-deploy"]["values"] == "e.g. 5m | 48h | 168h"
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


@respx.mock
def test_a_menu_is_not_presented_as_the_closed_set():
    """The API is explicit: `enum` means those values and nothing else, `x-choices` is what
    the portal offers. `sleep-after-deploy` takes any duration, `90m` included, so printing
    its menu as the accepted set is how a reader concludes `90m` is invalid."""
    respx.get(SPEC_URL).mock(return_value=httpx.Response(200, json=_spec_with_choices()))
    _mock_catalog()

    result = runner.invoke(app, ["-o", "json", "service", "describe", "sleep-mode"])
    rows = {r["option"]: r for r in json.loads(result.stdout)["settings"]["project"][0]["fields"]}
    # x-choices without an enum: a menu, and it says so.
    assert rows["sleep-after-deploy"]["values"] == "e.g. 5m | 48h | 168h"
    # enum: those values and nothing else, so no hedge.
    assert rows["wake-mode"]["values"] == "auto | confirm | manual"


@respx.mock
def test_a_cache_older_than_the_ttl_is_refetched():
    """An hour, not a day: a default changed upstream on the afternoon this was written and
    `--help` kept saying the old one."""
    route = respx.get(SPEC_URL).mock(return_value=httpx.Response(200, json=_spec_with_choices()))
    spec.load_live_spec(API)
    assert route.call_count == 1

    path = spec.live_cache_path(API)
    cached = json.loads(path.read_text())
    cached["fetched_at"] = cached["fetched_at"] - (spec.LIVE_TTL_SECONDS + 60)
    path.write_text(json.dumps(cached))
    spec.load_live_spec.cache_clear()

    spec.load_live_spec(API)
    assert route.call_count == 2


def _spec_with_source(endpoint: str = "GET /api/v2/projects/{project_name}/components") -> dict:
    """The vendored spec, plus an `x-choices-source` like the live one carries."""
    document = copy.deepcopy(spec.load_spec())
    field = document["components"]["schemas"]["SleepModeConfig"]["properties"]["waker-component"]
    field["x-choices-source"] = {
        "description": "De componenten van dit project.",
        "endpoint": endpoint,
        "path": "components[].name",
    }
    return document


def _components() -> None:
    respx.get(f"{API}/v2/projects/my-project/components").mock(
        return_value=httpx.Response(200, json={"components": [{"name": "web"}, {"name": "worker"}]})
    )


@respx.mock
def test_a_project_dependent_field_shows_this_project_s_values(monkeypatch: pytest.MonkeyPatch):
    """`waker-component` is not an enum and cannot be: "An enumeration here would be one
    project's snapshot and wrong for every other." The API names the endpoint that has the
    real list, so `describe` asks it."""
    monkeypatch.setenv("ZAD_PROJECT_ID", "my-project")
    monkeypatch.setenv("ZAD_API_KEY", "test-key")
    respx.get(SPEC_URL).mock(return_value=httpx.Response(200, json=_spec_with_source()))
    _mock_catalog()
    _components()

    result = runner.invoke(app, ["-o", "json", "service", "describe", "sleep-mode"])
    assert result.exit_code == 0, result.output
    row = {r["option"]: r for r in json.loads(result.stdout)["settings"]["project"][0]["fields"]}["waker-component"]
    assert row["values"] == "web | worker"
    # The source travels too, so an agent can call the endpoint itself rather than trust a
    # list this CLI happened to fetch a minute ago.
    assert row["source"]["endpoint"] == "GET /api/v2/projects/{project_name}/components"


@respx.mock
def test_without_a_project_the_source_is_named_instead(monkeypatch: pytest.MonkeyPatch):
    """`describe` answers without credentials, and must keep doing so."""
    monkeypatch.delenv("ZAD_PROJECT_ID", raising=False)
    monkeypatch.delenv("ZAD_API_KEY", raising=False)
    respx.get(SPEC_URL).mock(return_value=httpx.Response(200, json=_spec_with_source()))
    _mock_catalog()

    result = runner.invoke(app, ["-o", "json", "service", "describe", "sleep-mode"])
    assert result.exit_code == 0, result.output
    row = {r["option"]: r for r in json.loads(result.stdout)["settings"]["project"][0]["fields"]}["waker-component"]
    assert row["values"] == "<De componenten van dit project>"


@respx.mock
def test_a_placeholder_this_run_cannot_fill_is_not_guessed(monkeypatch: pytest.MonkeyPatch):
    """`{peer_project}` needs to know which peer is meant. Filling it with this project
    would list the wrong components with no sign that they are the wrong ones."""
    monkeypatch.setenv("ZAD_PROJECT_ID", "my-project")
    monkeypatch.setenv("ZAD_API_KEY", "test-key")
    respx.get(SPEC_URL).mock(
        return_value=httpx.Response(200, json=_spec_with_source("GET /api/v2/projects/{peer_project}/components"))
    )
    _mock_catalog()

    result = runner.invoke(app, ["-o", "json", "service", "describe", "sleep-mode"])
    row = {r["option"]: r for r in json.loads(result.stdout)["settings"]["project"][0]["fields"]}["waker-component"]
    assert row["values"] == "<De componenten van dit project>"


@respx.mock
def test_an_endpoint_that_fails_costs_nothing(monkeypatch: pytest.MonkeyPatch):
    """A 500 on a side quest must not take the description down with it."""
    monkeypatch.setenv("ZAD_PROJECT_ID", "my-project")
    monkeypatch.setenv("ZAD_API_KEY", "test-key")
    respx.get(SPEC_URL).mock(return_value=httpx.Response(200, json=_spec_with_source()))
    _mock_catalog()
    respx.get(f"{API}/v2/projects/my-project/components").mock(return_value=httpx.Response(500))

    result = runner.invoke(app, ["-o", "json", "service", "describe", "sleep-mode"])
    assert result.exit_code == 0, result.output
    row = {r["option"]: r for r in json.loads(result.stdout)["settings"]["project"][0]["fields"]}["waker-component"]
    assert row["values"] == "<De componenten van dit project>"


@respx.mock
def test_values_read_from_a_project_say_which_project(monkeypatch: pytest.MonkeyPatch):
    """The cell reads exactly like a platform rule while it is one project's answer at one
    moment, and a transcript keeps neither the project nor the moment."""
    monkeypatch.setenv("ZAD_PROJECT_ID", "my-project")
    monkeypatch.setenv("ZAD_API_KEY", "test-key")
    monkeypatch.setenv("COLUMNS", "300")
    respx.get(SPEC_URL).mock(return_value=httpx.Response(200, json=_spec_with_source()))
    _mock_catalog()
    _components()

    output = runner.invoke(app, ["service", "describe", "sleep-mode"]).output
    flat = " ".join(output.split())
    assert "web | worker +" in flat
    assert "+ from project 'my-project'" in flat
    assert "differ per project" in flat


@respx.mock
def test_the_help_screen_names_the_source_when_there_is_no_project(monkeypatch: pytest.MonkeyPatch):
    """Without a project there is nothing to read, so it says what the option takes.
    Without this note, `<the components of this project>` looks like a gap where it is an
    answer."""
    monkeypatch.delenv("ZAD_PROJECT_ID", raising=False)
    monkeypatch.delenv("ZAD_API_KEY", raising=False)
    monkeypatch.setenv("COLUMNS", "300")
    respx.get(SPEC_URL).mock(return_value=httpx.Response(200, json=_spec_with_source()))
    _mock_catalog()

    output = runner.invoke(app, ["service", "sleep-mode", "--help"]).output
    flat = " ".join(output.split())
    assert "come from your project itself" in flat
    assert "zadctl service describe sleep-mode" in flat


@respx.mock
def test_the_help_screen_reads_the_project_when_there_is_one(monkeypatch: pytest.MonkeyPatch):
    """Telling someone who has a project selected to select a project is the CLI not
    knowing what it just did. Help fetches the spec already; this is the same trip."""
    monkeypatch.setenv("ZAD_PROJECT_ID", "my-project")
    monkeypatch.setenv("ZAD_API_KEY", "test-key")
    monkeypatch.setenv("COLUMNS", "300")
    respx.get(SPEC_URL).mock(return_value=httpx.Response(200, json=_spec_with_source()))
    _mock_catalog()
    _components()

    output = runner.invoke(app, ["service", "sleep-mode", "--help"]).output
    flat = " ".join(output.split())
    assert "web | worker +" in flat
    assert "+ from project 'my-project'" in flat
    assert "Select a project" not in flat


@respx.mock
def test_resolving_the_command_does_not_call_the_api(monkeypatch: pytest.MonkeyPatch):
    """The help text is built when it is asked for. Building it at construction would make
    every `zadctl service sleep-mode ...` fetch a components list it then never shows."""
    monkeypatch.setenv("ZAD_PROJECT_ID", "my-project")
    monkeypatch.setenv("ZAD_API_KEY", "test-key")
    respx.get(SPEC_URL).mock(return_value=httpx.Response(200, json=_spec_with_source()))
    _mock_catalog()
    components = respx.get(f"{API}/v2/projects/my-project/components").mock(
        return_value=httpx.Response(200, json={"components": [{"name": "web"}]})
    )

    runner.invoke(app, ["-o", "json", "service", "sleep-mode"])
    # Once, for the description it printed -- not twice, for a help screen nobody asked for.
    assert components.call_count == 1


@respx.mock
def test_the_examples_the_api_offers_are_shown():
    """`match` is the field nobody can guess -- "which deployments are in scope", with a
    syntax of its own -- and the API answers it with `pr-*`, `*-preview`, `acceptatie` on
    the *item* of the array. Reading only the field itself prints `<text>` next to a
    question the platform has already answered."""
    document = copy.deepcopy(spec.load_spec())
    document["components"]["schemas"]["SleepModeConfig"]["properties"]["match"]["items"]["examples"] = [
        "pr-*",
        "*-preview",
        "acceptatie",
    ]
    respx.get(SPEC_URL).mock(return_value=httpx.Response(200, json=document))
    _mock_catalog()

    result = runner.invoke(app, ["-o", "json", "service", "describe", "sleep-mode"])
    block = json.loads(result.stdout)["settings"]["project"][0]
    rows = {r["option"]: r for r in block["fields"]}
    # "e.g." because they are illustrations: the description says any name, prefix or
    # suffix pattern is accepted.
    assert rows["match[0]"]["values"] == "e.g. pr-* | *-preview | acceptatie"
    assert "--set 'match[0]=pr-*'" in block["example_multiple"]


@respx.mock
def test_completing_a_value_asks_the_endpoint_the_api_named(monkeypatch: pytest.MonkeyPatch):
    """`--set waker-component=<TAB>` is what `x-choices-source` is for: the API says which
    endpoint holds the list, so the shell can offer this project's components."""
    from zad_cli import helpers

    monkeypatch.setenv("ZAD_PROJECT_ID", "my-project")
    monkeypatch.setenv("ZAD_API_KEY", "test-key")
    helpers.completion_settings.cache_clear()
    respx.get(SPEC_URL).mock(return_value=httpx.Response(200, json=_spec_with_source()))
    _mock_catalog()
    _components()

    # Through the shell's own path: a context this test builds itself would have the
    # parameters filled, which is exactly what a real completion does not have.
    from tests.test_completion import complete

    offered = complete(["service", "config", "set", "sleep-mode", "--set"], "waker-component=")
    assert offered == ["waker-component=web", "waker-component=worker"]
    helpers.completion_settings.cache_clear()


@respx.mock
def test_set_says_which_settings_it_would_drop(monkeypatch: pytest.MonkeyPatch):
    """`set` writes the document whole, and never said so. A practice run set
    `restrict-access.enabled` on keycloak and lost the `template=sso-only` it had set an
    hour earlier, with nothing on screen to say so."""
    monkeypatch.setenv("ZAD_PROJECT_ID", "my-project")
    monkeypatch.setenv("ZAD_API_KEY", "test-key")
    monkeypatch.setenv("COLUMNS", "300")
    respx.get(SPEC_URL).mock(return_value=httpx.Response(200, json=_spec_with_choices()))
    _mock_catalog()
    respx.get(f"{API}/v2/projects/my-project/services/keycloak/config").mock(
        return_value=httpx.Response(
            200,
            json={
                "service": "keycloak",
                "configurations": [{"target": "project", "config": {"template": "sso-only", "realm-roles": []}}],
            },
        )
    )

    result = runner.invoke(
        app, ["service", "config", "set", "keycloak", "--set", "restrict-access.enabled=true", "--dry-run"]
    )
    assert result.exit_code == 0, result.output
    flat = " ".join(result.output.split())
    assert "template would be removed" in flat
    # `realm-roles` is empty, so nothing is lost by leaving it out and it is not named.
    assert "realm-roles" not in flat


@respx.mock
def test_a_first_write_says_nothing(monkeypatch: pytest.MonkeyPatch):
    """Nothing to lose, nothing to warn about: a warning that fires every time is one
    people learn to scroll past."""
    monkeypatch.setenv("ZAD_PROJECT_ID", "my-project")
    monkeypatch.setenv("ZAD_API_KEY", "test-key")
    respx.get(SPEC_URL).mock(return_value=httpx.Response(200, json=_spec_with_choices()))
    _mock_catalog()
    respx.get(f"{API}/v2/projects/my-project/services/keycloak/config").mock(
        return_value=httpx.Response(200, json={"service": "keycloak", "configurations": []})
    )

    result = runner.invoke(app, ["service", "config", "set", "keycloak", "--set", "template=sso-only", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "would be removed" not in result.output
