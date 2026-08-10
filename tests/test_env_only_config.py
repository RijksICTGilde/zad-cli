"""There is one file: the .env in the working directory.

Nothing is written under ~, so two directories are two independent setups. This is what
makes it safe to have two terminals on two projects, which a single shared store cannot do.
"""

from __future__ import annotations

import httpx
import pytest
import respx
from typer.testing import CliRunner

from zad_cli import config, credentials
from zad_cli.cli import app
from zad_cli.envfile import env_path
from zad_cli.settings import Settings

runner = CliRunner()
KEY = "Xk3mQ9vP2rT7wY1bN5cL8hJ4gF6dS0aZ"


def run(*args: str):
    return runner.invoke(app, list(args))


def test_config_set_writes_the_working_directory(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """Not the home directory: that is the whole point."""
    monkeypatch.chdir(tmp_path)
    result = run("config", "set", "rollout", "false")
    assert result.exit_code == 0, result.output
    assert (tmp_path / ".env").read_text().strip() == "ZAD_ROLLOUT=false"


def test_two_directories_keep_their_own_settings(monkeypatch: pytest.MonkeyPatch, tmp_path):
    een, twee = tmp_path / "een", tmp_path / "twee"
    een.mkdir()
    twee.mkdir()

    monkeypatch.chdir(een)
    config.set_value("api_url", "https://een/api")
    credentials.store_api_key("proj-een", KEY)

    monkeypatch.chdir(twee)
    config.set_value("api_url", "https://twee/api")

    assert Settings.resolve().api_url == "https://twee/api"
    assert credentials.get_active_project() is None

    monkeypatch.chdir(een)
    assert Settings.resolve().api_url == "https://een/api"
    assert credentials.get_active_project() == "proj-een"


def test_nothing_is_written_outside_the_working_directory(monkeypatch: pytest.MonkeyPatch, tmp_path):
    home = tmp_path / "thuis"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)

    run("config", "set", "rollout", "false")
    credentials.store_token("tok-123")

    assert not (home / ".config").exists()


# --- Confirmation as a setting ---


def test_yes_can_be_set_so_the_obvious_is_not_asked_every_run():
    config.set_value("yes", "true")
    assert Settings.resolve().assume_yes is True
    assert Settings.resolve().sources["yes"] == "envfile"


def test_asking_is_still_the_default():
    assert Settings.resolve().assume_yes is False


def test_an_exported_no_beats_a_file_that_says_yes(monkeypatch: pytest.MonkeyPatch):
    """Turning it back off for one shell has to work, or the setting is a trap."""
    config.set_value("yes", "true")
    monkeypatch.setenv("ZAD_YES", "false")
    settings = Settings.resolve()
    assert settings.assume_yes is False
    assert settings.sources["yes"] == "env"


@respx.mock
def test_a_destructive_command_stops_asking_when_the_setting_says_so(monkeypatch: pytest.MonkeyPatch):
    """No stdin: without the setting typer.confirm aborts, with it the command proceeds.

    Not via --dry-run, because that returns before the confirmation by design.
    """
    monkeypatch.setenv("ZAD_API_URL", "https://api.example.com")
    monkeypatch.setenv("ZAD_API_KEY", KEY)
    monkeypatch.setenv("ZAD_PROJECT_ID", "p")
    route = respx.delete("https://api.example.com/v2/projects/p/d").mock(
        return_value=httpx.Response(200, json={"status": "ok"})
    )

    aborted = run("deployment", "delete", "d")
    assert aborted.exit_code != 0
    assert not route.called

    monkeypatch.setenv("ZAD_YES", "true")
    proceeded = run("deployment", "delete", "d")
    assert proceeded.exit_code == 0, proceeded.output
    assert route.called


def test_config_set_refuses_a_yes_that_is_not_a_boolean():
    result = run("config", "set", "yes", "misschien")
    assert result.exit_code == 1
    assert "true or false" in result.output


def test_the_env_file_is_not_world_readable_after_a_secret_lands_in_it():
    credentials.store_token("tok-123")
    assert env_path().stat().st_mode & 0o077 == 0
