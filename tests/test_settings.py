"""Tests for settings and config."""

from unittest.mock import patch


def test_defaults():
    with (
        patch.dict("os.environ", {}, clear=True),
        patch("zad_cli.config.CONFIG_PATH", __import__("pathlib").Path("/nonexistent")),
    ):
        from zad_cli.settings import Settings

        s = Settings.resolve()
        assert s.api_url == "https://operations-manager.rig.prd1.gn2.quattro.rijksapps.nl/api"
        assert s.api_key == ""
        assert s.project_id == ""
        assert s.output_format == "table"


def test_env_vars():
    with (
        patch.dict(
            "os.environ",
            {"ZAD_API_KEY": "env-key", "ZAD_API_URL": "https://custom/api", "ZAD_PROJECT_ID": "my-proj"},
        ),
        patch("zad_cli.config.CONFIG_PATH", __import__("pathlib").Path("/nonexistent")),
    ):
        from zad_cli.settings import Settings

        s = Settings.resolve()
        assert s.api_key == "env-key"
        assert s.api_url == "https://custom/api"
        assert s.project_id == "my-proj"


def test_flags_override_env():
    with (
        patch.dict("os.environ", {"ZAD_API_KEY": "env-key", "ZAD_PROJECT_ID": "env-proj"}),
        patch("zad_cli.config.CONFIG_PATH", __import__("pathlib").Path("/nonexistent")),
    ):
        from zad_cli.settings import Settings

        s = Settings.resolve(api_key="flag-key", project_id="flag-proj")
        assert s.api_key == "flag-key"
        assert s.project_id == "flag-proj"


def test_config_file_fallback(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text('api_url = "https://from-config/api"\n')

    with (
        patch.dict("os.environ", {}, clear=True),
        patch("zad_cli.config.CONFIG_PATH", config_path),
    ):
        from zad_cli.settings import Settings

        s = Settings.resolve()
        assert s.api_url == "https://from-config/api"


def test_config_set_and_get(tmp_path):
    config_path = tmp_path / "config.toml"
    config_dir = tmp_path

    with (
        patch("zad_cli.config.CONFIG_PATH", config_path),
        patch("zad_cli.config.CONFIG_DIR", config_dir),
    ):
        from zad_cli.config import get, set_value

        set_value("api_url", "https://test/api")
        assert get("api_url") == "https://test/api"

        # File should be valid TOML
        import tomllib

        data = tomllib.loads(config_path.read_text())
        assert data["api_url"] == "https://test/api"
