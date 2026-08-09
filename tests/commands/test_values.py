"""`zad env` and `zad alias`: the four value verbs, and the two layers they act on."""

from __future__ import annotations

import json

import httpx
import pytest
import respx
from typer.testing import CliRunner

from zad_cli.cli import app
from zad_cli.commands.values import extract_values, read_env_file

API = "https://api.example.com"
ENV_BASE = f"{API}/v2/projects/my-project/services/user-env-vars/values/component/web"
ENV_DEPLOYMENT_BASE = f"{API}/v2/projects/my-project/services/user-env-vars/values/deployment/prod/component/web"
ALIAS_BASE = f"{API}/v2/projects/my-project/services/aliases/values/component/web"

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


# --- The four verbs are four endpoints ---


@respx.mock
def test_add_posts():
    route = respx.post(ENV_BASE).mock(return_value=_ok())
    result = run("env", "add", "FEATURE_X=on", "-c", "web", "-y")
    assert result.exit_code == 0, result.output
    assert json.loads(route.calls[0].request.content) == {"values": {"FEATURE_X": "on"}}


@respx.mock
def test_set_patches():
    """set changes what exists; it is not a synonym for add."""
    route = respx.patch(ENV_BASE).mock(return_value=_ok())
    result = run("env", "set", "FEATURE_X=off", "-c", "web", "-y")
    assert result.exit_code == 0, result.output
    assert json.loads(route.calls[0].request.content) == {"values": {"FEATURE_X": "off"}}


@respx.mock
def test_unset_one_key_deletes_that_key():
    route = respx.delete(f"{ENV_BASE}/FEATURE_X").mock(return_value=_ok())
    result = run("env", "unset", "FEATURE_X", "-c", "web", "-y")
    assert result.exit_code == 0, result.output
    assert route.call_count == 1


@respx.mock
def test_unset_several_keys_uses_the_bulk_endpoint():
    route = respx.post(f"{ENV_BASE}/:delete").mock(return_value=_ok())
    result = run("env", "unset", "A", "B", "-c", "web", "-y")
    assert result.exit_code == 0, result.output
    assert json.loads(route.calls[0].request.content) == {"keys": ["A", "B"]}


@respx.mock
def test_clear_deletes_the_whole_layer():
    route = respx.delete(ENV_BASE).mock(return_value=_ok())
    result = run("env", "clear", "-c", "web", "-y")
    assert result.exit_code == 0, result.output
    assert route.call_count == 1


# --- Layers ---


@respx.mock
def test_a_deployment_makes_it_the_more_specific_layer():
    route = respx.post(ENV_DEPLOYMENT_BASE).mock(return_value=_ok())
    result = run("env", "add", "A=1", "-c", "web", "--deployment", "prod", "-y")
    assert result.exit_code == 0, result.output
    assert route.call_count == 1


@respx.mock
def test_alias_uses_the_aliases_service():
    route = respx.post(ALIAS_BASE).mock(return_value=_ok())
    result = run("alias", "add", "POSTGRES_HOST=$DATABASE_SERVER_HOST", "-c", "web", "-y")
    assert result.exit_code == 0, result.output
    assert json.loads(route.calls[0].request.content) == {"values": {"POSTGRES_HOST": "$DATABASE_SERVER_HOST"}}


def test_aliases_have_no_deployment_layer():
    """The catalog says aliases owns values on the component only; --deployment must fail."""
    result = run("alias", "add", "A=1", "-c", "web", "--deployment", "prod", "--dry-run", "-y")
    assert result.exit_code != 0
    assert "deployment-component" in result.output or "component" in result.output


# --- Sources of values ---


