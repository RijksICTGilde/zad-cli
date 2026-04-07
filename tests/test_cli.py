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
        [sys.executable, "-m", "zad_cli", "--version"],
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


def test_config_init_preserves_non_zad_vars(tmp_path):
    """config init should preserve non-ZAD variables, comments, and blank lines."""
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# Database config\nDATABASE_URL=postgres://localhost/mydb\n\nSENTRY_DSN=https://sentry.io/123\n"
    )

    clean_env = {k: v for k, v in _PLAIN_ENV.items() if not k.startswith("ZAD_")}
    result = subprocess.run(
        [sys.executable, "-m", "zad_cli", "config", "init"],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        env=clean_env,
        # y (confirm update) + default url (Enter) + api key + project id
        input="y\n\nmy-new-key\nmy-project\n",
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"

    content = env_file.read_text()
    assert "DATABASE_URL=postgres://localhost/mydb" in content
    assert "SENTRY_DSN=https://sentry.io/123" in content
    assert "# Database config" in content
    assert "ZAD_API_KEY=my-new-key" in content
    assert "ZAD_PROJECT_ID=my-project" in content


def test_config_init_clears_project_id_with_dash(tmp_path):
    """config init should remove ZAD_PROJECT_ID when user enters '-'."""
    env_file = tmp_path / ".env"
    env_file.write_text("ZAD_API_KEY=old-key\nZAD_PROJECT_ID=old-project\n")

    clean_env = {k: v for k, v in _PLAIN_ENV.items() if not k.startswith("ZAD_")}
    result = subprocess.run(
        [sys.executable, "-m", "zad_cli", "config", "init"],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        env=clean_env,
        # y (confirm) + default url (Enter) + accept masked key (Enter) + '-' to clear project
        input="y\n\n\n-\n",
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"

    content = env_file.read_text()
    assert "ZAD_API_KEY=old-key" in content
    assert "ZAD_PROJECT_ID" not in content


def test_config_init_creates_new_env(tmp_path):
    """config init should create a new .env when none exists."""
    clean_env = {k: v for k, v in _PLAIN_ENV.items() if not k.startswith("ZAD_")}
    result = subprocess.run(
        [sys.executable, "-m", "zad_cli", "config", "init"],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        env=clean_env,
        # No confirmation needed (file doesn't exist) + default url + key + '-' default for project (accept)
        input="\ntest-api-key\ntest-project\n",
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"

    env_file = tmp_path / ".env"
    assert env_file.exists()
    content = env_file.read_text()
    assert "ZAD_API_KEY" in content
    assert "test-api-key" in content
    assert "ZAD_PROJECT_ID" in content
    assert "test-project" in content
    # Default URL should NOT be written
    assert "ZAD_API_URL" not in content


def test_config_init_removes_custom_url_when_set_to_default(tmp_path):
    """config init should remove ZAD_API_URL when user resets it to the default."""
    env_file = tmp_path / ".env"
    env_file.write_text("ZAD_API_KEY=my-key\nZAD_API_URL=https://custom.example.com\nZAD_PROJECT_ID=proj\n")

    from zad_cli.settings import DEFAULT_API_URL

    clean_env = {k: v for k, v in _PLAIN_ENV.items() if not k.startswith("ZAD_")}
    result = subprocess.run(
        [sys.executable, "-m", "zad_cli", "config", "init"],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        env=clean_env,
        # y (confirm) + type default url explicitly + accept masked key + accept project
        input=f"y\n{DEFAULT_API_URL}\n\n\n",
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"

    content = env_file.read_text()
    assert "ZAD_API_URL" not in content
    assert "ZAD_API_KEY" in content
    assert "ZAD_PROJECT_ID" in content


def test_dotenv_loaded_from_cwd(tmp_path):
    """'.env' in the user's CWD should be loaded even when zad is installed elsewhere."""
    env_file = tmp_path / ".env"
    env_file.write_text("ZAD_API_KEY=test-key-from-cwd\nZAD_PROJECT_ID=test-proj\n")
    # Remove ZAD vars from env so load_dotenv can set them from .env
    clean_env = {k: v for k, v in _PLAIN_ENV.items() if not k.startswith("ZAD_")}
    result = subprocess.run(
        [sys.executable, "-m", "zad_cli", "project", "status"],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        env=clean_env,
    )
    err = _strip_ansi(result.stderr)
    # Should NOT complain about missing project - it should read it from .env
    assert "project is required" not in err
