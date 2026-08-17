"""There is one file: the `.env.zadctl` in the working directory.

Nothing is written under ~, so two directories are two independent setups. This is what
makes it safe to have two terminals on two projects, which a single shared store cannot do.
"""

from __future__ import annotations

import json

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
    assert (tmp_path / ".env.zadctl").read_text().strip() == "ZAD_ROLLOUT=false"
    assert not (tmp_path / ".env").exists(), "a plain .env belongs to whoever else is in this directory"


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


def test_config_list_shows_every_setting_that_is_resolved():
    """A setting that works but is invisible in `config list` is a setting nobody trusts:
    the table is where you go to find out why the CLI is behaving the way it is."""
    from zad_cli.settings import Settings

    result = run("-o", "json", "config", "list")
    shown = {row["setting"] for row in json.loads(result.stdout)["effective"]}
    resolved = set(Settings.resolve().sources)
    assert resolved <= shown, f"resolved but not listed: {sorted(resolved - shown)}"


# --- Removing a setting ---


def test_unset_removes_the_line_instead_of_pinning_a_value():
    """Overwriting is not removing: `config set rollout true` pins the default in place,
    which then stops following it if the default ever moves."""
    from zad_cli.envfile import env_path

    config.set_value("rollout", "false")
    result = run("config", "unset", "rollout")
    assert result.exit_code == 0, result.output
    assert "ZAD_ROLLOUT" not in env_path().read_text()
    assert Settings.resolve().sources["rollout"] == "default"


def test_unset_says_what_decides_it_now():
    """The question you have right after removing a setting."""
    config.set_value("rollout", "false")
    result = run("config", "unset", "rollout")
    assert "built-in default" in " ".join(result.output.split())


def test_unset_leaves_the_other_settings_alone():
    from zad_cli.envfile import env_path

    config.set_value("rollout", "false")
    config.set_value("api_url", "https://blijft/api")
    run("config", "unset", "rollout")
    assert "ZAD_API_URL=https://blijft/api" in env_path().read_text()


def test_unset_refuses_a_key_nothing_reads():
    result = run("config", "unset", "onzin")
    assert result.exit_code == 1
    assert "Unknown config key" in result.output


def test_unset_of_something_never_set_is_not_an_error():
    """Idempotent: the end state is what was asked for either way."""
    assert run("config", "unset", "rollout").exit_code == 0


# --- Dropping the stored credentials ---


def test_unset_project_releases_the_active_project(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """`config list` shows `project` among the settings; refusing to unset it left no way
    to drop an active project short of `logout`, which throws the session away with it."""
    monkeypatch.chdir(tmp_path)
    credentials.set_active_project("proj-x")

    result = run("config", "unset", "project")

    assert result.exit_code == 0, result.output
    assert "ZAD_PROJECT_ID" not in env_path().read_text()
    assert credentials.get_active_project() is None


def test_unset_api_key_drops_only_the_key(monkeypatch: pytest.MonkeyPatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    credentials.store_api_key("proj-x", KEY)
    credentials.set_active_project("proj-x")

    result = run("config", "unset", "api_key")

    assert result.exit_code == 0, result.output
    contents = env_path().read_text()
    assert "ZAD_API_KEY" not in contents
    assert "ZAD_PROJECT_ID=proj-x" in contents


def test_the_unset_error_lists_the_credential_keys_too():
    result = run("config", "unset", "onzin")
    assert result.exit_code == 1
    assert "project" in result.output and "api_key" in result.output


# --- Two files in one directory ---


def test_a_shadowed_env_file_gets_a_warning(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """A `.env` full of ZAD_ variables next to a `.env.zadctl` reads as loaded but is not;
    the drift otherwise shows up as talking to the wrong API."""
    monkeypatch.chdir(tmp_path)
    config.set_value("rollout", "false")  # creates the .env.zadctl that wins
    (tmp_path / ".env").write_text("ZAD_API_URL=https://oud/api\n")

    result = run("config", "list")

    assert result.exit_code == 0, result.output
    assert ".env" in result.output
    assert "ignored" in result.output


def test_config_path_names_the_winner_and_warns(monkeypatch: pytest.MonkeyPatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    config.set_value("rollout", "false")
    (tmp_path / ".env").write_text("ZAD_API_URL=https://oud/api\n")

    result = run("config", "path")

    assert result.exit_code == 0
    assert str(tmp_path / ".env.zadctl") in result.output
    assert "ignored" in result.output


def test_a_lone_legacy_env_file_warns_about_nothing(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """No `.env.zadctl` means the `.env` is the one in use, not a shadowed one."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("ZAD_API_URL=https://oud/api\n")

    result = run("config", "list")

    assert result.exit_code == 0, result.output
    assert "ignored" not in result.output
