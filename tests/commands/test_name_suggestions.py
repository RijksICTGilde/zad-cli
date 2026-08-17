"""A 404 on a name should say which names do exist.

Reading "deployment 'productei' does not exist" and then having to run `deployment list`
to find the spelling is two commands for one question, and the second one is the same
question asked again.
"""

import httpx
import pytest
import respx
from typer.testing import CliRunner

from zad_cli.cli import app

API = "https://api.example.com"


@pytest.fixture(autouse=True)
def _environment(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ZAD_API_URL", API)
    monkeypatch.setenv("ZAD_API_KEY", "k")
    monkeypatch.setenv("ZAD_PROJECT_ID", "p")
    yield


def _deployments(*names: str) -> None:
    respx.get(f"{API}/v2/projects/p/deployments").mock(
        return_value=httpx.Response(
            200,
            json={
                "project": "p",
                "cluster": "sandboxed-local",
                "deployments": [
                    {
                        "name": n,
                        "project": "p",
                        "cluster": "sandboxed-local",
                        "namespace": "ns",
                        "components": [],
                        "urls": {},
                        "status": "Healthy",
                        "sync_revision": "abc",
                        "last_synced_at": None,
                        "errors": [],
                    }
                    for n in names
                ],
            },
        )
    )


@respx.mock
def test_a_404_on_a_deployment_names_the_ones_that_exist():
    respx.get(f"{API}/v2/projects/p/deployments/productei").mock(
        return_value=httpx.Response(404, json={"detail": "Deployment 'productei' does not exist"})
    )
    _deployments("productie", "acceptatie")

    result = CliRunner().invoke(app, ["deployment", "describe", "productei"])

    assert result.exit_code != 0
    assert "productie" in result.output
    assert "acceptatie" in result.output


@respx.mock
def test_a_failing_lookup_does_not_replace_the_real_error():
    """The suggestion runs while an error is already being reported. If it cannot answer,
    silence is right; what must never happen is that it hides the 404 it came to help."""
    respx.get(f"{API}/v2/projects/p/deployments/productei").mock(
        return_value=httpx.Response(404, json={"detail": "Deployment 'productei' does not exist"})
    )
    respx.get(f"{API}/v2/projects/p/deployments").mock(return_value=httpx.Response(500, text="boom"))

    result = CliRunner().invoke(app, ["deployment", "describe", "productei"])

    assert result.exit_code != 0
    assert "does not exist" in result.output


@respx.mock
def test_an_error_that_is_not_a_404_costs_no_extra_call():
    """A 401 is not a spelling problem, and listing deployments would fail the same way."""
    route = respx.get(f"{API}/v2/projects/p/deployments/productie").mock(
        return_value=httpx.Response(401, json={"detail": "Invalid API key"})
    )
    listing = respx.get(f"{API}/v2/projects/p/deployments").mock(return_value=httpx.Response(200, json={}))

    CliRunner().invoke(app, ["deployment", "describe", "productie"])

    assert route.called
    assert not listing.called
