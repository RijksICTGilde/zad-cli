"""`--dry-run` makes no call, so it must not demand the key it would never send.

Checking a command before you have credentials -- validating a whole plan before
logging in -- is what a dry run is for, and the key check blocked exactly that: it
demanded *some* string and then never used it. A practice run worked around it with
`ZAD_API_KEY=dummy-key`, which is a trick you should not have to invent.
"""

from __future__ import annotations

from typer.testing import CliRunner

from zad_cli.cli import app

runner = CliRunner()


def test_dry_run_needs_no_api_key():
    # conftest clears ZAD_API_KEY; only a project flag is needed.
    result = runner.invoke(app, ["component", "add", "web", "--port", "8080", "--dry-run", "-p", "some-project"])

    assert result.exit_code == 0, result.output
    assert "no API key" not in result.output
    assert "components" in result.output  # the endpoint it would have called


def test_dry_run_through_the_catalog_needs_no_api_key_either():
    result = runner.invoke(
        app,
        ["service", "config", "set", "postgresql-database", "--set", "scope=shared", "--dry-run", "-p", "some-project"],
    )

    assert result.exit_code == 0, result.output
    assert "no API key" not in result.output


def test_a_real_call_still_requires_the_key():
    result = runner.invoke(app, ["component", "add", "web", "--port", "8080", "-p", "some-project"])

    assert result.exit_code == 1
    assert "no API key" in result.output
