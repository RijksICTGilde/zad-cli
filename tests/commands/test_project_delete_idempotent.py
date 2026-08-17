"""A teardown step runs precisely when something earlier went wrong.

`docs/playbooks/01-inrichten.md` says so in as many words: "Draai dit ook als er hierboven
iets faalde." That only holds if deleting something already gone is a success, so
`project delete` has the same `--ignore-not-found` that `deployment delete` has.

Two ways a project can be gone, and the second is the one that actually happens: after a
successful delete the name and key are removed from the .env, so the *next* run has no
project at all and fails before any call is made.
"""

import httpx
import respx
from typer.testing import CliRunner

from zad_cli.cli import app

runner = CliRunner()
API = "https://api.example.test"
ENV = {"ZAD_API_URL": API, "ZAD_API_KEY": "k", "NO_COLOR": "1"}


@respx.mock
def test_a_project_the_api_does_not_know_is_a_success_with_the_flag():
    respx.delete(f"{API}/projects/weg").mock(return_value=httpx.Response(404, json={"detail": "Project not found"}))

    result = runner.invoke(
        app,
        ["-p", "weg", "project", "delete", "--ignore-not-found", "-y"],
        env=ENV,
    )

    assert result.exit_code == 0, result.output
    assert "already deleted" in result.output


@respx.mock
def test_without_the_flag_it_still_fails():
    respx.delete(f"{API}/projects/weg").mock(return_value=httpx.Response(404, json={"detail": "Project not found"}))

    result = runner.invoke(app, ["-p", "weg", "project", "delete", "-y"], env=ENV)

    assert result.exit_code != 0


def test_no_active_project_left_is_the_same_already_gone():
    """The second teardown run: the .env was cleared by the first one."""
    result = runner.invoke(
        app,
        ["project", "delete", "--ignore-not-found", "-y"],
        env={"ZAD_API_URL": API, "NO_COLOR": "1"},
    )

    assert result.exit_code == 0, result.output
    assert "No active project" in result.output


def test_no_project_without_the_flag_still_asks_for_one():
    result = runner.invoke(
        app,
        ["project", "delete", "-y"],
        env={"ZAD_API_URL": API, "NO_COLOR": "1"},
    )

    assert result.exit_code != 0
    assert "project is required" in result.output
