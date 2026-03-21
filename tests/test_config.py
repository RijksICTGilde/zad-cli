"""Tests for configuration management."""

from unittest.mock import patch

import yaml


def test_defaults_when_no_config(tmp_path):
    config_path = tmp_path / "config.yml"
    with patch("zad_cli.config.context.CONFIG_PATH", config_path):
        from zad_cli.config.context import get_context

        ctx = get_context()
        assert ctx["api_url"] == "https://operations-manager.rig.prd1.gn2.quattro.rijksapps.nl/api"
        assert ctx["output_format"] == "table"
        assert ctx["task_timeout"] == 300


def test_set_and_get(tmp_path):
    config_path = tmp_path / "config.yml"
    with patch("zad_cli.config.context.CONFIG_PATH", config_path):
        from zad_cli.config.context import get_value, set_value

        set_value("api_url", "https://custom.example.com/api")
        assert get_value("api_url") == "https://custom.example.com/api"


def test_set_numeric_value(tmp_path):
    config_path = tmp_path / "config.yml"
    with patch("zad_cli.config.context.CONFIG_PATH", config_path):
        from zad_cli.config.context import get_value, set_value

        set_value("task_timeout", "600")
        assert get_value("task_timeout") == "600"


def test_context_switching(tmp_path):
    config_path = tmp_path / "config.yml"
    with patch("zad_cli.config.context.CONFIG_PATH", config_path):
        from zad_cli.config.context import get_current_context_name, get_value, set_context, set_value

        set_value("api_url", "https://default.example.com/api")
        set_value("api_url", "https://staging.example.com/api", "staging")
        set_context("staging")

        assert get_current_context_name() == "staging"
        assert get_value("api_url") == "https://staging.example.com/api"
        assert get_value("api_url", "default") == "https://default.example.com/api"


def test_list_contexts(tmp_path):
    config_path = tmp_path / "config.yml"
    with patch("zad_cli.config.context.CONFIG_PATH", config_path):
        from zad_cli.config.context import list_contexts, set_value

        set_value("api_url", "url1", "alpha")
        set_value("api_url", "url2", "beta")

        contexts = list_contexts()
        assert "alpha" in contexts
        assert "beta" in contexts


def test_config_file_format(tmp_path):
    config_path = tmp_path / "config.yml"
    with patch("zad_cli.config.context.CONFIG_PATH", config_path):
        from zad_cli.config.context import set_context, set_value

        set_value("api_url", "https://prod.example.com/api", "production")
        set_context("production")

        data = yaml.safe_load(config_path.read_text())
        assert data["current-context"] == "production"
        assert data["contexts"]["production"]["api_url"] == "https://prod.example.com/api"


def test_settings_resolve_defaults(tmp_path):
    config_path = tmp_path / "config.yml"
    with (
        patch("zad_cli.config.context.CONFIG_PATH", config_path),
        patch.dict("os.environ", {}, clear=True),
    ):
        from zad_cli.config.settings import Settings

        settings = Settings.resolve()
        assert settings.api_url == "https://operations-manager.rig.prd1.gn2.quattro.rijksapps.nl/api"
        assert settings.api_key == ""
        assert settings.project_id == ""
        assert settings.output_format == "table"


def test_settings_env_override(tmp_path):
    config_path = tmp_path / "config.yml"
    with (
        patch("zad_cli.config.context.CONFIG_PATH", config_path),
        patch.dict(
            "os.environ",
            {"ZAD_API_KEY": "env-key", "ZAD_API_URL": "https://custom.example.com/api", "ZAD_PROJECT_ID": "my-proj"},
        ),
    ):
        from zad_cli.config.settings import Settings

        settings = Settings.resolve()
        assert settings.api_key == "env-key"
        assert settings.api_url == "https://custom.example.com/api"
        assert settings.project_id == "my-proj"


def test_settings_flag_override(tmp_path):
    config_path = tmp_path / "config.yml"
    with (
        patch("zad_cli.config.context.CONFIG_PATH", config_path),
        patch.dict("os.environ", {"ZAD_API_KEY": "env-key", "ZAD_PROJECT_ID": "env-proj"}),
    ):
        from zad_cli.config.settings import Settings

        settings = Settings.resolve(api_key="flag-key", project_id="flag-proj")
        assert settings.api_key == "flag-key"
        assert settings.project_id == "flag-proj"
