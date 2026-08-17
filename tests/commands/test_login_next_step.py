"""What `zadctl login` says when it is done: who you are, and the step after this one."""

from __future__ import annotations

import base64
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


def _refuse_to_be_asked(*_args, **_kwargs):
    raise AssertionError("the login asked a question")


def run(*args: str):
    return runner.invoke(app, list(args))


def jwt(claims: dict) -> str:
    body = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"header.{body}.signature"


def test_login_names_who_you_are():
    result = run("login", "--token", jwt({"preferred_username": "robbert"}))
    assert result.exit_code == 0, result.output
    assert "robbert" in result.output


def test_a_token_that_is_not_a_jwt_is_still_a_working_token():
    result = run("login", "--token", "plain-token")
    assert result.exit_code == 0, result.output
    assert credentials.get_token() == "plain-token"
    assert "Signed in" in result.output


def test_login_without_an_active_project_points_at_the_next_command():
    result = run("login", "--token", "tok-123")
    output = " ".join(result.output.split())
    assert "zadctl project use" in output
    assert "zadctl project list" in output


def test_login_with_an_active_project_says_what_it_is():
    credentials.set_active_project("mijn-project")
    result = run("login", "--token", "tok-123")
    output = " ".join(result.output.split())
    assert "mijn-project" in output
    assert "zadctl project status" in output


def test_login_in_a_terminal_asks_nothing(monkeypatch: pytest.MonkeyPatch):
    """It used to ask "Pick an active project now?" and open the picker on yes. That is a
    question standing in front of an answer: the reader came to sign in, and got a prompt about
    something else. It names the ways on instead, and picks nothing by itself."""
    from zad_cli import picker

    monkeypatch.setattr(picker, "is_interactive", lambda: True)
    monkeypatch.setattr("typer.confirm", _refuse_to_be_asked)

    result = run("login", "--token", "tok-123")

    assert result.exit_code == 0, result.output
    assert credentials.get_active_project() in (None, "")
    assert "zadctl project use" in " ".join(result.output.split())


def test_login_does_not_list_the_projects(monkeypatch: pytest.MonkeyPatch):
    """Someone who is a member of thirty gets a screen of names they did not ask for and still
    has to type one. No call goes out for them."""
    from zad_cli import picker

    monkeypatch.setattr(picker, "is_interactive", lambda: True)

    with respx.mock:
        listed = respx.get(f"{API}/v2/projects").mock(return_value=httpx.Response(200, json={"projects": []}))
        result = run("login", "--token", "tok-123")

    assert result.exit_code == 0, result.output
    assert not listed.called, "the login has no business fetching the project list"


def test_declining_the_picker_still_names_the_command(monkeypatch: pytest.MonkeyPatch):
    from zad_cli import picker

    monkeypatch.setattr(picker, "is_interactive", lambda: True)
    monkeypatch.setattr("typer.confirm", lambda *a, **k: False)
    result = run("login", "--token", "tok-123")
    assert result.exit_code == 0, result.output
    assert "zadctl project use" in " ".join(result.output.split())
