"""Which Keycloak `zad login` talks to: flag > env > config > default, for all three parts.

The base URL is the one that moves when you point the CLI at a test realm, so it has to
move on its own, without the realm and the client having to be retyped with it.
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from zad_cli import config
from zad_cli.cli import app
from zad_cli.settings import (
    DEFAULT_KEYCLOAK_CLIENT_ID,
    DEFAULT_KEYCLOAK_REALM,
    DEFAULT_KEYCLOAK_URL,
    Settings,
)

runner = CliRunner()


@pytest.fixture(autouse=True)
def _environment(monkeypatch: pytest.MonkeyPatch):
    for name in ("ZAD_KEYCLOAK_URL", "ZAD_KEYCLOAK_REALM", "ZAD_KEYCLOAK_CLIENT_ID", "ZAD_SSO_ISSUER"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("ZAD_SSO_CLIENT_ID", raising=False)
    yield


def run(*args: str):
    return runner.invoke(app, list(args))


# --- The defaults are the production environment ---


def test_the_defaults_point_at_production():
    settings = Settings.resolve()
    assert settings.keycloak_url == "https://keycloak.rijksapp.nl"
    assert settings.keycloak_realm == "rig-platform"
    assert settings.keycloak_client_id == "zad-cli"
    assert settings.sso_issuer == "https://keycloak.rijksapp.nl/realms/rig-platform"
    assert settings.sources["keycloak_url"] == "default"


def test_the_issuer_is_composed_from_the_base_url_and_the_realm():
    assert (DEFAULT_KEYCLOAK_URL, DEFAULT_KEYCLOAK_REALM, DEFAULT_KEYCLOAK_CLIENT_ID) == (
        "https://keycloak.rijksapp.nl",
        "rig-platform",
        "zad-cli",
    )


def test_no_keycloak_host_is_derived_from_the_api_url(monkeypatch: pytest.MonkeyPatch):
    """The old heuristic turned zad.x into keycloak.x with realm operations-manager.

    For production that guessed wrong, so the API URL must have no say at all.
    """
    monkeypatch.setenv("ZAD_API_URL", "https://zad.sandbox.rijksapp.dev/api")
    settings = Settings.resolve()
    assert settings.sso_issuer == "https://keycloak.rijksapp.nl/realms/rig-platform"
    assert "sandbox" not in settings.sso_issuer
    assert "operations-manager" not in settings.sso_issuer


# --- The chain, for each of the three ---


def test_the_config_file_moves_the_base_url_on_its_own():
    """The one thing 'klaar als' asks for: one setting, realm and client untouched."""
    config.set_value("keycloak_url", "https://keycloak.test.example")
    settings = Settings.resolve()
    assert settings.sso_issuer == "https://keycloak.test.example/realms/rig-platform"
    assert settings.keycloak_client_id == "zad-cli"
    assert settings.sources["keycloak_url"] == "config"


@pytest.mark.parametrize(
    ("key", "env", "attribute"),
    [
        ("keycloak_url", "ZAD_KEYCLOAK_URL", "keycloak_url"),
        ("keycloak_realm", "ZAD_KEYCLOAK_REALM", "keycloak_realm"),
        ("keycloak_client_id", "ZAD_KEYCLOAK_CLIENT_ID", "keycloak_client_id"),
    ],
)
def test_env_beats_config_and_the_flag_beats_env(monkeypatch: pytest.MonkeyPatch, key: str, env: str, attribute: str):
    value = "https://from-config.example" if key == "keycloak_url" else "from-config"
    config.set_value(key, value)
    assert getattr(Settings.resolve(), attribute) == value
    assert Settings.resolve().sources[key] == "config"

    monkeypatch.setenv(env, "https://from-env.example" if key == "keycloak_url" else "from-env")
    settings = Settings.resolve()
    assert "from-env" in getattr(settings, attribute)
    assert settings.sources[key] == "env"

    flag = "https://from-flag.example" if key == "keycloak_url" else "from-flag"
    settings = Settings.resolve(**{key: flag})
    assert getattr(settings, attribute) == flag
    assert settings.sources[key] == "flag"


def test_the_trailing_slash_does_not_double_up_in_the_issuer():
    config.set_value("keycloak_url", "https://keycloak.test.example/")
    assert Settings.resolve().sso_issuer == "https://keycloak.test.example/realms/rig-platform"


# --- The overrides CLI-1 shipped keep working ---


def test_sso_issuer_skips_the_composition(monkeypatch: pytest.MonkeyPatch):
    config.set_value("keycloak_url", "https://keycloak.test.example")
    monkeypatch.setenv("ZAD_SSO_ISSUER", "https://elders.example/auth/realms/anders/")
    settings = Settings.resolve()
    assert settings.sso_issuer == "https://elders.example/auth/realms/anders"
    assert settings.sources["sso_issuer"] == "env"


def test_sso_client_id_still_sets_the_client(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ZAD_SSO_CLIENT_ID", "oude-client")
    settings = Settings.resolve()
    assert settings.keycloak_client_id == "oude-client"
    assert settings.sources["keycloak_client_id"] == "env"


# --- config set / list ---


def test_config_set_accepts_the_three_new_keys():
    for key, value in (
        ("keycloak_url", "https://keycloak.test.example"),
        ("keycloak_realm", "test-realm"),
        ("keycloak_client_id", "test-client"),
    ):
        result = run("config", "set", key, value)
        assert result.exit_code == 0, result.output
    assert config.get("keycloak_realm") == "test-realm"


def test_config_set_refuses_a_keycloak_url_that_is_not_a_url():
    result = run("config", "set", "keycloak_url", "keycloak.test.example")
    assert result.exit_code == 1
    assert config.get("keycloak_url") == ""


def test_config_list_shows_the_keycloak_settings_and_their_source():
    config.set_value("keycloak_url", "https://keycloak.test.example")
    result = run("-o", "json", "config", "list")
    effective = {row["setting"]: row for row in json.loads(result.stdout)["effective"]}
    assert effective["keycloak_url"]["value"] == "https://keycloak.test.example"
    assert "config file" in effective["keycloak_url"]["source"]
    assert effective["keycloak_realm"]["value"] == "rig-platform"
    assert effective["keycloak_client_id"]["value"] == "zad-cli"
    assert effective["sso_issuer"]["value"] == "https://keycloak.test.example/realms/rig-platform"


def test_the_flag_reaches_the_settings_through_the_cli():
    result = run("--keycloak-url", "https://k.example", "-o", "json", "config", "list")
    effective = {row["setting"]: row for row in json.loads(result.stdout)["effective"]}
    assert effective["keycloak_url"]["value"] == "https://k.example"
    assert "flag" in effective["keycloak_url"]["source"]
