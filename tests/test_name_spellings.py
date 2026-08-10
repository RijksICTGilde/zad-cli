"""The first positional of every component and deployment command is also --name.

The positional reads well by hand; the option says what the value is, which is what a
script or an agent wants. Two spellings that disagree are refused: one silently winning
means acting on the wrong resource.
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from zad_cli.cli import app

runner = CliRunner()
KEY = "Xk3mQ9vP2rT7wY1bN5cL8hJ4gF6dS0aZ"


@pytest.fixture(autouse=True)
def _environment(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ZAD_API_URL", "https://api.example.com")
    monkeypatch.setenv("ZAD_API_KEY", KEY)
    monkeypatch.setenv("ZAD_PROJECT_ID", "p")
    yield


# (argv without the name, the payload field the name lands in)
CASES = [
    (["component", "add"], "name"),
    (["deployment", "create", "-y"], "deploymentName"),
]


@pytest.mark.parametrize(("argv", "field"), CASES)
def test_both_spellings_give_the_same_payload(argv: list[str], field: str):
    positional = runner.invoke(app, ["-o", "json", *argv, "x1", "--dry-run"])
    explicit = runner.invoke(app, ["-o", "json", *argv, "--name", "x1", "--dry-run"])
    assert positional.exit_code == 0, positional.output
    assert explicit.exit_code == 0, explicit.output
    assert json.loads(positional.stdout)["payload"][field] == "x1"
    assert json.loads(explicit.stdout)["payload"] == json.loads(positional.stdout)["payload"]


@pytest.mark.parametrize(("argv", "_field"), CASES)
def test_disagreeing_spellings_are_refused(argv: list[str], _field: str):
    result = runner.invoke(app, [*argv, "x1", "--name", "x2", "--dry-run"])
    assert result.exit_code != 0
    assert "disagree" in result.output


@pytest.mark.parametrize(("argv", "_field"), CASES)
def test_a_missing_name_names_both_ways_to_give_it(argv: list[str], _field: str):
    result = runner.invoke(app, [*argv, "--dry-run"])
    assert result.exit_code != 0
    assert "--name" in result.output


@pytest.mark.parametrize(
    ("group", "command"),
    [
        ("component", "add"),
        ("component", "assign"),
        ("component", "update"),
        ("component", "delete"),
        ("deployment", "describe"),
        ("deployment", "create"),
        ("deployment", "update-image"),
        ("deployment", "refresh"),
        ("deployment", "delete"),
    ],
)
def test_every_command_offers_name_as_an_option(group: str, command: str):
    """The whole point is that this holds everywhere, not only where it was convenient."""
    result = runner.invoke(app, [group, command, "--help"])
    assert result.exit_code == 0, result.output
    assert "--name" in result.stdout


def test_assign_can_be_fully_explicit():
    """Two positionals: order fills them, so both need an option or neither can be named."""
    result = runner.invoke(
        app,
        ["-o", "json", "component", "assign", "--name", "web", "--deployment", "prod", "--image", "i", "--dry-run"],
    )
    assert result.exit_code == 0, result.output
    body = json.loads(result.stdout)
    assert body["payload"] == {"component_name": "web", "image": "i"}
    assert body["endpoint"].endswith("/deployments/prod/components")


def test_generate_skeleton_needs_no_name():
    """Printing an example manifest is not an operation on a deployment."""
    result = runner.invoke(app, ["deployment", "create", "--generate-skeleton"])
    assert result.exit_code == 0, result.output
    assert "components" in result.stdout
