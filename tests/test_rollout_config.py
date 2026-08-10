"""Rolling out is a setting: flag > env > config > default, and unknown keys are refused."""

from __future__ import annotations

import json

import httpx
import pytest
import respx
from typer.testing import CliRunner

from zad_cli import config, credentials
from zad_cli.cli import app
from zad_cli.settings import Settings

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


# --- The four layers ---


def test_rollout_defaults_to_true():
    settings = Settings.resolve()
    assert settings.rollout is True
    assert settings.sources["rollout"] == "default"


def test_config_can_turn_rollout_off():
    config.set_value("rollout", "false")
    settings = Settings.resolve()
    assert settings.rollout is False
    assert settings.sources["rollout"] == "envfile"


def test_env_beats_the_config_file(monkeypatch: pytest.MonkeyPatch):
    config.set_value("rollout", "false")
    monkeypatch.setenv("ZAD_ROLLOUT", "true")
    settings = Settings.resolve()
    assert settings.rollout is True
    assert settings.sources["rollout"] == "env"


def test_the_flag_beats_everything(monkeypatch: pytest.MonkeyPatch):
    config.set_value("rollout", "false")
    monkeypatch.setenv("ZAD_ROLLOUT", "false")
    settings = Settings.resolve(rollout=True)
    assert settings.rollout is True
    assert settings.sources["rollout"] == "flag"


def test_no_rollout_on_the_command_line_beats_a_config_that_says_true():
    config.set_value("rollout", "true")
    assert Settings.resolve(rollout=False).rollout is False


