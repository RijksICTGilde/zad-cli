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


def strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def extract_commands(help_output: str) -> set[str]:
    """Extract command names from Typer --help output.

    Parses the 'Commands' section structurally instead of using substring
    matching, which could give false positives (e.g. 'list' matching
    'Listing all deployments' in a description).

    Typer/Rich outputs panels like:
        ╭─ Commands ─────────────╮
        │ logs     View logs...  │
        │ config   Manage ...    │
        ╰────────────────────────╯
    """
    lines = help_output.split("\n")
    in_commands = False
    commands = set()
    for line in lines:
        stripped = line.strip()
        # Typer outputs "╭─ Commands ─╮" as the panel header
        if re.search(r"\bCommands\b", stripped):
            in_commands = True
            continue
        if in_commands:
            # End of panel
            if stripped.startswith("╰") or not stripped:
                if commands:
                    break
                continue
            # Strip Rich panel borders: "│ command-name  Description │"
            inner = stripped.strip("│").strip()
            if not inner:
                continue
            parts = inner.split()
            if parts and not parts[0].startswith("─"):
                commands.add(parts[0])
    return commands


def run_help(*args: str) -> subprocess.CompletedProcess:
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
        result = run_help(*args)
        prefix = "zad " + group if group else "zad"
        assert result.returncode == 0, f"{prefix} --help failed: {result.stderr}"
        out = strip_ansi(result.stdout)
        actual_commands = extract_commands(out)
        assert actual_commands, f"Could not parse any commands from '{prefix} --help' output"
        for cmd in commands:
            assert cmd in actual_commands, (
                f"Command '{cmd}' missing from '{prefix}' commands: {sorted(actual_commands)}. "
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


# Minimum required positional parameters (excluding self) for each method.
# Changing these would break callers that pass arguments positionally.
EXPECTED_METHOD_MIN_ARGS: dict[str, int] = {
    "add_component": 2,
    "add_component_to_deployment": 3,
    "add_service": 2,
    "backup_bucket": 2,
    "backup_database": 2,
    "backup_namespace": 1,
    "backup_project": 2,
    "backup_status": 0,
    "cancel_task": 1,
    "check_subdomain": 2,
    "clone_bucket": 3,
    "clone_database": 3,
    "close": 0,
    "delete_component": 2,
    "delete_deployment": 2,
    "delete_project": 1,
    "delete_snapshot": 3,
    "describe_deployment": 2,
    "get_logs": 1,
    "get_task": 1,
    "health": 0,
    "list_backup_runs": 2,
    "list_deployments": 1,
    "list_projects": 0,
    "list_snapshots": 2,
    "list_subdomains": 0,
    "list_tasks": 0,
    "metrics_cpu": 0,
    "metrics_memory": 0,
    "metrics_network": 0,
    "metrics_overview": 0,
    "metrics_pods": 0,
    "metrics_query": 1,
    "project_status": 1,
    "refresh_deployment": 2,
    "refresh_project": 1,
    "remove_service": 2,
    "resolve_namespace": 2,
    "restore_backup_run": 3,
    "restore_bucket": 3,
    "restore_database": 3,
    "restore_project": 1,
    "restore_pvc": 3,
    "sanitize": 1,
    "tune_resources": 1,
    "update_image": 4,
    "upsert_deployment": 2,
    "validate_clone": 2,
    "wait_for_task": 1,
}


def test_client_method_signatures_not_broken():
    """Method signatures must not lose required positional parameters."""
    from zad_cli.api.client import ZadClient

    for method_name, expected_min in EXPECTED_METHOD_MIN_ARGS.items():
        method = getattr(ZadClient, method_name, None)
        if method is None:
            continue  # Covered by test_client_public_methods_not_removed
        sig = inspect.signature(method)
        # Count parameters that are positional (no default) excluding 'self'
        required_positional = sum(
            1
            for p in sig.parameters.values()
            if p.name != "self"
            and p.default is inspect.Parameter.empty
            and p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
        )
        assert required_positional >= expected_min, (
            f"Method '{method_name}' now requires {required_positional} positional args, "
            f"expected at least {expected_min}. Reducing required args may indicate a "
            f"backwards-incompatible signature change."
        )
