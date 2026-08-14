"""Binding a service, entered from the service instead of from the component.

`component add --service x` was the only way in, which reads well when you are setting a
component up and badly when you are wiring a database. The platform's own refusal talks
about services -- "Services that must be enabled at project level first: ['keycloak']" --
and there was no command spelled the way that sentence is.

`add` selects the service for the project. `assign` binds it to components. `unassign` takes
that binding away again; `delete` is not the word for it, because `service delete` meant
removing the service from the project and its endpoint was withdrawn.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx
from typer.testing import CliRunner

from zad_cli.cli import app

API = "https://api.example.com"
SERVICES = f"{API}/v2/projects/my-project/services"

runner = CliRunner()


@pytest.fixture(autouse=True)
def _credentials(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ZAD_API_KEY", "test-key")
    monkeypatch.setenv("ZAD_PROJECT_ID", "my-project")
    monkeypatch.setenv("ZAD_API_URL", API)
    monkeypatch.setenv("ZAD_YES", "true")


def _ok():
    return httpx.Response(200, json={"success": True})


@respx.mock
def test_add_selects_the_service_and_binds_nothing():
    """The step the platform means by "must be enabled at project level first"."""
    route = respx.post(SERVICES).mock(return_value=_ok())

    result = runner.invoke(app, ["service", "add", "keycloak"])

    assert result.exit_code == 0, result.output
    assert json.loads(route.calls.last.request.content) == {"service": "keycloak"}


@respx.mock
def test_add_can_bind_in_the_same_call():
    route = respx.post(SERVICES).mock(return_value=_ok())

    runner.invoke(app, ["service", "add", "redis", "-c", "web", "-c", "worker"])

    assert json.loads(route.calls.last.request.content) == {
        "service": "redis",
        "components": ["web", "worker"],
    }


@respx.mock
def test_assign_names_the_components_it_binds_to():
    route = respx.post(SERVICES).mock(return_value=_ok())

    result = runner.invoke(app, ["service", "assign", "postgresql-database", "-c", "backend"])

    assert result.exit_code == 0, result.output
    assert json.loads(route.calls.last.request.content) == {
        "service": "postgresql-database",
        "components": ["backend"],
    }


@respx.mock
def test_unassign_removes_only_the_named_service_from_the_named_component():
    route = respx.patch(f"{API}/v2/projects/my-project/components/worker").mock(return_value=_ok())

    result = runner.invoke(app, ["service", "unassign", "redis", "-c", "worker"])

    assert result.exit_code == 0, result.output
    body = json.loads(route.calls.last.request.content)
    assert body == {"remove_services": ["redis"]}
    assert "services" not in body, "the whole list is what loses the config behind it"


@respx.mock
def test_unassign_does_one_component_at_a_time():
    """The API takes the removal on the component, so two components are two calls."""
    web = respx.patch(f"{API}/v2/projects/my-project/components/web").mock(return_value=_ok())
    worker = respx.patch(f"{API}/v2/projects/my-project/components/worker").mock(return_value=_ok())

    runner.invoke(app, ["service", "unassign", "redis", "-c", "web", "-c", "worker"])

    assert web.called and worker.called


@respx.mock
def test_a_service_the_catalog_does_not_know_is_refused_before_anything_is_sent():
    route = respx.post(SERVICES).mock(return_value=_ok())

    result = runner.invoke(app, ["service", "assign", "postgress", "-c", "web"])

    assert result.exit_code != 0
    assert not route.called


@respx.mock
def test_unassign_asks_first_because_it_takes_something_away(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("ZAD_YES", raising=False)
    route = respx.patch(f"{API}/v2/projects/my-project/components/worker").mock(return_value=_ok())

    # Empty stdin: a prompt with nothing to read aborts, which is what proves it prompted.
    result = runner.invoke(app, ["service", "unassign", "redis", "-c", "worker"], input="")

    assert result.exit_code != 0
    assert not route.called
