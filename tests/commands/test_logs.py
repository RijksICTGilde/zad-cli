"""`zadctl logs`: what actually goes out on the wire.

These tests exist because both flags this command has were dead for months. `-n` went out
as `limit` from the first commit, `--since` as a parameter the API never declared, and
FastAPI drops an undeclared query parameter without a word. So `zadctl logs -n 500
--since 1h` answered 200 with the ten lines of the server default, which is exactly what a
working call looks like from the outside.

Asserting on the query string is therefore the point of these tests, not an implementation
detail: the names are the contract, and nothing else in the stack complains when they are
wrong.
"""

from __future__ import annotations

import httpx
import pytest
import respx
from typer.testing import CliRunner

from zad_cli.cli import app

runner = CliRunner()
API = "https://api.example.com"
KEY = "Xk3mQ9vP2rT7wY1bN5cL8hJ4gF6dS0aZ"

PAYLOAD = {
    "status": "success",
    "project": "mijn-project",
    "results": [
        {
            "deployment": "production",
            "component": "backend",
            "lines": ["2026/09/01 10:00:00 een oude regel", "2026/09/01 12:00:00 een verse regel"],
            "line_count": 2,
        }
    ],
}


@pytest.fixture(autouse=True)
def _environment(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ZAD_API_URL", API)
    monkeypatch.setenv("ZAD_API_KEY", KEY)
    monkeypatch.setenv("ZAD_PROJECT_ID", "mijn-project")
    yield


def _mock() -> respx.Route:
    return respx.get(f"{API}/logs/mijn-project").mock(return_value=httpx.Response(200, json=PAYLOAD))


def _params(route: respx.Route) -> dict[str, str]:
    return dict(route.calls[0].request.url.params)


@respx.mock
def test_the_line_count_goes_out_under_the_name_the_api_declares():
    route = _mock()

    result = runner.invoke(app, ["logs", "production", "-n", "500"])

    assert result.exit_code == 0, result.output
    assert _params(route) == {"deployment": "production", "lines": "500"}


@respx.mock
def test_a_window_goes_out_as_since():
    route = _mock()

    result = runner.invoke(app, ["logs", "production", "--since", "1h"])

    assert result.exit_code == 0, result.output
    assert _params(route)["since"] == "1h"


@respx.mock
def test_a_window_without_a_line_count_asks_for_the_maximum():
    """The server ANDs tail and since, so the default ten-line tail would swallow the hour.

    Newer servers open the limit themselves, but saying it here is what gets `--since`
    working against a server that predates the parameter, where the client-side filter is
    all there is.
    """
    route = _mock()

    runner.invoke(app, ["logs", "production", "--since", "1h"])

    assert _params(route)["lines"] == "1000"


@respx.mock
def test_a_plain_call_asks_for_nothing_it_does_not_need():
    """No line count and no window: the server's own default decides, as it always did."""
    route = _mock()

    runner.invoke(app, ["logs", "production"])

    assert _params(route) == {"deployment": "production"}


@respx.mock
def test_a_window_the_cli_cannot_parse_never_reaches_the_api():
    result = runner.invoke(app, ["logs", "production", "--since", "gisteren"])

    assert result.exit_code != 0
    assert not respx.calls
