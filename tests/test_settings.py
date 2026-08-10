"""Settings resolve from flags > environment > defaults, and settings are written to .env.

conftest gives every test its own working directory and clears the ZAD_* variables, so the
`.env` written here is the only one in play.
"""

from __future__ import annotations

import pytest

from zad_cli import config
from zad_cli.envfile import env_path
from zad_cli.settings import DEFAULT_API_URL, Settings


def test_defaults():
    s = Settings.resolve()
    assert s.api_url == DEFAULT_API_URL
    assert s.api_key == ""
    assert s.project_id == ""
    assert s.output_format == "table"
    assert s.rollout is True


def test_env_vars(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ZAD_API_KEY", "env-key")
    monkeypatch.setenv("ZAD_API_URL", "https://custom/api")
    monkeypatch.setenv("ZAD_PROJECT_ID", "my-proj")
    s = Settings.resolve()
    assert (s.api_key, s.api_url, s.project_id) == ("env-key", "https://custom/api", "my-proj")
    assert s.sources["api_key"] == "env"


def test_flags_override_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ZAD_API_KEY", "env-key")
    monkeypatch.setenv("ZAD_PROJECT_ID", "env-proj")
    s = Settings.resolve(api_key="flag-key", project_id="flag-proj")
    assert (s.api_key, s.project_id) == ("flag-key", "flag-proj")
    assert s.sources["project"] == "flag"


def test_config_set_writes_the_env_file():
    config.set_value("api_url", "https://test/api")
    assert config.get("api_url") == "https://test/api"
    assert "ZAD_API_URL=https://test/api" in env_path().read_text()


def test_config_set_writes_the_variable_the_setting_is_read_from(monkeypatch: pytest.MonkeyPatch):
    """The whole point of the named settings: `rollout` has to land on ZAD_ROLLOUT."""
    config.set_value("rollout", "false")
    monkeypatch.setenv("ZAD_ROLLOUT", config.get("rollout"))
    s = Settings.resolve()
    assert s.rollout is False
    assert s.sources["rollout"] == "env"


def test_config_unset_puts_the_default_back():
    config.set_value("api_url", "https://test/api")
    config.unset("api_url")
    assert config.get("api_url") == ""
    assert Settings.resolve().api_url == DEFAULT_API_URL


def test_the_env_file_is_not_world_readable():
    """It holds an API key and an access token."""
    config.set_value("api_url", "https://test/api")
    assert env_path().stat().st_mode & 0o077 == 0


def test_writing_keeps_the_lines_it_does_not_own():
    """The file is the user's; the CLI edits only the variables it knows."""
    env_path().write_text("# mijn eigen regel\nMIJN_VAR=1\nZAD_API_URL=https://oud/api\n")
    config.set_value("api_url", "https://nieuw/api")
    text = env_path().read_text()
    assert "# mijn eigen regel" in text
    assert "MIJN_VAR=1" in text
    assert "ZAD_API_URL=https://nieuw/api" in text
    assert "https://oud/api" not in text


def test_an_unknown_key_is_refused():
    with pytest.raises(config.UnknownConfigKeyError):
        config.set_value("rolout", "false")
