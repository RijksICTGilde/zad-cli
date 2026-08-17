"""`zadctl deployment url` exists so nobody has to know a document's shape to get one value.

Downstream tooling was reaching into the raw task result of a deploy with `jq`:

    jq -r ".urls.\"$DEPLOYMENT\".urls.\"$COMPONENT\""

That nesting is whatever the API's task happened to return, passed through. This CLI never
promised it, so nothing here would have failed if it changed; and until 13 August that
field could carry an address for a component with no ingress at all, which a pipeline would
then publish as its result.
"""

from typing import Any

import pytest
from typer.testing import CliRunner

from zad_cli.cli import app

URLS = {
    "web": "https://web-productie-p1.example.dev",
    "api": "https://api-productie-p1.example.dev",
}


def _stub(monkeypatch: pytest.MonkeyPatch, urls: dict[str, str]) -> None:
    class _StubClient:
        def __init__(self, *_args, **_kwargs):
            self.wait = True
            self.verbose = False

        def describe_deployment(self, _project: str, _deployment: str) -> dict[str, Any]:
            return {"deployment": "productie", "urls": urls}

        def close(self) -> None:
            pass

    monkeypatch.setenv("ZAD_API_KEY", "k")
    monkeypatch.setenv("ZAD_PROJECT_ID", "p")
    monkeypatch.setenv("ZAD_API_URL", "https://api.example.com")
    monkeypatch.setattr("zad_cli.helpers.ZadClient", _StubClient, raising=False)
    import zad_cli.api.client as client_module

    monkeypatch.setattr(client_module, "ZadClient", _StubClient)


def test_one_component_prints_the_bare_address(monkeypatch: pytest.MonkeyPatch) -> None:
    """`URL=$(zadctl deployment url productie -c web)` has to give a usable string: no table,
    no quotes, no trailing advice."""
    _stub(monkeypatch, URLS)

    result = CliRunner().invoke(app, ["deployment", "url", "productie", "-c", "web"])

    assert result.exit_code == 0, result.output
    assert result.stdout.strip() == "https://web-productie-p1.example.dev"


def test_without_a_component_it_lists_them(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub(monkeypatch, URLS)

    result = CliRunner().invoke(app, ["deployment", "url", "productie"])

    assert result.exit_code == 0, result.output
    assert "web\thttps://web-productie-p1.example.dev" in result.stdout
    assert "api\thttps://api-productie-p1.example.dev" in result.stdout


def test_a_component_without_an_address_says_which_ones_have_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """A worker has no ingress, and "null" in a shell variable is a URL that 404s later."""
    _stub(monkeypatch, URLS)

    result = CliRunner().invoke(app, ["deployment", "url", "productie", "-c", "worker"])

    assert result.exit_code != 0
    assert "web" in result.output and "api" in result.output
    assert "publish-on-web" in result.output


def test_json_gives_the_map(monkeypatch: pytest.MonkeyPatch) -> None:
    import json

    _stub(monkeypatch, URLS)

    result = CliRunner().invoke(app, ["-o", "json", "deployment", "url", "productie"])

    assert json.loads(result.stdout) == URLS
