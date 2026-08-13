"""What the CLI asks before it acts, and what it just does.

The rule: it asks before it removes something or overwrites it with older data. Everything
else acts. Thirty-two confirmations were once spread over adding, setting and updating too,
which trains people to answer "y" without reading - and that habit is worth more than the
prompts it defeats.

`--yes`, `ZAD_YES=true` and `zad config set yes true` silence the remaining ones, so a
script or an agent never meets a prompt at all.
"""

from typing import Any

import pytest
from typer.testing import CliRunner

from zad_cli.cli import app


def _stub(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    seen: dict[str, Any] = {}

    class _StubClient:
        def __init__(self, *_args, **_kwargs):
            self.wait = True
            self.verbose = False

        def __getattr__(self, name: str):
            def call(*args: Any, **kwargs: Any) -> dict:
                seen[name] = (args, kwargs)
                return {"success": True}

            return call

        def close(self) -> None:
            pass

    monkeypatch.setenv("ZAD_API_KEY", "k")
    monkeypatch.setenv("ZAD_PROJECT_ID", "p")
    monkeypatch.setenv("ZAD_API_URL", "https://api.example.com")
    monkeypatch.delenv("ZAD_YES", raising=False)
    monkeypatch.setattr("zad_cli.helpers.ZadClient", _StubClient, raising=False)
    import zad_cli.api.client as client_module

    monkeypatch.setattr(client_module, "ZadClient", _StubClient)
    return seen


# Empty stdin: a prompt with nothing to read aborts, so a command that still asks fails
# here and one that acts goes through. That is exactly the difference being asserted.
@pytest.mark.parametrize(
    "argv",
    [
        ["component", "add", "web", "--port", "8080"],
        ["component", "update", "web", "--memory-limit", "512Mi"],
        ["deployment", "create", "productie", "--component", "web", "--image", "img:1"],
        ["service", "config", "set", "redis", "--set", "acl-key-prefix=true"],
        ["env", "add", "--component", "web", "FOO=bar"],
        ["backup", "create", "productie"],
        ["db", "schema", "add", "rapportage"],
    ],
)
def test_adding_and_changing_no_longer_asks(monkeypatch: pytest.MonkeyPatch, argv: list[str]) -> None:
    _stub(monkeypatch)

    result = CliRunner().invoke(app, argv, input="")

    assert result.exit_code == 0, result.output
    assert "[y/N]" not in result.output


@pytest.mark.parametrize(
    "argv",
    [
        ["project", "delete"],
        ["deployment", "delete", "productie"],
        ["component", "delete", "web"],
        ["env", "clear", "--component", "web"],
        ["service", "config", "clear", "redis"],
    ],
)
def test_removing_still_asks(monkeypatch: pytest.MonkeyPatch, argv: list[str]) -> None:
    _stub(monkeypatch)

    result = CliRunner().invoke(app, argv, input="")

    assert result.exit_code != 0, f"{argv} went ahead without asking: {result.output}"


@pytest.mark.parametrize("argv", [["project", "delete"], ["deployment", "delete", "productie"]])
def test_the_yes_setting_silences_even_those(monkeypatch: pytest.MonkeyPatch, argv: list[str]) -> None:
    """An agent sets this once and never meets a prompt, which is the point of having it."""
    _stub(monkeypatch)
    monkeypatch.setenv("ZAD_YES", "true")

    result = CliRunner().invoke(app, argv, input="")

    assert result.exit_code == 0, result.output