@respx.mock
def test_values_can_come_from_an_env_file(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text('# a comment\n\nA=1\nB="two words"\n')
    route = respx.post(ENV_BASE).mock(return_value=_ok())
    result = run("env", "add", "-c", "web", "--env-file", str(env_file), "-y")
    assert result.exit_code == 0, result.output
    assert json.loads(route.calls[0].request.content) == {"values": {"A": "1", "B": "two words"}}


@respx.mock
def test_values_can_come_from_a_yaml_mapping(tmp_path):
    mapping = tmp_path / "vals.yaml"
    mapping.write_text("A: 1\nB: two\n")
    route = respx.post(ENV_BASE).mock(return_value=_ok())
    result = run("env", "add", "-c", "web", "--from-file", str(mapping), "-y")
    assert result.exit_code == 0, result.output
    assert json.loads(route.calls[0].request.content) == {"values": {"A": "1", "B": "two"}}


@respx.mock
def test_an_argument_wins_over_a_file(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("A=from-file\n")
    route = respx.post(ENV_BASE).mock(return_value=_ok())
    run("env", "add", "A=from-flag", "-c", "web", "--env-file", str(env_file), "-y")
    assert json.loads(route.calls[0].request.content) == {"values": {"A": "from-flag"}}


def test_a_value_can_be_read_from_a_file(tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("s3cr3t")
    result = run("-o", "json", "env", "add", f"TOKEN=@{secret}", "-c", "web", "--dry-run", "-y")
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["payload"]["values"]["TOKEN"] == "s3cr3t"


def test_nothing_to_send_is_an_error():
    result = run("env", "add", "-c", "web", "--dry-run", "-y")
    assert result.exit_code != 0


def test_a_pair_without_an_equals_is_rejected():
    result = run("env", "add", "JUSTAKEY", "-c", "web", "--dry-run", "-y")
    assert result.exit_code != 0
    assert "KEY=VALUE" in result.output


def test_env_file_lines_are_reported_by_number(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("A=1\nbroken line\n")
    result = run("env", "add", "-c", "web", "--env-file", str(env_file), "--dry-run", "-y")
    assert result.exit_code != 0
    assert ":2:" in result.output


def test_read_env_file_ignores_comments_and_blanks(tmp_path):
    path = tmp_path / ".env"
    path.write_text("\n# comment\nA=1\n\n  B = 2 \n")
    assert read_env_file(str(path)) == {"A": "1", "B": "2"}


# --- Reading ---


@respx.mock
def test_list_extracts_the_component_layer():
    respx.get(f"{API}/v2/projects/my-project/services/user-env-vars/config").mock(
        return_value=httpx.Response(200, json={"components": {"web": {"A": "1", "B": "2"}}})
    )
    result = run("-o", "json", "env", "list", "-c", "web")
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {"A": "1", "B": "2"}


@respx.mock
def test_get_prints_one_value():
    respx.get(f"{API}/v2/projects/my-project/services/user-env-vars/config").mock(
        return_value=httpx.Response(200, json={"components": {"web": {"A": "1"}}})
    )
    result = run("env", "get", "A", "-c", "web")
    assert result.exit_code == 0, result.output
    assert result.stdout.strip() == "1"


@respx.mock
def test_get_of_an_unset_key_fails_rather_than_printing_nothing():
    respx.get(f"{API}/v2/projects/my-project/services/user-env-vars/config").mock(
        return_value=httpx.Response(200, json={"components": {"web": {"A": "1"}}})
    )
    result = run("env", "get", "MISSING", "-c", "web")
    assert result.exit_code == 1
    assert "MISSING" in result.output


# --- Extraction ---


def test_extraction_prefers_the_deployment_branch_when_one_is_asked_for():
    document = {
        "components": {"web": {"A": "component"}},
        "deployments": {"prod": {"components": {"web": {"A": "deployment"}}}},
    }
    assert extract_values(document, component="web", deployment="prod") == {"A": "deployment"}


def test_extraction_without_a_deployment_takes_the_component_wide_values():
    document = {
        "components": {"web": {"A": "component"}},
        "deployments": {"prod": {"components": {"web": {"A": "deployment"}}}},
    }
    assert extract_values(document, component="web", deployment=None) == {"A": "component"}


def test_extraction_returns_none_for_an_unrecognised_shape():
    """An unexpected document must not be reported as "no values set"."""
    assert extract_values({"something": "else"}, component="web", deployment=None) is None
