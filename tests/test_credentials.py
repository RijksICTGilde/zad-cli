"""The API key, the token and the active project live in the working directory's .env.

conftest gives every test its own working directory, so what is written here is the only
.env in play.
"""

from __future__ import annotations

import pytest

from zad_cli import credentials
from zad_cli.envfile import env_path

KEY = "Xk3mQ9vP2rT7wY1bN5cL8hJ4gF6dS0aZ"


def test_redact_shows_enough_to_recognise_not_enough_to_use():
    assert credentials.redact(KEY).startswith("Xk3m")
    assert KEY not in credentials.redact(KEY)
    assert credentials.redact("") == ""
    assert credentials.redact("kort") == "****"


def test_the_key_is_stored_with_the_project_it_belongs_to():
    """One directory is one project, so the two are written together or they drift."""
    credentials.store_api_key("proj-a", KEY)
    assert credentials.get_api_key() == KEY
    assert credentials.get_active_project() == "proj-a"


def test_the_environment_wins_over_the_file(monkeypatch: pytest.MonkeyPatch):
    """A script that exports a key means it; the file is the remembered default."""
    credentials.store_api_key("proj-a", KEY)
    monkeypatch.setenv("ZAD_API_KEY", "van-de-omgeving")
    assert credentials.get_api_key() == "van-de-omgeving"


def test_the_token_round_trips():
    credentials.store_token("tok-123")
    assert credentials.get_token() == "tok-123"


def test_clear_forgets_the_secrets_but_not_the_settings():
    credentials.store_api_key("proj-a", KEY)
    credentials.store_token("tok-123")
    env_path().write_text(env_path().read_text() + "ZAD_API_URL=https://blijft/api\n")

    credentials.clear()

    assert credentials.get_token() is None
    assert credentials.get_api_key() is None
    assert credentials.get_active_project() is None
    assert "ZAD_API_URL=https://blijft/api" in env_path().read_text()


def test_secrets_are_not_world_readable():
    credentials.store_token("tok-123")
    assert env_path().stat().st_mode & 0o077 == 0


def test_two_directories_do_not_share_a_project(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """The reason the home-directory store went away: two checkouts, two projects."""
    credentials.store_api_key("proj-a", KEY)

    other = tmp_path / "elders"
    other.mkdir()
    monkeypatch.chdir(other)
    assert credentials.get_active_project() is None

    credentials.store_api_key("proj-b", "sleutel-b")
    assert credentials.get_active_project() == "proj-b"
