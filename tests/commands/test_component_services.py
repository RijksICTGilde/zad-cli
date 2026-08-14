"""`component update --service` adds; it never quietly takes something away.

The flag used to replace the whole list, on a command whose own help says "Only the fields
you specify change; all others remain as-is". Naming one service therefore unbound every
other one. A practice run hit it while unpublishing a component: the attachment coupling was
gone afterwards, and nothing had said so.

Taking a service away is `--remove-service`; setting the list exactly is
`--replace-services`. Both say out loud what they do.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx
from typer.testing import CliRunner

from zad_cli.cli import app

API = "https://api.example.com"
COMPONENTS = f"{API}/v2/projects/my-project/components"
UPDATE = f"{API}/v2/projects/my-project/components/backend"

runner = CliRunner()


@pytest.fixture(autouse=True)
def _credentials(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ZAD_API_KEY", "test-key")
    monkeypatch.setenv("ZAD_PROJECT_ID", "my-project")
    monkeypatch.setenv("ZAD_API_URL", API)
    monkeypatch.setenv("ZAD_YES", "true")


def _bound_to(*names: str) -> None:
    respx.get(COMPONENTS).mock(
        return_value=httpx.Response(
            200,
            json={
                "components": [
                    {"name": "backend", "services": list(names)},
                    {"name": "frontend", "services": ["publish-on-web"]},
                ]
            },
        )
    )


def _sent() -> dict:
    route = respx.patch(UPDATE)
    return json.loads(route.calls.last.request.content)


@respx.mock
def test_adding_a_service_keeps_the_ones_already_there():
    _bound_to("postgresql-database", "redis", "attachments")
    respx.patch(UPDATE).mock(return_value=httpx.Response(200, json={"success": True}))

    result = runner.invoke(app, ["component", "update", "backend", "--service", "minio-storage"])

    assert result.exit_code == 0, result.output
    assert _sent()["services"] == ["postgresql-database", "redis", "attachments", "minio-storage"]


@respx.mock
def test_naming_one_service_does_not_unbind_the_rest():
    """The exact shape of the loss: `--service redis` used to send `["redis"]`."""
    _bound_to("postgresql-database", "redis", "attachments")
    respx.patch(UPDATE).mock(return_value=httpx.Response(200, json={"success": True}))

    runner.invoke(app, ["component", "update", "backend", "--service", "redis"])

    assert "attachments" in _sent()["services"]


@respx.mock
def test_adding_something_already_bound_changes_nothing():
    _bound_to("redis", "attachments")
    respx.patch(UPDATE).mock(return_value=httpx.Response(200, json={"success": True}))

    runner.invoke(app, ["component", "update", "backend", "--service", "redis"])

    assert _sent()["services"] == ["redis", "attachments"]


@respx.mock
def test_removing_is_a_flag_of_its_own():
    _bound_to("postgresql-database", "redis", "attachments")
    respx.patch(UPDATE).mock(return_value=httpx.Response(200, json={"success": True}))

    runner.invoke(app, ["component", "update", "backend", "--remove-service", "redis"])

    assert _sent()["services"] == ["postgresql-database", "attachments"]


@respx.mock
def test_replace_still_exists_for_when_that_is_what_you_mean():
    _bound_to("postgresql-database", "redis", "attachments")
    respx.patch(UPDATE).mock(return_value=httpx.Response(200, json={"success": True}))

    runner.invoke(
        app,
        ["component", "update", "backend", "--replace-services", "--service", "redis"],
    )

    assert _sent()["services"] == ["redis"]


@respx.mock
def test_an_update_that_is_not_about_services_reads_nothing_and_sends_nothing():
    """No GET, and no `services` key: touching the list at all is what loses couplings."""
    listing = respx.get(COMPONENTS)
    respx.patch(UPDATE).mock(return_value=httpx.Response(200, json={"success": True}))

    runner.invoke(app, ["component", "update", "backend", "--memory-limit", "512Mi"])

    assert "services" not in _sent()
    assert not listing.called
