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
    assert "deploy" in result.stdout
    assert "delete" in result.stdout
    assert "create" in result.stdout


def test_deploy_requires_project_and_api_key():
    result = subprocess.run(
        [sys.executable, "-m", "zad_cli", "project", "deploy", "-d", "test"],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin"},
    )
    assert result.returncode != 0
    assert "ZAD_PROJECT_ID" in result.stderr or "ZAD_API_KEY" in result.stderr


def test_all_subcommands_have_help():
    """Verify every sub-command group responds to --help."""
    subcommands = [
        "config",
        "project",
        "deployment",
        "backup",
        "restore",
        "clone",
        "logs",
        "metrics",
        "invite",
    ]
    for cmd in subcommands:
        result = subprocess.run(
            [sys.executable, "-m", "zad_cli", cmd, "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"{cmd} --help failed: {result.stderr}"
