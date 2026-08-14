"""`component list` reads the definitions, not only the deployments.

A practice run added three components without --deployment -- the state `component add`
itself calls a valid one -- and `component list` answered "No results." while
`project describe` showed all three. The list came from the deployments endpoint, so a
component nothing referenced yet was invisible exactly in the state it was newest in.
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
DEPLOYMENTS = f"{API}/v2/projects/my-project/deployments"

runner = CliRunner()


@pytest.fixture(autouse=True)
def _credentials(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ZAD_API_KEY", "test-key")
    monkeypatch.setenv("ZAD_PROJECT_ID", "my-project")
    monkeypatch.setenv("ZAD_API_URL", API)


def _definition(name: str, **extra) -> dict:
    return {"name": name, "type": "single", "ports": {}, "services": [], **extra}


def _deployment(name: str, *references: str) -> dict:
    return {
        "name": name,
        "project": "my-project",
        "cluster": "c1",
        "namespace": f"rig-my-project-{name}",
        "status": "healthy",
        "components": [{"reference": r, "image": "img:latest"} for r in references],
    }


def _mock(*, definitions: list[dict], deployments: list[dict]) -> None:
    respx.get(COMPONENTS).mock(return_value=httpx.Response(200, json={"components": definitions}))
    respx.get(DEPLOYMENTS).mock(
        return_value=httpx.Response(200, json={"project": "my-project", "cluster": "c1", "deployments": deployments})
    )


def _names(result) -> list[str]:
    assert result.exit_code == 0, result.output
    return [row["component"] for row in json.loads(result.stdout)]


@respx.mock
def test_a_component_that_is_only_defined_shows_up():
    _mock(definitions=[_definition("web"), _definition("worker")], deployments=[])

    names = _names(runner.invoke(app, ["-o", "json", "component", "list"]))

    assert names == ["web", "worker"]


@respx.mock
def test_an_unattached_component_names_no_deployment():
    _mock(definitions=[_definition("web")], deployments=[])

    result = runner.invoke(app, ["-o", "json", "component", "list"])
    row = json.loads(result.stdout)[0]

    assert row["deployments"] == []
    assert "-" not in json.dumps(row), "json gives the domain shape; '-' is the table's rendering"


@respx.mock
def test_attachments_come_along_with_their_deployment():
    _mock(
        definitions=[_definition("web"), _definition("worker")],
        deployments=[_deployment("prod", "web")],
    )

    rows = json.loads(runner.invoke(app, ["-o", "json", "component", "list"]).stdout)

    assert {row["component"]: row["deployments"] for row in rows} == {"web": ["prod"], "worker": []}


@respx.mock
def test_the_table_keeps_the_readable_rendering():
    """Lists are data for json; the table joins them and writes "-" for none."""
    _mock(
        definitions=[_definition("web"), _definition("worker")],
        deployments=[_deployment("prod", "web")],
    )

    result = runner.invoke(app, ["component", "list"])

    assert result.exit_code == 0, result.output
    assert "prod" in result.output
    assert "-" in result.output


@respx.mock
def test_the_deployment_filter_matches_the_attachment():
    _mock(
        definitions=[_definition("web"), _definition("worker")],
        deployments=[_deployment("prod", "web")],
    )

    names = _names(runner.invoke(app, ["-o", "json", "component", "list", "-d", "prod"]))

    assert names == ["web"]


@respx.mock
def test_ports_and_services_come_from_the_definition():
    _mock(
        definitions=[_definition("web", ports={"inbound": [8080]}, services=["redis", "keycloak"])],
        deployments=[],
    )

    row = json.loads(runner.invoke(app, ["-o", "json", "component", "list"]).stdout)[0]

    assert row["ports"] == [8080]
    assert row["services"] == ["redis", "keycloak"]


@respx.mock
def test_no_components_is_still_no_results():
    _mock(definitions=[], deployments=[])

    result = runner.invoke(app, ["component", "list"])

    assert result.exit_code == 0
    assert "No results." in result.output
