"""`zad service` and `zad service config`, driven by the bundled catalog snapshot."""

from __future__ import annotations

import json

import httpx
import pytest
import respx
from typer.testing import CliRunner

from zad_cli.cli import app

API = "https://api.example.com"
runner = CliRunner()


@pytest.fixture(autouse=True)
def _credentials(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ZAD_API_KEY", "test-key")
    monkeypatch.setenv("ZAD_PROJECT_ID", "my-project")
    monkeypatch.setenv("ZAD_API_URL", API)
    yield


def run(*args: str):
    return runner.invoke(app, list(args))


# --- Catalog ---


def test_service_list_comes_from_the_catalog():
    result = run("-o", "json", "service", "list")
    assert result.exit_code == 0, result.output
    names = {entry["name"] for entry in json.loads(result.stdout)}
    assert "postgresql-database" in names
    assert len(names) >= 15


def test_hidden_services_need_all():
    plain = {e["name"] for e in json.loads(run("-o", "json", "service", "list").stdout)}
    everything = {e["name"] for e in json.loads(run("-o", "json", "service", "list", "--all").stdout)}
    assert plain < everything


def test_types_is_an_alias_of_list():
    assert run("-o", "json", "service", "types").stdout == run("-o", "json", "service", "list").stdout


def test_describe_reports_the_layers_a_service_accepts():
    result = run("-o", "json", "service", "describe", "postgresql-database")
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["targets"] == ["project"]


def test_unknown_service_names_the_valid_ones():
    result = run("service", "describe", "postgres")
    assert result.exit_code != 0
    assert "postgresql-database" in result.output


# --- Layer selection ---


def test_one_layer_means_target_is_optional():
    result = run(
        "-o", "json", "service", "config", "set", "postgresql-database", "--set", "scope=project", "--dry-run", "-y"
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["endpoint"] == (
        "/v2/projects/my-project/services/postgresql-database/config/project"
    )


def test_more_than_one_layer_refuses_to_guess():
    """cross-domain-access takes project and deployment; picking one silently is wrong."""
    result = run("service", "config", "set", "cross-domain-access", "--set", "a=b", "--dry-run", "-y")
    assert result.exit_code != 0
    assert "--target" in result.output


def test_explicit_target_resolves_the_deployment_layer():
    result = run(
        "-o",
        "json",
        "service",
        "config",
        "set",
        "cross-domain-access",
        "--target",
        "deployment",
        "--deployment",
        "prod",
        "--set",
        "outbound[0].name=database",
        "--dry-run",
        "-y",
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["endpoint"] == (
        "/v2/projects/my-project/services/cross-domain-access/config/deployment/prod"
    )


def test_a_layer_the_service_does_not_have_is_rejected():
    result = run("service", "config", "set", "postgresql-database", "--target", "component", "--set", "a=b", "-y")
    assert result.exit_code != 0
    assert "project" in result.output


def test_component_layer_without_a_component_says_so():
    result = run("service", "config", "set", "publish-on-web", "--set", "a=b", "--dry-run", "-y")
    assert result.exit_code != 0
    assert "--component" in result.output


# --- Bodies ---


def test_a_body_can_come_from_a_manifest(tmp_path):
    manifest = tmp_path / "pg.yaml"
    manifest.write_text("scope: project\n")
    result = run("service", "config", "set", "postgresql-database", "-f", str(manifest), "--dry-run", "-y")
    assert result.exit_code == 0, result.output
    assert "project" in result.output


def test_set_overrides_the_manifest(tmp_path):
    manifest = tmp_path / "pg.yaml"
    manifest.write_text("scope: shared\n")
    result = run(
        "-o",
        "json",
        "service",
        "config",
        "set",
        "postgresql-database",
        "-f",
        str(manifest),
        "--set",
        "scope=project",
        "--dry-run",
        "-y",
    )
    assert json.loads(result.stdout)["payload"]["scope"] == "project"


def test_nothing_to_send_is_an_error():
    result = run("service", "config", "set", "postgresql-database", "--dry-run", "-y")
    assert result.exit_code != 0
    assert "--set" in result.output


def test_an_invalid_value_is_caught_before_the_request_leaves():
    """`scope` is an enum in the spec; a typo should not cost a round trip."""
    result = run("service", "config", "set", "postgresql-database", "--set", "scope=namespace", "--dry-run", "-y")
    assert result.exit_code != 0
    assert "shared" in result.output


def test_schema_prints_the_json_schema():
    result = run("-o", "json", "service", "config", "schema", "postgresql-database")
    assert result.exit_code == 0, result.output
    assert "scope" in result.stdout
    # A $ref would leave the reader chasing definitions that are not in the output.
    assert "$ref" not in result.stdout


def test_generate_skeleton_prints_an_example_body():
    result = run("-o", "json", "service", "config", "set", "postgresql-database", "--generate-skeleton")
    assert result.exit_code == 0, result.output
    assert "scope" in json.loads(result.stdout)


# --- Requests ---


@respx.mock
def test_config_set_puts_to_the_layer_endpoint():
    route = respx.put(f"{API}/v2/projects/my-project/services/postgresql-database/config/project").mock(
        return_value=httpx.Response(200, json={"status": "ok"})
    )
    result = run("service", "config", "set", "postgresql-database", "--set", "scope=project", "-y")
    assert result.exit_code == 0, result.output
    assert json.loads(route.calls[0].request.content) == {"scope": "project"}


@respx.mock
def test_config_clear_deletes_the_layer_endpoint():
    route = respx.delete(f"{API}/v2/projects/my-project/services/publish-on-web/config/component/web").mock(
        return_value=httpx.Response(200, json={"status": "ok"})
    )
    result = run("service", "config", "clear", "publish-on-web", "--component", "web", "-y")
    assert result.exit_code == 0, result.output
    assert route.call_count == 1


@respx.mock
def test_no_rollout_defers_and_says_what_is_waiting():
    respx.put(f"{API}/v2/projects/my-project/services/postgresql-database/config/project").mock(
        return_value=httpx.Response(200, json={"status": "ok"})
    )
    respx.get(f"{API}/v2/projects/my-project/pending-rollout").mock(
        return_value=httpx.Response(200, json={"project": "my-project", "count": 2})
    )
    result = run("--no-rollout", "service", "config", "set", "postgresql-database", "--set", "scope=project", "-y")
    assert result.exit_code == 0, result.output
    assert "2 change(s) waiting" in result.output
    assert "zad project refresh" in result.output


@respx.mock
def test_config_get_reads_every_layer():
    respx.get(f"{API}/v2/projects/my-project/services/postgresql-database/config").mock(
        return_value=httpx.Response(200, json={"project": {"scope": "shared"}})
    )
    result = run("-o", "json", "service", "config", "get", "postgresql-database")
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {"project": {"scope": "shared"}}


@respx.mock
def test_project_pending_reports_the_count():
    respx.get(f"{API}/v2/projects/my-project/pending-rollout").mock(
        return_value=httpx.Response(
            200, json={"project": "my-project", "count": 3, "task_types": ["configure_service"]}
        )
    )
    result = run("-o", "json", "project", "pending")
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["count"] == 3


def test_schema_can_be_written_for_an_editor(tmp_path):
    """A manifest with a $schema modeline gets completion and validation as you type."""
    target = tmp_path / "nested" / "pg.json"
    result = run("service", "config", "schema", "postgresql-database", "--write", str(target))
    assert result.exit_code == 0, result.output
    written = json.loads(target.read_text())
    assert written["$schema"].startswith("https://json-schema.org/")
    assert "scope" in json.dumps(written)
    assert "yaml-language-server" in result.output
