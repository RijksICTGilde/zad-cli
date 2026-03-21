"""Tests for settings resolution."""

from unittest.mock import patch


def test_defaults():
    with patch.dict("os.environ", {}, clear=True):
        from zad_cli.settings import Settings

        s = Settings.resolve()
        assert s.api_url == "https://operations-manager.rig.prd1.gn2.quattro.rijksapps.nl/api"
        assert s.api_key == ""
        assert s.project_id == ""
        assert s.output_format == "table"


def test_env_vars():
    with patch.dict(
        "os.environ",
        {"ZAD_API_KEY": "env-key", "ZAD_API_URL": "https://custom/api", "ZAD_PROJECT_ID": "my-proj"},
    ):
        from zad_cli.settings import Settings

        s = Settings.resolve()
        assert s.api_key == "env-key"
        assert s.api_url == "https://custom/api"
        assert s.project_id == "my-proj"


def test_flags_override_env():
    with patch.dict("os.environ", {"ZAD_API_KEY": "env-key", "ZAD_PROJECT_ID": "env-proj"}):
        from zad_cli.settings import Settings

        s = Settings.resolve(api_key="flag-key", project_id="flag-proj")
        assert s.api_key == "flag-key"
        assert s.project_id == "flag-proj"
