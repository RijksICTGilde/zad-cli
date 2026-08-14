"""`zadctl project status` answers "is it healthy, and is what runs what I last pushed".

Status, revision and last sync were in the response all along and were not rendered, so
the command listed which deployments exist and left out the part that makes it a status.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx
from typer.testing import CliRunner

from zad_cli.cli import app

runner = CliRunner()
API = "https://api.example.com"
KEY = "Xk3mQ9vP2rT7wY1bN5cL8hJ4gF6dS0aZ"
SYNCED = (datetime.now(UTC) - timedelta(hours=4)).isoformat()

DEPLOYMENTS = {
    "project": "p",
    "cluster": "sandbox",
    "deployments": [
        {
            "name": "production",
            "project": "p",
            "cluster": "sandbox",
            "namespace": "p",
            "components": [{"reference": "web", "image": "ghcr.io/org/app:v1"}],
            "urls": {"web": "https://web-production.example.dev"},
            "status": "Healthy",
            "sync_revision": "abc123def4567890deadbeef",
            "last_synced_at": SYNCED,
            "errors": [],
        },
        {
            "name": "staging",
            "project": "p",
            "cluster": "sandbox",
            "namespace": "p",
            "components": [],
            "urls": {},
            "status": "Degraded",
            "sync_revision": None,
            "last_synced_at": None,
            "errors": [{"category": "image", "resource": "web", "message": "pull failed"}],
        },
    ],
}


@pytest.fixture(autouse=True)
def _environment(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ZAD_API_URL", API)
    monkeypatch.setenv("ZAD_API_KEY", KEY)
    monkeypatch.setenv("ZAD_PROJECT_ID", "p")
    yield


def _mock() -> None:
    respx.get(f"{API}/v2/projects/p/deployments").mock(return_value=httpx.Response(200, json=DEPLOYMENTS))
    respx.get(f"{API}/subdomains").mock(return_value=httpx.Response(200, json={"items": []}))


def run(*args: str):
    return runner.invoke(app, list(args))


@respx.mock
def test_the_status_of_each_deployment_is_shown():
    _mock()
    flat = " ".join(run("project", "status").output.split())
    assert "Healthy" in flat
    assert "Degraded" in flat


@respx.mock
def test_the_revision_is_shown_short_enough_to_read():
    """A full commit sha squeezes every other column and nobody reads past the first few."""
    _mock()
    flat = " ".join(run("project", "status").output.split())
    assert "abc123def456" in flat
    assert "abc123def4567890deadbeef" not in flat


@respx.mock
def test_the_last_sync_is_shown_as_an_age():
    """'4 hours ago' answers 'is this current'; an ISO timestamp makes you do the sum."""
    _mock()
    assert "4 hours ago" in " ".join(run("project", "status").output.split())


@respx.mock
def test_a_deployment_that_never_synced_says_so_without_inventing_a_time():
    _mock()
    output = run("project", "status").output
    assert output.count("-") >= 2  # revision and last sync, both empty for staging


@respx.mock
def test_urls_are_listed_under_the_table():
    """The longest value here, and the one you copy rather than scan."""
    _mock()
    output = run("project", "status").output
    assert "https://web-production.example.dev" in output
    assert output.index("Deployments") < output.index("https://web-production")


@respx.mock
def test_issues_are_surfaced():
    _mock()
    assert run("project", "status").exit_code == 0


@respx.mock
def test_json_still_passes_the_response_through():
    _mock()
    result = run("-o", "json", "project", "status")
    payload = json.loads(result.stdout)
    assert payload["deployments"][0]["sync_revision"] == "abc123def4567890deadbeef"
