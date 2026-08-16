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
    """Same two halves as `assign`: `add -c` went through the same silently-skipping field."""
    selection = respx.post(SERVICES).mock(return_value=_ok())
    web = respx.patch(f"{API}/v2/projects/my-project/components/web").mock(return_value=_ok())
    worker = respx.patch(f"{API}/v2/projects/my-project/components/worker").mock(return_value=_ok())

    result = runner.invoke(app, ["service", "add", "redis", "-c", "web", "-c", "worker"])

    assert result.exit_code == 0, result.output
    assert json.loads(selection.calls.last.request.content) == {"service": "redis"}
    assert json.loads(web.calls.last.request.content) == {"add_services": ["redis"]}
    assert json.loads(worker.calls.last.request.content) == {"add_services": ["redis"]}


@respx.mock
def test_add_without_components_still_says_a_service_was_already_there():
    """The other half of the warning rule: on a bare `add`, "already exists" is the answer
    to the question you asked."""
    respx.post(SERVICES).mock(
        return_value=httpx.Response(
            200,
            json={
                "status": "success",
                "services_skipped": ["redis"],
                "warnings": ["Service 'redis' already exists on the project"],
            },
        )
    )

    result = runner.invoke(app, ["service", "add", "redis"])

    assert result.exit_code == 0, result.output
    assert "already exists" in result.output


@respx.mock
def test_assign_binds_on_the_component_and_not_through_the_services_call():
    """The `components` field on `POST /services` is a no-op whenever the service is already
    selected for the project -- it short-circuits and still echoes `components_updated`. A
    practice run lost an authorization-wall to that: success, "components updated: frontend",
    no binding, and a public URL answering 200 with no wall in front of it. Almost everyone
    configures a service before binding it, so the broken branch is the common one.

    Hence: the selection through `POST /services`, the binding through `add_services` on the
    component, which merges server-side and cannot silently skip."""
    selection = respx.post(SERVICES).mock(return_value=_ok())
    binding = respx.patch(f"{API}/v2/projects/my-project/components/backend").mock(return_value=_ok())

    result = runner.invoke(app, ["service", "assign", "postgresql-database", "-c", "backend"])

    assert result.exit_code == 0, result.output
    assert json.loads(selection.calls.last.request.content) == {"service": "postgresql-database"}
    assert "components" not in json.loads(selection.calls.last.request.content)
    assert json.loads(binding.calls.last.request.content) == {"add_services": ["postgresql-database"]}


@respx.mock
def test_assign_binds_every_named_component():
    selection = respx.post(SERVICES).mock(return_value=_ok())
    web = respx.patch(f"{API}/v2/projects/my-project/components/web").mock(return_value=_ok())
    worker = respx.patch(f"{API}/v2/projects/my-project/components/worker").mock(return_value=_ok())

    result = runner.invoke(app, ["service", "assign", "redis", "-c", "web", "-c", "worker"])

    assert result.exit_code == 0, result.output
    assert selection.called and web.called and worker.called


@respx.mock
def test_assign_does_not_cry_wolf_about_a_service_that_was_configured_first():
    """`services_skipped` is the normal answer here: you configured the service, now you bind
    it. Surfacing "already exists on the project" would warn about the half this command
    only makes sure of, on a run that did exactly what it said."""
    respx.post(SERVICES).mock(
        return_value=httpx.Response(
            200,
            json={
                "status": "success",
                "services_added": [],
                "services_skipped": ["authorization-wall"],
                "warnings": ["Service 'authorization-wall' already exists on the project"],
            },
        )
    )
    respx.patch(f"{API}/v2/projects/my-project/components/frontend").mock(return_value=_ok())

    result = runner.invoke(app, ["service", "assign", "authorization-wall", "-c", "frontend"])

    assert result.exit_code == 0, result.output
    assert "already exists" not in result.output


@respx.mock
def test_assign_still_reports_a_warning_that_is_about_the_selection():
    """The filter is narrow on purpose: only the skip is expected."""
    respx.post(SERVICES).mock(
        return_value=httpx.Response(
            200,
            json={"status": "success", "services_added": ["redis"], "warnings": ["Quota nearly reached"]},
        )
    )
    respx.patch(f"{API}/v2/projects/my-project/components/web").mock(return_value=_ok())

    result = runner.invoke(app, ["service", "assign", "redis", "-c", "web"])

    assert result.exit_code == 0, result.output
    assert "Quota nearly reached" in result.output


@respx.mock
def test_assign_dry_run_shows_both_calls_and_sends_neither():
    selection = respx.post(SERVICES).mock(return_value=_ok())
    binding = respx.patch(f"{API}/v2/projects/my-project/components/web").mock(return_value=_ok())

    result = runner.invoke(app, ["-o", "json", "service", "assign", "redis", "-c", "web", "--dry-run"])

    assert result.exit_code == 0, result.output
    assert not selection.called and not binding.called
    calls = json.loads(result.stdout)
    assert [c["method"] for c in calls] == ["POST", "PATCH"]
    assert calls[1]["endpoint"].endswith("/components/web")


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
