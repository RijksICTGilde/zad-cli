"""Choosing a project: the picker, the no-TTY path, and what `use` says afterwards."""

from __future__ import annotations

import json

import httpx
import pytest
import respx
from typer.testing import CliRunner

from zad_cli import credentials
from zad_cli.cli import app

API = "https://api.example.com"
KEY = "Xk3mQ9vP2rT7wY1bN5cL8hJ4gF6dS0aZ"

runner = CliRunner()


@pytest.fixture(autouse=True)
def _environment(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ZAD_API_URL", API)
    monkeypatch.delenv("ZAD_API_KEY", raising=False)
    monkeypatch.delenv("ZAD_PROJECT_ID", raising=False)
    yield


def run(*args: str):
    return runner.invoke(app, list(args))


@pytest.fixture
def _tty(monkeypatch: pytest.MonkeyPatch):
    """Pretend there is a terminal on both ends, without there being one."""
    from zad_cli import picker

    monkeypatch.setattr(picker, "is_interactive", lambda: True)
    yield


def _projects_route(*names: str):
    return respx.get(f"{API}/v2/projects").mock(
        return_value=httpx.Response(
            200,
            json={
                "projects": [
                    {"name": name, "role": "admin", "description": f"{name} beschrijving", "api_key": KEY}
                    for name in names
                ]
            },
        )
    )


# --- Without a terminal ---


def test_use_without_a_name_and_without_a_tty_says_what_to_do():
    result = run("project", "use")
    assert result.exit_code == 1
    assert "zadctl project list" in result.output
    assert "terminal" in result.output


def test_use_without_a_name_in_json_mode_never_opens_a_picker(_tty):
    """A picker drawn into a pipeline would be both invisible and wrong."""
    result = run("-o", "json", "project", "use")
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error"].startswith("No project name")


def test_use_with_a_name_still_works_without_a_terminal():
    result = run("project", "use", "p")
    assert result.exit_code == 0, result.output
    assert credentials.get_active_project() == "p"


# --- With a terminal ---


@respx.mock
def test_the_picker_makes_the_chosen_project_active(_tty, monkeypatch: pytest.MonkeyPatch):
    credentials.store_token("tok-123")
    _projects_route("een", "twee")
    from zad_cli import picker

    monkeypatch.setattr(picker, "pick", lambda choices, *, title, initial=0: choices[1].value)

    result = run("project", "use")
    assert result.exit_code == 0, result.output
    assert credentials.get_active_project() == "twee"


@respx.mock
def test_the_picker_starts_on_the_project_that_is_already_active(_tty, monkeypatch: pytest.MonkeyPatch):
    credentials.store_token("tok-123")
    credentials.set_active_project("twee")
    _projects_route("een", "twee")
    seen: dict = {}
    from zad_cli import picker

    def fake_pick(choices, *, title, initial=0):
        seen["choices"] = choices
        seen["initial"] = initial
        return choices[initial].value

    monkeypatch.setattr(picker, "pick", fake_pick)
    result = run("project", "use")
    assert result.exit_code == 0, result.output
    assert seen["initial"] == 1
    assert "(active)" in seen["choices"][1].hint


@respx.mock
def test_the_picker_never_shows_an_api_key(_tty, monkeypatch: pytest.MonkeyPatch):
    credentials.store_token("tok-123")
    _projects_route("een")
    seen: dict = {}
    from zad_cli import picker

    def fake_pick(choices, *, title, initial=0):
        seen["choices"] = choices
        return choices[0].value

    monkeypatch.setattr(picker, "pick", fake_pick)
    result = run("project", "use")
    assert result.exit_code == 0, result.output
    rendered = " ".join(f"{c.value} {c.label} {c.hint}" for c in seen["choices"])
    assert KEY not in rendered
    assert KEY[:4] not in rendered
    assert KEY not in result.output


@respx.mock
def test_the_picker_stores_the_key_so_the_next_command_works(_tty, monkeypatch: pytest.MonkeyPatch):
    credentials.store_token("tok-123")
    _projects_route("een")
    from zad_cli import picker

    monkeypatch.setattr(picker, "pick", lambda choices, *, title, initial=0: choices[0].value)
    run("project", "use")
    assert credentials.get_api_key("een") == KEY


@respx.mock
def test_cancelling_the_picker_leaves_the_active_project_alone(_tty, monkeypatch: pytest.MonkeyPatch):
    credentials.store_token("tok-123")
    credentials.set_active_project("oud")
    _projects_route("een", "twee")
    from zad_cli import picker

    monkeypatch.setattr(picker, "pick", lambda choices, *, title, initial=0: None)
    result = run("project", "use")
    assert result.exit_code == 1
    assert credentials.get_active_project() == "oud"


@respx.mock
def test_a_membership_of_nothing_says_how_to_make_a_project(_tty):
    credentials.store_token("tok-123")
    respx.get(f"{API}/v2/projects").mock(return_value=httpx.Response(200, json={"projects": []}))
    result = run("project", "use")
    assert result.exit_code == 1
    assert "project create" in result.output


def test_picking_without_a_token_says_to_log_in(_tty):
    result = run("project", "use")
    assert result.exit_code == 1
    assert "zadctl login" in result.output


# --- select is the same command ---


@respx.mock
def test_select_is_the_same_thing_as_use(_tty, monkeypatch: pytest.MonkeyPatch):
    credentials.store_token("tok-123")
    _projects_route("een")
    from zad_cli import picker

    monkeypatch.setattr(picker, "pick", lambda choices, *, title, initial=0: choices[0].value)
    result = run("project", "select")
    assert result.exit_code == 0, result.output
    assert credentials.get_active_project() == "een"


def test_select_takes_a_name_too():
    result = run("project", "select", "p")
    assert result.exit_code == 0, result.output
    assert credentials.get_active_project() == "p"


# --- What it says afterwards ---


def test_use_says_which_project_and_api_url_now_apply():
    credentials.store_api_key("p", KEY)
    result = run("project", "use", "p")
    assert result.exit_code == 0, result.output
    assert "p" in result.output
    assert API in result.output
    # Rich wraps to the console width, so compare on the unwrapped text.
    assert "Commands here now act on" in " ".join(result.output.split())


def test_use_without_a_key_says_what_would_produce_one():
    """Being told twice that something is missing, without what fixes it, reads as broken."""
    result = run("project", "use", "zonder-sleutel")
    assert "No API key" in " ".join(result.output.split())
    assert "zadctl login" in result.output


def test_export_says_on_stderr_what_it_wrote_to_stdout():
    credentials.store_api_key("p", KEY)
    result = run("project", "use", "p", "--export")
    assert result.exit_code == 0, result.output
    assert result.stdout.strip().startswith("export ZAD_PROJECT_ID=p")


def test_write_env_names_the_variables_it_wrote(tmp_path):
    credentials.store_api_key("p", KEY)
    env_file = tmp_path / ".env"
    result = run("project", "use", "p", "--write-env", str(env_file))
    assert result.exit_code == 0, result.output
    assert "ZAD_PROJECT_ID" in result.output
    assert KEY not in result.output


# --- The listing ---


@respx.mock
def test_list_marks_the_active_project():
    credentials.store_token("tok-123")
    credentials.set_active_project("twee")
    _projects_route("een", "twee")
    result = run("-o", "json", "project", "list")
    rows = {row["name"]: row["active"] for row in json.loads(result.stdout)}
    assert rows == {"een": "", "twee": "*"}


@respx.mock
def test_list_still_hides_the_keys_when_it_marks_the_active_one():
    credentials.store_token("tok-123")
    credentials.set_active_project("een")
    _projects_route("een")
    result = run("project", "list")
    assert KEY not in result.output
