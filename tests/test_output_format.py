"""Output format is a setting: flag > env > config > default, with --json/--yaml as sugar."""

from __future__ import annotations

import json

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


# --- Errors follow the format that was asked for ---
#
# Through a subprocess, because this is entrypoint behaviour: `main()` leaves Click's
# standalone mode to catch usage errors, and CliRunner calls the app directly.


def _cli(*args: str, env: dict[str, str] | None = None):
    import os
    import subprocess
    import sys
    import tempfile

    return subprocess.run(
        [sys.executable, "-m", "zad_cli", *args],
        capture_output=True,
        text=True,
        env={
            "PATH": os.environ.get("PATH", ""),
            "NO_COLOR": "1",
            "TERM": "dumb",
            "ZAD_CATALOG_OFFLINE": "1",
            **(env or {}),
        },
        cwd=tempfile.mkdtemp(),
    )


def test_a_usage_error_is_json_when_json_was_asked_for():
    """Otherwise a caller parsing stdout gets structure for every success and a drawn box
    for the most ordinary failure there is."""
    result = _cli("--json", "attachment", "add")
    assert result.returncode == 1, result.stderr
    payload = json.loads(result.stdout)
    assert "attachment_id" in payload["error"]
    assert payload["status_code"] == 1
    assert "--help" in payload["details"]["help"]


def test_a_usage_error_exits_one_and_not_clicks_two():
    """This CLI publishes what its exit codes mean, and 2 says "platform, worth retrying".

    Click's convention is 2 for any usage error, which made a mistyped flag look retryable
    to the one reader that cannot tell from the message: a script. A wrong argument is your
    input, the same as a rejected field, so it is 1.
    """
    result = _cli("-o", "table", "attachment", "add")
    assert result.returncode == 1
    assert "Missing argument" in result.stderr + result.stdout
    assert not result.stdout.strip().startswith("{")


def test_an_exported_format_decides_too():
    """The format is a setting, so an error has to honour it without a flag as well."""
    result = _cli("attachment", "add", env={"ZAD_OUTPUT_FORMAT": "json"})
    assert result.returncode == 1
    assert json.loads(result.stdout)["status_code"] == 1


def test_a_successful_command_still_exits_zero():
    """Leaving Click's standalone mode means owning the exit codes; this is the one that
    would break silently."""
    assert _cli("service", "list").returncode == 0


def test_a_command_that_raises_exit_keeps_its_code():
    """Outside standalone mode Click returns the code rather than raising it."""
    assert _cli("config", "set", "output", "xml").returncode == 1


def test_an_aborted_confirmation_exits_one():
    result = _cli("deployment", "delete", "d", env={"ZAD_API_KEY": "k", "ZAD_PROJECT_ID": "p"})
    assert result.returncode == 1
