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


@respx.mock
def test_login_in_a_terminal_offers_the_picker(monkeypatch: pytest.MonkeyPatch):
    from zad_cli import picker

    monkeypatch.setattr(picker, "is_interactive", lambda: True)
    monkeypatch.setattr("typer.confirm", lambda *a, **k: True)
    monkeypatch.setattr(picker, "pick", lambda choices, *, title, initial=0: choices[0].value)
    respx.get(f"{API}/v2/projects").mock(
        return_value=httpx.Response(200, json={"projects": [{"name": "een", "role": "admin", "api_key": KEY}]})
    )

    result = run("login", "--token", "tok-123")
    assert result.exit_code == 0, result.output
    assert credentials.get_active_project() == "een"


@respx.mock
def test_a_picker_that_finds_nothing_does_not_fail_the_login(monkeypatch: pytest.MonkeyPatch):
    """Signing in worked; being a member of no project is a separate matter."""
    from zad_cli import picker

    monkeypatch.setattr(picker, "is_interactive", lambda: True)
    monkeypatch.setattr("typer.confirm", lambda *a, **k: True)
    respx.get(f"{API}/v2/projects").mock(return_value=httpx.Response(200, json={"projects": []}))

    result = run("login", "--token", "tok-123")
    assert result.exit_code == 0, result.output
    assert credentials.get_token() == "tok-123"
    assert "zadctl project use" in " ".join(result.output.split())


def test_declining_the_picker_still_names_the_command(monkeypatch: pytest.MonkeyPatch):
    from zad_cli import picker

    monkeypatch.setattr(picker, "is_interactive", lambda: True)
    monkeypatch.setattr("typer.confirm", lambda *a, **k: False)
    result = run("login", "--token", "tok-123")
    assert result.exit_code == 0, result.output
    assert "zadctl project use" in " ".join(result.output.split())
