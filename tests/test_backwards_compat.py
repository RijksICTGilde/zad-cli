"""Compatibility tests.

These guard against accidental removal of CLI commands or client methods. Adding is
always fine; removing fails CI. Since 1.0 the policy is "additive within a major": a
removal is allowed in a major release and shows up here as a deliberate edit to the
baseline, with a note saying what replaced it. See CLAUDE.md, "Compatibility policy".

Removed on 11 August 2026, all for the same reason: they called endpoints that do not
exist. `scripts/check_coverage.py` now asks that question from both sides, so a command
pointing at nothing fails the check instead of failing in someone's terminal.

- `zad metrics` (health, overview, cpu, memory, pods, network, query), and the client
  methods behind them. `/api/metrics/*` is absent from the spec and answers 404 on the
  sandbox and on production. Nothing replaces it: cluster metrics are not a project
  operation, and `metrics-scraper` (a service you configure on a component) is a different
  thing that happens to share the word.
- `zad backup namespace|database|bucket` and their client methods. Also absent from the
  spec, also 404. `zad backup create` covers backing up a deployment and does work.
- `ZadClient.list_projects` and `ZadClient.remove_service`: no command reached them, and
  their endpoints are gone. `list_projects_sso` and `zad service config clear` replace them.

Removed on 13 August 2026: `zad project list --show-keys`, and with it every trace of an
API key in that command's answer. Not masked, not "yes/no": the rows are built from name,
role and description only, in every output format, so `-o json` is not a way around it. One
command that can put every key you hold into a screen or a transcript is one command too
many, and the caller is as often a script or an agent as a person. `zad project use <name>`
stores the key where the CLI needs it. `credentials.redact` now returns `(set)` rather than
the first four and last two characters, everywhere it is used.

Changed on 12 August 2026, and this one breaks callers on purpose: `restore_project`,
`restore_database` and `restore_bucket` gained a required `payload` argument, and their
commands gained required options. All three endpoints declare a required request body that
we never sent, so every call returned 422 and none of them has ever worked. There is no
compatible version to preserve. The check below only guards against *losing* required
arguments, so it stays green; the note is here because that is the whole point of the file.

`zad component delete` was kept through a window where the API had no DELETE on a component
and the command refused locally. That endpoint landed on 11 August, so it does the real
thing again. Keeping it beat removing it: the gap was upstream and closed within a day.
"""

import inspect
import os
import re
import subprocess
import sys
import tempfile

# A throwaway HOME: conftest isolates the credentials store for in-process tests, but a
# subprocess gets none of that and would read the developer's own ~/.config/zad. That made
# the suite depend on whoever ran it: a machine with an active project stored took a
# different branch than a clean checkout.
_ISOLATED_HOME = tempfile.mkdtemp(prefix="zad-test-home-")
_PLAIN_ENV = {**os.environ, "HOME": _ISOLATED_HOME, "NO_COLOR": "1", "TERM": "dumb", "ZAD_CATALOG_OFFLINE": "1"}
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


# Panels that list options rather than commands. Everything else is a command panel:
# since 1.0 the root help groups its 20-odd command groups under names of its own
# ("Services and configuration", …), so matching only a panel called "Commands" would
# find nothing.
_OPTION_PANELS = re.compile(r"\bOptions\b|\bArguments\b")


def extract_commands(help_output: str) -> set[str]:
    """Extract command names from Typer --help output.

    Parses the panels structurally instead of matching substrings, which could give
    false positives (e.g. 'list' matching 'Listing all deployments' in a description).

    Typer/Rich outputs panels like:
        ╭─ Commands ─────────────╮
        │ logs     View logs...  │
        │ config   Manage ...    │
        ╰────────────────────────╯
    """
    commands: set[str] = set()
    in_commands = False
    for line in help_output.split("\n"):
        stripped = line.strip()
        if stripped.startswith("╭"):
            # A new panel: a command panel unless its title says otherwise.
            in_commands = not _OPTION_PANELS.search(stripped)
            continue
        if stripped.startswith("╰"):
            in_commands = False
            continue
        if not in_commands:
            continue
        if not stripped.startswith("│"):
            continue
        # Strip Rich panel borders, keeping the leading padding: a wrapped description
        # line is indented under the name column, so only an entry's first line has a
        # name in that column.
        inner = stripped.strip("│").rstrip()
        if not inner.startswith(" ") or not inner.strip():
            continue
        if inner[1:2] == " ":
            continue  # indented: a continuation of the previous entry's description
        commands.add(inner.strip().split()[0])
    return commands


def run_help(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "zad_cli", *args, "--help"],
        capture_output=True,
        text=True,
        env=_PLAIN_ENV,
        cwd=_ISOLATED_HOME,
    )


