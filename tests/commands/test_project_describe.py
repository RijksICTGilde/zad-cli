"""`zadctl project describe`: a project as it stands, from the read endpoints.

The response shape is the one in RIG-Cluster PR #60. Two of its distinctions are the point
of most of these tests: a withheld secret is not a value, and `env_var_names: null` is not
an empty list.
"""

from __future__ import annotations

import json
from datetime import UTC

import httpx
import pytest
import respx
from typer.testing import CliRunner

from zad_cli.cli import app

runner = CliRunner()
API = "https://api.example.com"
KEY = "Xk3mQ9vP2rT7wY1bN5cL8hJ4gF6dS0aZ"

DETAIL = {
    "project": {
        "name": "mijn-project",
        "display_name": "Mijn Project",
        "description": "Aangemaakt via de portal",
        "clusters": ["odcn-production"],
    },
    "source": "project-file",
    "cluster": "odcn-production",
    "pending_rollout": {"project": "mijn-project", "count": 0, "since": None, "task_types": []},
    "services": [
        {
            "name": "publish-on-web",
            "usages": [
                {"target": "project", "component": None, "deployment": None, "config": None},
                {"target": "component", "component": "backend", "deployment": None, "config": {"tls": "standard"}},
            ],
        },
        {
            "name": "keycloak",
            "usages": [{"target": "project", "component": None, "deployment": None, "config": {"secret": "***"}}],
        },
    ],
    "components": [
        {
            "name": "backend",
            "type": "single",
            "ports": {"inbound": [8000], "outbound": [443]},
            "services": ["publish-on-web", "keycloak"],
            "env_var_names": ["API_TOKEN", "DATABASE_PASSWORD"],
            "aliases": {"POSTGRES_HOST": "$DATABASE_SERVER_HOST"},
            "attachments": [{"reference": "server-cert", "provide_as": "file", "path": "/etc/ssl/cert.pem"}],
        },
        {"name": "worker", "type": "single", "ports": {"inbound": []}, "services": [], "env_var_names": None},
    ],
    "deployments": [
        {
            "name": "production",
            "components": [{"reference": "backend", "image": "ghcr.io/org/backend:1.0"}],
            "status": "Healthy",
            "errors": [],
        }
    ],
}


@pytest.fixture(autouse=True)
def _environment(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ZAD_API_URL", API)
    monkeypatch.setenv("ZAD_API_KEY", KEY)
    monkeypatch.setenv("ZAD_PROJECT_ID", "mijn-project")
    yield


def run(*args: str):
    return runner.invoke(app, list(args))


def _mock(payload: dict = DETAIL, path: str = "") -> None:
    respx.get(f"{API}/v2/projects/mijn-project{path}").mock(return_value=httpx.Response(200, json=payload))


@respx.mock
def test_json_passes_the_response_through():
    """An agent gets the API's own shape, not a rearrangement of it."""
    _mock()
    result = run("-o", "json", "project", "describe")
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == DETAIL


@respx.mock
def test_the_table_shows_services_components_and_deployments():
    _mock()
    result = run("project", "describe")
    assert result.exit_code == 0, result.output
    flat = " ".join(result.output.split())
    assert "publish-on-web" in flat
    assert "backend" in flat
    assert "production" in flat


@respx.mock
def test_a_withheld_secret_is_not_rendered_as_a_value():
    """`***` means the API kept it back. Printing it says the setting is three asterisks."""
    _mock()
    flat = " ".join(run("project", "describe").output.split())
    assert "set, not shown" in flat
    assert "secret=***" not in flat


@respx.mock
def test_null_env_vars_are_not_shown_as_none():
    """The API is explicit: null means it could not read them, [] means there are none."""
    _mock()
    flat = " ".join(run("project", "describe").output.split())
    assert "(unreadable)" in flat


@respx.mock
def test_pending_changes_are_said_before_everything_else():
    """What follows describes the project file; this says how far the cluster is behind."""
    from datetime import datetime, timedelta

    since = (datetime.now(UTC) - timedelta(hours=3)).isoformat()
    _mock({**DETAIL, "pending_rollout": {"count": 2, "since": since, "task_types": ["add_component"]}})
    output = run("project", "describe").output
    flat = " ".join(output.split())
    assert "2 change(s) saved but not rolled out" in flat
    assert "3 hours ago" in flat
    assert output.index("not rolled out") < output.index("Services in use")


@respx.mock
def test_a_project_in_sync_says_nothing_about_rolling_out():
    _mock()
    assert "not rolled out" not in run("project", "describe").output


@respx.mock
def test_part_asks_the_api_for_only_that_piece():
    """Not a filter on the whole: the API has an endpoint per part, so use it."""
    route = respx.get(f"{API}/v2/projects/mijn-project/services").mock(
        return_value=httpx.Response(200, json={"project": "mijn-project", "services": DETAIL["services"]})
    )
    whole = respx.get(f"{API}/v2/projects/mijn-project")

    result = run("project", "describe", "--part", "services")

    assert result.exit_code == 0, result.output
    assert route.called
    assert not whole.called


def test_an_unknown_part_names_the_valid_ones():
    result = run("project", "describe", "--part", "bogus")
    assert result.exit_code != 0
    flat = " ".join(result.output.replace("│", " ").split())
    assert "Unknown part 'bogus'" in flat
    assert "services, components, deployments" in flat


def test_describe_lists_the_urls_per_deployment_and_component(capsys):
    """The API computes them and hands them over; leaving them out sent the reader to a
    second command for the question they most often have here: where is it, then?"""
    from zad_cli.commands.project import _render_description
    from zad_cli.output.formatter import OutputFormatter

    _render_description(
        OutputFormatter("table"),
        "p",
        {
            "deployments": [
                {
                    "name": "productie",
                    "components": [{"reference": "web"}, {"reference": "api"}],
                    "status": "Healthy",
                    "errors": [],
                    "urls": {
                        "web": "https://web-productie.example.dev",
                        "api": "https://api-productie.example.dev",
                    },
                }
            ]
        },
    )

    out = capsys.readouterr().out
    assert "https://web-productie.example.dev" in out
    assert "https://api-productie.example.dev" in out
    # Both components of the same deployment, each on its own line under its name.
    assert out.count("productie") >= 3


def test_a_deployment_without_urls_renders_no_url_block(capsys):
    """A deployment that was never rolled out has none, and an empty table saying so is
    noise rather than an answer."""
    from zad_cli.commands.project import _render_description
    from zad_cli.output.formatter import OutputFormatter

    _render_description(
        OutputFormatter("table"),
        "p",
        {"deployments": [{"name": "productie", "components": [], "status": "Missing", "errors": [], "urls": {}}]},
    )

    assert "URLs" not in capsys.readouterr().out
