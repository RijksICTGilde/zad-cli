"""`zadctl env` and `zadctl alias`: the four value verbs, and the two layers they act on."""

from __future__ import annotations

import json

import httpx
import pytest
import respx
from typer.testing import CliRunner

from zad_cli.cli import app
from zad_cli.commands.values import read_env_file, values_from_components

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
#
# The values endpoint answers this itself: a GET on the same path the writes use, per
# layer, so it is right for deployment-component too.


@respx.mock
def test_list_reads_the_values_endpoint_for_this_layer():
    respx.get(ENV_BASE).mock(
        return_value=httpx.Response(
            200,
            json={
                "service": "user-env-vars",
                "target": "component",
                "component": "web",
                "values": {"A": "1", "B": "2"},
            },
        )
    )
    result = run("-o", "json", "env", "list", "-c", "web")
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {"A": "1", "B": "2"}


@respx.mock
def test_list_of_a_deployment_reads_the_deployment_layer():
    """The more specific layer has its own endpoint; it must not be answered from the other."""
    deployment = respx.get(ENV_DEPLOYMENT_BASE).mock(
        return_value=httpx.Response(
            200,
            json={
                "service": "user-env-vars",
                "target": "deployment-component",
                "component": "web",
                "deployment": "prod",
                "values": {"A": "override"},
            },
        )
    )
    component = respx.get(ENV_BASE).mock(return_value=httpx.Response(200, json={"values": {"A": "1"}}))
    result = run("-o", "json", "env", "list", "-c", "web", "--deployment", "prod")
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {"A": "override"}
    assert deployment.call_count == 1 and component.call_count == 0


@respx.mock
def test_get_prints_one_value():
    respx.get(ENV_BASE).mock(return_value=httpx.Response(200, json={"values": {"A": "1"}}))
    result = run("env", "get", "A", "-c", "web")
    assert result.exit_code == 0, result.output
    assert result.stdout.strip() == "1"


@respx.mock
def test_get_of_an_unset_key_fails_rather_than_printing_nothing():
    respx.get(ENV_BASE).mock(return_value=httpx.Response(200, json={"values": {"A": "1"}}))
    result = run("env", "get", "MISSING", "-c", "web")
    assert result.exit_code == 1
    assert "MISSING" in result.output


@respx.mock
def test_a_secret_is_reported_as_withheld_not_as_three_asterisks():
    """An env var is stored encrypted, so the API returns ***; that is not its value."""
    respx.get(ENV_BASE).mock(return_value=httpx.Response(200, json={"values": {"TOKEN": "***"}}))
    result = run("-o", "json", "env", "list", "-c", "web")
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {"TOKEN": "(set, not returned by the API)"}


@respx.mock
def test_an_alias_reference_comes_back_as_stored():
    """An alias is a reference, not a secret: the reference is the readable part."""
    respx.get(ALIAS_BASE).mock(
        return_value=httpx.Response(200, json={"values": {"POSTGRES_HOST": "$DATABASE_SERVER_HOST"}})
    )
    result = run("-o", "json", "alias", "list", "-c", "web")
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {"POSTGRES_HOST": "$DATABASE_SERVER_HOST"}


# --- Reading from an API that has no values GET yet ---
#
# The endpoint gained its GET on 2026-08-11. Against an API without it the answer is the
# component definition, which still names what is set: a name without its value beats an
# empty list, which would claim nothing is set.

COMPONENTS = f"{API}/v2/projects/my-project/components"


def _no_values_get(base: str = ENV_BASE):
    return respx.get(base).mock(return_value=httpx.Response(405, json={"detail": "Method Not Allowed"}))


@respx.mock
def test_list_falls_back_to_the_component_definition_for_names():
    _no_values_get()
    respx.get(COMPONENTS).mock(
        return_value=httpx.Response(200, json={"components": [{"name": "web", "env_var_names": ["A", "B"]}]})
    )
    result = run("-o", "json", "env", "list", "-c", "web")
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {"A": "(set, no read endpoint)", "B": "(set, no read endpoint)"}


