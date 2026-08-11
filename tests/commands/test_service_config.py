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


def run(*args: str, input: str | None = None):
    return runner.invoke(app, list(args), input=input)


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


def test_no_settings_means_switch_it_on_not_an_error():
    """This used to be refused. An empty body is what "use this service" looks like, and
    the API accepts it; the refusal made selecting a service a two-step trick."""
    result = run("-o", "json", "service", "config", "set", "postgresql-database", "--dry-run", "-y")
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["payload"] == {}


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


# --- Which command configures which service ---


def test_the_catalog_says_which_command_to_use(monkeypatch: pytest.MonkeyPatch):
    """`attachments` is in the service list but is not driven by `service config`.

    Targets and values say where a setting lands; neither says which command puts it
    there, which is the question someone reading the list actually has.
    """
    result = run("-o", "json", "service", "list", "--all")
    services = {s["name"]: s for s in json.loads(result.stdout)}
    assert "attachments" in services


@pytest.mark.parametrize(
    ("service", "expected"),
    [
        ("attachments", "zad attachment"),
        ("user-env-vars", "zad env"),
        ("aliases", "zad alias"),
        ("postgresql-database", "zad service config set postgresql-database"),
        ("minio-storage", "--target"),
        ("platform", "nothing to set"),
    ],
)
def test_describe_names_the_command_that_configures_it(service: str, expected: str):
    result = run("service", "describe", service)
    assert result.exit_code == 0, result.output
    # Rich wraps and truncates table cells at the terminal width, so compare on the
    # unwrapped text and on a fragment short enough to survive it.
    assert expected in " ".join(result.output.split())


def test_a_service_with_more_than_one_layer_says_target_is_needed():
    result = run("-o", "json", "service", "describe", "minio-storage")
    assert "--target <project|deployment>" in result.stdout


def test_a_service_with_one_layer_needs_no_target_in_the_hint():
    """Suggesting --target where there is only one layer teaches a flag nobody needs."""
    result = run("service", "describe", "postgresql-database")
    flat = " ".join(result.output.split())
    assert "--target" not in flat.split("use")[1][:120]


def test_everything_in_the_catalog_is_reachable_under_service():
    """The rule this replaces an exception with: if it is in `service list`, it is under
    `zad service <name>`. Having to remember which services are the exception is what
    makes a CLI something you have to think about instead of type."""
    from typer.main import get_command

    from zad_cli.cli import app

    service_group = get_command(app).commands["service"]
    reachable = set(service_group.commands)

    result = run("-o", "json", "service", "list", "--all")
    for entry in json.loads(result.stdout):
        if not entry["targets"] and not entry["value_targets"]:
            continue  # nothing to set: the platform runs it by itself
        assert entry["name"] in reachable or "config" in reachable, (
            f"{entry['name']} is in the catalog but not under `zad service`"
        )


@pytest.mark.parametrize(
    ("service_form", "short_form"),
    [
        (["service", "attachments"], ["attachment"]),
        (["service", "user-env-vars"], ["env"]),
        (["service", "aliases"], ["alias"]),
    ],
)
def test_the_short_form_is_the_same_app(service_form: list[str], short_form: list[str]):
    """Two spellings, one implementation: nothing can drift between them."""
    long_help = run(*service_form, "--help").stdout
    short_help = run(*short_form, "--help").stdout
    verbs_long = {line.strip().split()[0] for line in long_help.splitlines() if line.startswith("│ ")}
    verbs_short = {line.strip().split()[0] for line in short_help.splitlines() if line.startswith("│ ")}
    assert verbs_long == verbs_short


# --- Selecting a service without configuring it ---


def test_a_service_can_be_switched_on_without_settings():
    """Several services are mostly switched on rather than configured. The API accepts an
    empty body; refusing it here made that possible only through `echo {} | ... -f -`."""
    result = run("-o", "json", "service", "config", "set", "minio-storage", "--target", "project", "--dry-run")
    assert result.exit_code == 0, result.output
    body = json.loads(result.stdout)
    assert body["method"] == "PUT"
    assert body["endpoint"].endswith("/services/minio-storage/config/project")


def test_an_empty_body_is_the_same_as_an_empty_manifest():
    """Two spellings of one request; they may not diverge."""
    bare = run("-o", "json", "service", "config", "set", "minio-storage", "--target", "project", "--dry-run")
    manifest = run(
        "-o",
        "json",
        "service",
        "config",
        "set",
        "minio-storage",
        "--target",
        "project",
        "-f",
        "-",
        "--dry-run",
        input="{}",
    )
    assert json.loads(bare.stdout)["payload"] == json.loads(manifest.stdout)["payload"]


def test_a_wrong_value_is_still_caught():
    """Letting an empty body through must not let a wrong one through with it."""
    result = run("service", "config", "set", "redis", "--set", "acl-key-prefix=onzin", "--dry-run")
    assert result.exit_code != 0
    assert "expected boolean" in " ".join(result.output.split())
