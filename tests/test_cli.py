"""Tests for CLI entry point."""

import os
import re
import subprocess
import sys

# Env that disables Rich color codes (bold/dim may still appear)
_PLAIN_ENV = {**os.environ, "NO_COLOR": "1", "TERM": "dumb"}

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def _run_help(*args: str) -> subprocess.CompletedProcess:
    """Run a CLI command with --help and return the result."""
    return subprocess.run(
        [sys.executable, "-m", "zad_cli", *args, "--help"],
        capture_output=True,
        text=True,
        env=_PLAIN_ENV,
    )


def test_help_exits_zero():
    result = _run_help()
    out = _strip_ansi(result.stdout)
    assert result.returncode == 0
    assert "CLI for ZAD" in out
    assert "--api-key" in out
    assert "--project" in out
    assert "ZAD_PROJECT_ID" in out
    assert "--verbose" in out


def test_version():
    result = subprocess.run(
        [sys.executable, "-m", "zad_cli", "version"],
        capture_output=True,
        text=True,
        env=_PLAIN_ENV,
    )
    assert result.returncode == 0
    assert "zad-cli" in result.stdout


def test_project_help_without_api_key():
    result = _run_help("project")
    out = _strip_ansi(result.stdout)
    assert result.returncode == 0
    assert "list" in out
    assert "status" in out
    assert "delete" in out
    assert "refresh" in out
    assert "subdomains" in out
    assert "check-subdomain" in out


def test_deployment_help_shows_create():
    result = _run_help("deployment")
    out = _strip_ansi(result.stdout)
    assert result.returncode == 0
    assert "create" in out
    assert "delete" in out
    assert "update-image" in out
    # check-subdomain was moved to project
    assert "check-subdomain" not in out


def test_deploy_create_takes_positional_name():
    """deployment create takes deployment name as positional argument."""
    result = subprocess.run(
        [sys.executable, "-m", "zad_cli", "deployment", "create", "test"],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "NO_COLOR": "1", "TERM": "dumb"},
    )
    err = _strip_ansi(result.stderr)
    assert result.returncode != 0
    # Should fail on missing project/key or missing component args, not on argument parsing
    assert "ZAD_PROJECT_ID" in err or "ZAD_API_KEY" in err or "--component" in err


def test_component_help_shows_delete():
    result = _run_help("component")
    out = _strip_ansi(result.stdout)
    assert result.returncode == 0
    assert "delete" in out
    assert "add" in out
    assert "list" in out


def test_service_help_shows_delete():
    result = _run_help("service")
    out = _strip_ansi(result.stdout)
    assert result.returncode == 0
    assert "delete" in out
    assert "add" in out
    assert "types" in out


def test_task_list_uses_filter_project():
    """task list should use --filter-project to clearly distinguish from global -p."""
    result = _run_help("task", "list")
    out = _strip_ansi(result.stdout)
    assert result.returncode == 0
    assert "--filter-project" in out


def test_deployment_create_has_yes_flag():
    """deployment create (upsert) should require confirmation via --yes."""
    result = _run_help("deployment", "create")
    out = _strip_ansi(result.stdout)
    assert result.returncode == 0
    assert "--yes" in out


def test_logs_takes_positional_deployment():
    """logs should accept deployment as a positional argument."""
    result = _run_help("logs")
    out = _strip_ansi(result.stdout)
    assert result.returncode == 0
    assert "DEPLOYMENT" in out


def test_clone_help_shows_check():
    result = _run_help("clone")
    out = _strip_ansi(result.stdout)
    assert result.returncode == 0
    assert "check" in out


def test_all_subcommands_have_help():
    """Verify every sub-command group responds to --help."""
    subcommands = [
        "config",
        "project",
        "deployment",
        "component",
        "service",
        "resource",
        "task",
        "backup",
        "restore",
        "clone",
        "logs",
        "metrics",
        "open",
    ]
    for cmd in subcommands:
        result = _run_help(cmd)
        assert result.returncode == 0, f"{cmd} --help failed: {result.stderr}"


# --- Global options in any position ---

_MINIMAL_ENV = {"PATH": "/usr/bin:/bin", "NO_COLOR": "1", "TERM": "dumb"}


def test_global_option_after_subcommand():
    """Global options like --output should work after the subcommand."""
    result = subprocess.run(
        [sys.executable, "-m", "zad_cli", "metrics", "overview", "--output", "json"],
        capture_output=True,
        text=True,
        env=_MINIMAL_ENV,
    )
    err = _strip_ansi(result.stderr)
    assert "No such option" not in err


def test_global_option_equals_form():
    """--output=json form should also work after the subcommand."""
    result = subprocess.run(
        [sys.executable, "-m", "zad_cli", "deployment", "list", "--output=yaml"],
        capture_output=True,
        text=True,
        env=_MINIMAL_ENV,
    )
    err = _strip_ansi(result.stderr)
    assert "No such option" not in err


def test_global_flag_after_subcommand():
    """Global flags like --verbose should work after the subcommand."""
    result = subprocess.run(
        [sys.executable, "-m", "zad_cli", "metrics", "overview", "--verbose"],
        capture_output=True,
        text=True,
        env=_MINIMAL_ENV,
    )
    err = _strip_ansi(result.stderr)
    assert "No such option" not in err