# Every command group and its expected subcommands.
# New commands appearing in --help is fine. Commands disappearing from this
# dict means a backwards-incompatible removal.
EXPECTED_COMMANDS: dict[str, list[str]] = {
    "": [
        "config",
        "login",
        "logout",
        "project",
        "attachment",
        "env",
        "alias",
        "db",
        "registry",
        "deployment",
        "component",
        "service",
        "resource",
        "task",
        "backup",
        "restore",
        "clone",
        "logs",
        "open",
        "admin",
        "version",
    ],
    "project": [
        "list",
        "create",
        "use",
        "select",
        "status",
        "refresh",
        "pending",
        "delete",
        "subdomains",
        "check-subdomain",
    ],
    "deployment": ["list", "describe", "create", "update-image", "refresh", "delete"],
    "component": ["list", "add", "assign", "update", "delete"],
    # 1.0: `service add` and `service delete` were withdrawn with the endpoints behind
    # them; configuration is now written per layer. See CLAUDE.md, "Compatibility policy".
    "service": ["types", "list", "describe", "config"],
    "resource": ["tune", "sanitize"],
    "task": ["wait", "status", "list", "cancel"],
    "backup": ["create", "list", "status", "delete"],
    "restore": ["list", "project", "backup", "pvc", "database", "bucket", "deployment", "pvc-snapshots"],
    "clone": ["database", "bucket", "check"],
    "config": ["init", "set", "get", "list", "path"],
    "open": ["project", "portal", "domains"],
    "admin": ["list", "delete", "orphan-report", "orphan-confirm", "cleanup", "reconcile"],
    "service config": ["get", "set", "clear", "schema"],
    "attachment": ["list", "add", "assign", "update", "delete"],
    "env": ["list", "get", "add", "set", "unset", "clear"],
    "alias": ["list", "get", "add", "set", "unset", "clear"],
    "db": ["schema"],
    "db schema": ["list", "add", "remove"],
    "registry": ["add"],
}

# Removed in 1.0, with what replaced them. Listed rather than deleted silently, so the
# next person reading this file can tell a deliberate removal from an accident.
REMOVED_IN_1_0: dict[str, str] = {
    "service add": "the endpoint is deprecated upstream; use `service config set`",
    "service delete": "the endpoint was withdrawn upstream; use `service config clear`",
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
    "confirm_orphans",
    "delete_admin_mark",
    "get_orphan_report",
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
    "get_deployment_v2",
    "get_logs",
    "get_task",
    "list_backup_runs",
    "list_deployments",
    "list_deployments_v2",
    "list_projects_sso",
    "create_project_sso",
    "get_service_config",
    "put_service_config",
    "delete_service_config",
    "add_service_values",
    "change_service_values",
    "clear_service_values",
    "remove_service_values",
    "remove_service_value",
    "pending_rollout",
    "create_attachment",
    "update_attachment",
    "delete_attachment",
    "assign_attachment",
    "list_database_schemas",
    "add_database_schema",
    "remove_database_schema",
    "add_registry_by_credentials",
    "add_registry_by_secret",
    "trigger_cleanup",
    "trigger_reconciliation",
    "reconcile_projects",
    "server_version",
    "list_admin_marked",
    "list_pvc_snapshots",
    "list_snapshots",
    "list_subdomains",
    "list_tasks",
    "project_status",
    "refresh_deployment",
    "refresh_project",
    "resolve_namespace",
    "restore_backup_run",
    "restore_bucket",
    "restore_deployment_resource",
    "restore_database",
    "restore_project",
    "restore_pvc",
    "sanitize",
    "tune_resources",
    "update_component",
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
    "confirm_orphans": 1,
    "delete_admin_mark": 1,
    "get_orphan_report": 0,
    "list_admin_marked": 0,
    "list_pvc_snapshots": 3,
    "restore_deployment_resource": 3,
    "add_component_to_deployment": 3,
    "add_service": 2,
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
    "get_deployment_v2": 2,
    "get_logs": 1,
    "get_task": 1,
    "list_backup_runs": 2,
    "list_deployments": 1,
    "list_deployments_v2": 1,
    "list_projects_sso": 1,
    "create_project_sso": 2,
    "get_service_config": 2,
    "put_service_config": 2,
    "delete_service_config": 1,
    "add_service_values": 2,
    "change_service_values": 2,
    "clear_service_values": 1,
    "remove_service_values": 2,
    "remove_service_value": 2,
    "pending_rollout": 1,
    "create_attachment": 4,
    "update_attachment": 4,
    "delete_attachment": 2,
    "assign_attachment": 4,
    "list_database_schemas": 1,
    "add_database_schema": 2,
    "remove_database_schema": 2,
    "add_registry_by_credentials": 2,
    "add_registry_by_secret": 2,
    "trigger_cleanup": 1,
    "trigger_reconciliation": 0,
    "reconcile_projects": 0,
    "server_version": 0,
    "list_snapshots": 2,
    "list_subdomains": 0,
    "list_tasks": 0,
    "project_status": 1,
    "refresh_deployment": 2,
    "refresh_project": 1,
    "resolve_namespace": 2,
    "restore_backup_run": 3,
    "restore_bucket": 3,
    "restore_database": 3,
    "restore_project": 1,
    "restore_pvc": 3,
    "sanitize": 1,
    "tune_resources": 1,
    "update_component": 3,
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


def test_removed_commands_are_really_gone():
    """A removal must be complete: a command left half-registered is worse than either."""
    for removed in REMOVED_IN_1_0:
        group, _, command = removed.rpartition(" ")
        result = run_help(*group.split())
        assert result.returncode == 0, f"zad {group} --help failed: {result.stderr}"
        assert command not in extract_commands(strip_ansi(result.stdout)), (
            f"'{removed}' was removed in 1.0 ({REMOVED_IN_1_0[removed]}) but still appears in --help."
        )
