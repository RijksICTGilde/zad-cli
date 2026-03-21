"""Tests for CLI entry point."""

import subprocess
import sys


def test_help_exits_zero():
    result = subprocess.run(
        [sys.executable, "-m", "zad_cli", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "CLI for ZAD" in result.stdout
    assert "--api-key" in result.stdout
    assert "--project" in result.stdout
    assert "ZAD_PROJECT_ID" in result.stdout
    assert "--verbose" in result.stdout


def test_version():
    result = subprocess.run(
        [sys.executable, "-m", "zad_cli", "version"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "zad-cli" in result.stdout


def test_project_help_without_api_key():
    result = subprocess.run(
        [sys.executable, "-m", "zad_cli", "project", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "list" in result.stdout
    assert "status" in result.stdout
    assert "delete" in result.stdout
    assert "refresh" in result.stdout
    assert "subdomains" in result.stdout


def test_deployment_help_shows_create():
    result = subprocess.run(
        [sys.executable, "-m", "zad_cli", "deployment", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "create" in result.stdout
    assert "delete" in result.stdout
    assert "update-image" in result.stdout


def test_deploy_create_takes_positional_name():
    """deployment create takes deployment name as positional argument."""
    result = subprocess.run(
        [sys.executable, "-m", "zad_cli", "deployment", "create", "test"],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin"},
    )
    assert result.returncode != 0
    # Should fail on missing project/key or missing component args, not on argument parsing
    assert "ZAD_PROJECT_ID" in result.stderr or "ZAD_API_KEY" in result.stderr or "--component" in result.stderr


def test_component_help_shows_delete():
    result = subprocess.run(
        [sys.executable, "-m", "zad_cli", "component", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "delete" in result.stdout
    assert "add" in result.stdout
    assert "list" in result.stdout


def test_service_help_shows_remove():
    result = subprocess.run(
        [sys.executable, "-m", "zad_cli", "service", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "remove" in result.stdout
    assert "add" in result.stdout
    assert "types" in result.stdout


def test_task_list_uses_project_name_not_project():
    """task list should use --project-name to avoid collision with global -p."""
    result = subprocess.run(
        [sys.executable, "-m", "zad_cli", "task", "list", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "--project-name" in result.stdout


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
        result = subprocess.run(
            [sys.executable, "-m", "zad_cli", cmd, "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"{cmd} --help failed: {result.stderr}"