def test_an_unreadable_rollout_value_fails_loudly(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ZAD_ROLLOUT", "misschien")
    with pytest.raises(SystemExit):
        Settings.resolve()


# --- A .env written by hand, which is how it is documented ---


def write_env(text: str) -> None:
    """Put a .env down the way a person would, not the way `config set` does."""
    from zad_cli.envfile import env_path

    env_path().write_text(text)


def test_a_hand_written_false_turns_rolling_out_off():
    """The one case this setting exists for, so it must survive every layer."""
    write_env("ZAD_ROLLOUT=false\n")
    settings = Settings.resolve()
    assert settings.rollout is False
    assert settings.sources["rollout"] == "envfile"


def test_a_hand_written_true_does_not_crash():
    write_env("ZAD_ROLLOUT=true\n")
    settings = Settings.resolve()
    assert settings.rollout is True
    assert settings.sources["rollout"] == "envfile"


def test_a_hand_written_value_that_is_not_a_boolean_gets_the_tidy_error(capsys):
    write_env("ZAD_ROLLOUT=misschien\n")
    with pytest.raises(SystemExit):
        Settings.resolve()
    assert "true or false" in capsys.readouterr().err


def test_an_exported_variable_beats_the_file(monkeypatch: pytest.MonkeyPatch):
    """Exporting is being explicit now; the file is what was remembered earlier."""
    write_env("ZAD_ROLLOUT=false\n")
    monkeypatch.setenv("ZAD_ROLLOUT", "true")
    settings = Settings.resolve()
    assert settings.rollout is True
    assert settings.sources["rollout"] == "env"


def test_config_get_spells_the_value_the_way_config_set_takes_it():
    write_env("ZAD_ROLLOUT=false\n")
    result = run("-o", "json", "config", "get", "rollout")
    assert json.loads(result.stdout)["value"] == "false"


def test_writing_another_key_leaves_a_hand_written_one_alone():
    write_env("ZAD_ROLLOUT=false\n")
    config.set_value("api_url", "https://api.example.com")
    assert Settings.resolve().rollout is False


def test_a_value_with_awkward_characters_stays_readable():
    config.set_value("api_url", 'https://api.example.com/"x"y')
    assert config.get("api_url") == 'https://api.example.com/"x"y'


# --- What the request actually carries ---


@respx.mock
def test_rollout_false_from_the_config_reaches_the_request():
    """The setting is not decoration: the query parameter must change with it."""
    config.set_value("rollout", "false")
    credentials.store_api_key("p", KEY)
    credentials.set_active_project("p")
    route = respx.post(f"{API}/v2/projects/p/components").mock(
        return_value=httpx.Response(202, json={"task_id": "t", "poll_url": "/api/tasks/t"})
    )
    respx.get(f"{API}/tasks/t").mock(return_value=httpx.Response(200, json={"status": "completed"}))
    respx.get(f"{API}/v2/projects/p/pending-rollout").mock(
        return_value=httpx.Response(200, json={"project": "p", "count": 1})
    )
    result = run("component", "add", "c", "--deployment", "d", "--image", "nginx:1")
    assert result.exit_code == 0, result.output
    assert route.calls[0].request.url.params["rollout"] == "false"


@respx.mock
def test_the_flag_overrides_a_config_that_says_no_rollout():
    config.set_value("rollout", "false")
    credentials.store_api_key("p", KEY)
    credentials.set_active_project("p")
    route = respx.post(f"{API}/v2/projects/p/components").mock(
        return_value=httpx.Response(202, json={"task_id": "t", "poll_url": "/api/tasks/t"})
    )
    respx.get(f"{API}/tasks/t").mock(return_value=httpx.Response(200, json={"status": "completed"}))
    result = run("--rollout", "component", "add", "c", "--deployment", "d", "--image", "nginx:1")
    assert result.exit_code == 0, result.output
    assert "rollout" not in route.calls[0].request.url.params


@respx.mock
def test_a_saved_change_says_how_many_are_waiting_and_how_to_roll_them_out():
    config.set_value("rollout", "false")
    credentials.store_api_key("p", KEY)
    credentials.set_active_project("p")
    respx.post(f"{API}/v2/projects/p/components").mock(
        return_value=httpx.Response(202, json={"task_id": "t", "poll_url": "/api/tasks/t"})
    )
    respx.get(f"{API}/tasks/t").mock(return_value=httpx.Response(200, json={"status": "completed"}))
    respx.get(f"{API}/v2/projects/p/pending-rollout").mock(
        return_value=httpx.Response(200, json={"project": "p", "count": 3})
    )
    result = run("component", "add", "c", "--deployment", "d", "--image", "nginx:1")
    output = " ".join(result.output.split())
    assert "3 change(s) waiting" in output
    assert "zad project refresh" in output


# --- config set / get / list ---


def test_config_set_refuses_a_key_nothing_reads():
    result = run("config", "set", "rolout", "false")
    assert result.exit_code == 1
    assert "api_url" in result.output
    assert "rollout" in result.output
    assert config.get("rolout") == ""


def test_config_set_refuses_a_rollout_value_that_is_not_a_boolean():
    result = run("config", "set", "rollout", "ja")
    assert result.exit_code == 1
    assert config.get("rollout") == ""


def test_config_set_normalises_the_boolean():
    result = run("config", "set", "rollout", "FALSE")
    assert result.exit_code == 0, result.output
    assert config.get("rollout") == "false"


def test_config_get_returns_rollout():
    config.set_value("rollout", "false")
    result = run("-o", "json", "config", "get", "rollout")
    assert json.loads(result.stdout)["value"] == "false"


def test_config_list_says_where_each_setting_comes_from(monkeypatch: pytest.MonkeyPatch):
    """The file and an exported variable are different answers to 'why does it do this'."""
    config.set_value("rollout", "false")
    monkeypatch.setenv("ZAD_API_URL", "https://exported/api")
    result = run("-o", "json", "config", "list")
    effective = {row["setting"]: row for row in json.loads(result.stdout)["effective"]}
    assert effective["rollout"]["value"] == "false"
    assert ".env" in effective["rollout"]["source"]
    assert "exported" in effective["api_url"]["source"]


def test_config_list_never_prints_the_api_key(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ZAD_API_KEY", KEY)
    result = run("-o", "json", "config", "list")
    assert KEY not in result.stdout
