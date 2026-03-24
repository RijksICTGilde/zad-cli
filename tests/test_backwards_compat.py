"""Backwards compatibility tests.

These tests guard against accidental removal of CLI commands or client methods.
Adding new commands/methods is fine; removing existing ones fails CI.
See CLAUDE.md "Backwards Compatibility Policy" for rationale.
"""

import inspect
import os
import re
import subprocess
import sys

_PLAIN_ENV = {**os.environ, "NO_COLOR": "1", "TERM": "dumb"}
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def _run_help(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "zad_cli", *args, "--help"],
        capture_output=True,
        text=True,
        env=_PLAIN_ENV,
    )


# Every command group and its expected subcommands.
# New commands appearing in --help is fine. Commands disappearing from this
# dict means a backwards-incompatible removal.
EXPECTED_COMMANDS: dict[str, list[str]] = {
    "": [
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
        "version",
    ],
    "project": ["list", "status", "refresh", "delete", "subdomains", "check-subdomain"],
    "deployment": ["list", "describe", "create", "update-image", "refresh", "delete"],
    "component": ["list", "add", "assign", "delete"],
    "service": ["types", "add", "delete"],
    "resource": ["tune", "sanitize"],
    "task": ["wait", "status", "list", "cancel"],
    "backup": ["create", "list", "status", "delete", "namespace", "database", "bucket"],
    "restore": ["list", "project", "backup", "pvc", "database", "bucket"],
    "clone": ["database", "bucket", "check"],
    "metrics": ["health", "overview", "cpu", "memory", "pods", "network", "query"],
    "config": ["init", "set", "get", "list", "path"],
    "open": ["project", "portal", "domains"],
}


def test_cli_commands_not_removed():
    """Every command listed in EXPECTED_COMMANDS must still appear in --help."""
    for group, commands in EXPECTED_COMMANDS.items():
        args = group.split() if group else []
        result = _run_help(*args)
        assert result.returncode == 0, f"{'zad ' + group if group else 'zad'} --help failed: {result.stderr}"
        out = _strip_ansi(result.stdout)
        for cmd in commands:
            assert cmd in out, (
                f"Command '{cmd}' missing from '{'zad ' + group if group else 'zad'}' --help output. "
                f"Removing commands is a backwards-incompatible change."
            )


# Every public method on ZadClient that external code may depend on.
EXPECTED_CLIENT_METHODS: list[str] = [
    "add_component",
    "add_component_to_deployment",
    "add_service",
    "backup_bucket",
    "backup_database",
    "backup_namespace",
    "backup_project",
    "backup_status",
    "cancel_task",
    "check_subdomain",
    "clone_bucket",
    "clone_database",
    "close",
    "delete_component",
    "delete_deployment",
    "delete_project",
    "delete_snapshot",
    "describe_deployment",
    "get_logs",
    "get_task",
    "health",
    "list_backup_runs",
    "list_deployments",
    "list_projects",
    "list_snapshots",
    "list_subdomains",
    "list_tasks",
    "metrics_cpu",
    "metrics_memory",
    "metrics_network",
    "metrics_overview",
    "metrics_pods",
    "metrics_query",
    "project_status",
    "refresh_deployment",
    "refresh_project",
    "remove_service",
    "resolve_namespace",
    "restore_backup_run",
    "restore_bucket",
    "restore_database",
    "restore_project",
    "restore_pvc",
    "sanitize",
    "tune_resources",
    "update_image",
    "upsert_deployment",
    "validate_clone",
    "wait_for_task",
]


def test_client_public_methods_not_removed():
    """Every method in EXPECTED_CLIENT_METHODS must still exist on ZadClient."""
    from zad_cli.api.client import ZadClient

    actual_methods = {
        name for name, _ in inspect.getmembers(ZadClient, predicate=inspect.isfunction) if not name.startswith("_")
    }

    for method in EXPECTED_CLIENT_METHODS:
        assert method in actual_methods, (
            f"Method '{method}' missing from ZadClient. Removing public methods is a backwards-incompatible change."
        )
