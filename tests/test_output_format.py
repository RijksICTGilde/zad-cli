"""Output format is a setting: flag > env > config > default, with --json/--yaml as sugar."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from zad_cli import config
from zad_cli.cli import app
from zad_cli.settings import Settings

runner = CliRunner()


@pytest.fixture(autouse=True)
def _environment(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("ZAD_OUTPUT_FORMAT", raising=False)
    yield


def test_default_is_table():
    assert Settings.resolve().output_format == "table"
    assert Settings.resolve().sources["output"] == "default"


def test_config_sets_the_default():
    config.set_value("output", "json")
    settings = Settings.resolve()
    assert settings.output_format == "json"
    assert settings.sources["output"] == "envfile"


def test_env_beats_config(monkeypatch: pytest.MonkeyPatch):
    config.set_value("output", "json")
    monkeypatch.setenv("ZAD_OUTPUT_FORMAT", "yaml")
    settings = Settings.resolve()
    assert settings.output_format == "yaml"
    assert settings.sources["output"] == "env"


def test_flag_beats_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ZAD_OUTPUT_FORMAT", "yaml")
    settings = Settings.resolve(output_format="json")
    assert settings.output_format == "json"
    assert settings.sources["output"] == "flag"


@pytest.mark.parametrize("written", ["json", "JSON", " yaml ", "table"])
def test_config_normalises_what_it_accepts(written: str):
    config.set_value("output", written)
    assert config.get("output") == written.strip().lower()


def test_config_refuses_a_format_that_cannot_be_rendered():
    """Caught at write time: the config file is read on every later run."""
    result = runner.invoke(app, ["config", "set", "output", "xml"])
    assert result.exit_code != 0
    assert "table, yaml" in result.output or "json" in result.output


def test_output_is_an_accepted_config_key():
    """`config list` shows it as a setting, so `config set` has to accept it."""
    assert "output" in config.KNOWN_KEYS


def test_json_shorthand_matches_the_long_form():
    assert runner.invoke(app, ["--json", "config", "list"]).exit_code == 0
    short = runner.invoke(app, ["--json", "service", "list"]).output
    long = runner.invoke(app, ["--output", "json", "service", "list"]).output
    assert short == long


def test_yaml_shorthand_matches_the_long_form():
    short = runner.invoke(app, ["--yaml", "service", "list"]).output
    long = runner.invoke(app, ["--output", "yaml", "service", "list"]).output
    assert short == long


def test_json_and_yaml_together_is_refused():
    result = runner.invoke(app, ["--json", "--yaml", "service", "list"])
    assert result.exit_code != 0
    assert "cannot be combined" in result.output


def test_shorthand_contradicting_output_is_refused():
    """Two ways of asking that disagree is a typo, not a precedence puzzle."""
    result = runner.invoke(app, ["--json", "--output", "yaml", "service", "list"])
    assert result.exit_code != 0
    assert "contradicts" in result.output


def test_shorthand_agreeing_with_output_is_fine():
    assert runner.invoke(app, ["--json", "--output", "json", "service", "list"]).exit_code == 0