@respx.mock
def test_no_read_path_at_all_fails_rather_than_reporting_an_empty_list():
    """The bug this replaced: an empty list read as "nothing is set"."""
    _no_values_get()
    respx.get(COMPONENTS).mock(return_value=httpx.Response(200, json={"components": []}))
    result = run("env", "list", "-c", "web")
    # A missing read path is the platform's side, so it is a PLATFORM diagnosis (exit 2),
    # not a "you typed something wrong" 1.
    assert result.exit_code == 2
    # Rich wraps the message, so compare without the line breaks it inserted.
    assert "does not mean none are set" in " ".join(result.output.split())


@respx.mock
def test_unreadable_names_are_not_reported_as_none_set():
    """null means the API could not read them, which is not "there are none"."""
    _no_values_get()
    respx.get(COMPONENTS).mock(
        return_value=httpx.Response(200, json={"components": [{"name": "web", "env_var_names": None}]})
    )
    result = run("env", "list", "-c", "web")
    assert result.exit_code == 2


@respx.mock
def test_a_deployment_layer_is_not_answered_with_component_wide_values():
    """The component definition is component-wide; using it here answers the wrong question."""
    _no_values_get(ENV_DEPLOYMENT_BASE)
    components = respx.get(COMPONENTS).mock(
        return_value=httpx.Response(200, json={"components": [{"name": "web", "env_var_names": ["A"]}]})
    )
    result = run("env", "list", "-c", "web", "--deployment", "prod")
    assert result.exit_code == 2
    assert components.call_count == 0
    # The reason names the layer that cannot answer, not a missing endpoint in general.
    assert "component-wide" in " ".join(result.output.split())


@respx.mock
def test_get_keeps_apart_not_set_and_set_but_unreadable():
    _no_values_get()
    respx.get(COMPONENTS).mock(
        return_value=httpx.Response(200, json={"components": [{"name": "web", "env_var_names": ["A"]}]})
    )
    known = run("env", "get", "A", "-c", "web")
    assert known.exit_code == 1
    assert "cannot be shown" in " ".join(known.output.split())

    unknown = run("env", "get", "MISSING", "-c", "web")
    assert unknown.exit_code == 1
    assert "is not set" in unknown.output


@respx.mock
def test_a_get_that_answers_without_values_is_not_reported_as_a_missing_endpoint():
    """The GET exists and answered; saying it does not exist points at the wrong thing."""
    respx.get(ENV_BASE).mock(return_value=httpx.Response(200, json={"service": "user-env-vars"}))
    components = respx.get(COMPONENTS).mock(return_value=httpx.Response(200, json={"components": []}))
    result = run("env", "list", "-c", "web")
    assert result.exit_code == 2
    output = " ".join(result.output.split())
    assert "answered, but without a 'values' field" in output
    assert "has no GET" not in output
    assert components.call_count == 0


@pytest.mark.parametrize("group", ["env", "alias"])
@pytest.mark.parametrize("command", ["list", "get"])
def test_help_does_not_claim_there_is_no_read_endpoint(group: str, command: str):
    """The read path is the values GET; the help must not describe the code it replaced."""
    result = run(group, command, "--help")
    assert result.exit_code == 0, result.output
    assert "no endpoint that returns" not in " ".join(result.output.split())


@respx.mock
def test_an_error_that_is_not_a_missing_get_is_not_swallowed():
    """A 404 names a component that does not exist; hiding it behind the fallback would lie."""
    respx.get(ENV_BASE).mock(return_value=httpx.Response(404, json={"detail": "Component not found"}))
    components = respx.get(COMPONENTS).mock(return_value=httpx.Response(200, json={"components": []}))
    result = run("env", "list", "-c", "web")
    assert result.exit_code != 0
    assert components.call_count == 0


def test_values_from_components_reads_both_document_shapes():
    as_list = {"components": [{"name": "web", "env_var_names": ["A"]}]}
    as_map = {"components": {"web": {"env_var_names": ["A"]}}}
    expected = {"A": "(set, no read endpoint)"}
    assert values_from_components(as_list, component="web", field="env_var_names") == expected
    assert values_from_components(as_map, component="web", field="env_var_names") == expected


def test_values_from_components_returns_none_for_an_unknown_component():
    document = {"components": [{"name": "api", "env_var_names": ["A"]}]}
    assert values_from_components(document, component="web", field="env_var_names") is None
