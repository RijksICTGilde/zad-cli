"""`zad db schema`, `zad admin cleanup|reconcile`, `zad registry add`, `zad version`."""

from __future__ import annotations

import json

import httpx
import pytest
import respx
from typer.testing import CliRunner

from zad_cli.cli import app

API = "https://api.example.com"
SCHEMAS = f"{API}/v2/projects/my-project/services/postgresql-database/schemas"

runner = CliRunner()


@pytest.fixture(autouse=True)
def _credentials(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ZAD_API_KEY", "test-key")
    monkeypatch.setenv("ZAD_PROJECT_ID", "my-project")
    monkeypatch.setenv("ZAD_API_URL", API)
    yield


def run(*args: str):
    return runner.invoke(app, list(args))


def _ok():
    return httpx.Response(200, json={"status": "ok"})


# --- Database schemas ---


@respx.mock
def test_schema_list():
    respx.get(SCHEMAS).mock(
        return_value=httpx.Response(200, json={"schemas": [{"postfix": "reporting", "description": "d"}]})
    )
    result = run("-o", "json", "db", "schema", "list")
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)[0]["postfix"] == "reporting"


@respx.mock
def test_schema_add():
    route = respx.post(SCHEMAS).mock(return_value=_ok())
    result = run("db", "schema", "add", "reporting", "--description", "read models", "-y")
    assert result.exit_code == 0, result.output
    assert json.loads(route.calls[0].request.content) == {"postfix": "reporting", "description": "read models"}


@respx.mock
def test_schema_remove_can_forget_without_dropping():
    route = respx.delete(f"{SCHEMAS}/reporting").mock(return_value=_ok())
    result = run("db", "schema", "remove", "reporting", "--forget", "-y")
    assert result.exit_code == 0, result.output
    assert route.calls[0].request.url.params["forget"] == "true"


def test_schema_add_dry_run_shows_the_endpoint():
    result = run("-o", "json", "db", "schema", "add", "reporting", "--dry-run", "-y")
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["endpoint"].endswith("/postgresql-database/schemas")


# --- Admin ---


@respx.mock
def test_cleanup_is_a_dry_run_unless_apply_is_given():
    route = respx.post(f"{API}/v2/admin/cleanup/trigger").mock(return_value=httpx.Response(200, json={"purged": 0}))
    result = run("admin", "cleanup")
    assert result.exit_code == 0, result.output
    assert route.calls[0].request.url.params["dry_run"] == "true"
    assert "nothing was purged" in result.output


@respx.mock
def test_cleanup_with_apply_actually_purges():
    route = respx.post(f"{API}/v2/admin/cleanup/trigger").mock(return_value=httpx.Response(200, json={"purged": 2}))
    result = run("admin", "cleanup", "--apply", "--project-name", "p", "-y")
    assert result.exit_code == 0, result.output
    params = route.calls[0].request.url.params
    assert params["dry_run"] == "false"
    assert params["project_name"] == "p"


@respx.mock
def test_reconcile_runs_the_full_pass_by_default():
    route = respx.post(f"{API}/v2/admin/reconciliation/trigger").mock(
        return_value=httpx.Response(200, json={"unmarked": 0})
    )
    result = run("admin", "reconcile")
    assert result.exit_code == 0, result.output
    assert route.calls[0].request.url.params["dry_run"] == "true"


@respx.mock
def test_reconcile_projects_only_rereads_the_repo():
    route = respx.post(f"{API}/v2/admin/projects/:reconcile").mock(return_value=httpx.Response(200, json={"ok": True}))
    result = run("admin", "reconcile", "--projects")
    assert result.exit_code == 0, result.output
    assert route.call_count == 1


# --- Registries ---


@respx.mock
def test_registry_add_by_credentials():
    route = respx.post(f"{API}/projects/my-project/registries/by-credentials").mock(return_value=_ok())
    result = run("registry", "add", "ghcr", "--url", "ghcr.io/org", "--username", "bot", "--password", "s3cr3t", "-y")
    assert result.exit_code == 0, result.output
    assert json.loads(route.calls[0].request.content)["password"] == "s3cr3t"


@respx.mock
def test_registry_add_by_secret():
    route = respx.post(f"{API}/projects/my-project/registries/by-secret").mock(return_value=_ok())
    result = run("registry", "add", "ghcr", "--url", "ghcr.io/org", "--secret-name", "pull-secret", "-y")
    assert result.exit_code == 0, result.output
    assert json.loads(route.calls[0].request.content)["secretName"] == "pull-secret"


def test_registry_add_refuses_both_shapes_at_once():
    result = run(
        "registry", "add", "ghcr", "--url", "u", "--username", "b", "--password", "p", "--secret-name", "s", "-y"
    )
    assert result.exit_code != 0


def test_registry_add_needs_one_of_the_two_shapes():
    result = run("registry", "add", "ghcr", "--url", "u", "-y")
    assert result.exit_code != 0


def test_registry_password_can_come_from_a_file(tmp_path):
    token = tmp_path / "token.txt"
    token.write_text("s3cr3t")
    result = run(
        "-o",
        "json",
        "registry",
        "add",
        "ghcr",
        "--url",
        "u",
        "--username",
        "b",
        "--password",
        f"@{token}",
        "--dry-run",
        "-y",
    )
    assert result.exit_code == 0, result.output
    # A dry run shows the shape of the request, never the secret in it.
    assert "s3cr3t" not in result.stdout


# --- Version ---


@respx.mock
def test_version_reports_both_sides():
    respx.get(f"{API}/version").mock(return_value=httpx.Response(200, json={"name": "ZAD", "version": "abc1234"}))
    result = run("-o", "json", "version")
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["zad_cli"]
    assert payload["server"]["version"] == "abc1234"


@respx.mock
def test_an_unreachable_server_still_reports_the_cli_version():
    respx.get(f"{API}/version").mock(side_effect=httpx.ConnectError("down"))
    result = run("-o", "json", "version")
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["zad_cli"]
    assert "error" in payload["server"]
