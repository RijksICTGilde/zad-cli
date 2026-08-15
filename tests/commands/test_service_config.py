"""`zadctl service` and `zadctl service config`, driven by the bundled catalog snapshot."""

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
    # publish-on-web accepts more than one layer, so --target is never defaulted.
    result = run(
        "service", "config", "set", "publish-on-web", "--target", "component", "--set", "a=b", "--dry-run", "-y"
    )
    assert result.exit_code != 0
    assert "--component" in result.output


def test_a_layer_without_an_endpoint_is_labelled_not_offered_as_a_valid_pick():
    """The `pass --target (...)` hint used to list `deployment-component` bare for
    publish-on-web, while `service describe` marks it "(not supported)": two answers to
    the same question, and following the hint leads into a refusal."""
    result = run("service", "config", "schema", "publish-on-web")

    assert result.exit_code != 0
    flat = " ".join(result.output.split())
    assert "deployment-component (not supported)" in flat


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
    result = run("service", "config", "clear", "publish-on-web", "--target", "component", "--component", "web", "-y")
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
    assert "zadctl project refresh" in result.output


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
        ("attachments", "zadctl attachment"),
        ("user-env-vars", "zadctl env"),
        ("aliases", "zadctl alias"),
        ("postgresql-database", "zadctl service config set postgresql-database"),
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
    `zadctl service <name>`. Having to remember which services are the exception is what
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
            f"{entry['name']} is in the catalog but not under `zadctl service`"
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


def test_the_binding_line_adds_no_claim_the_registry_did_not_make():
    """`binding` says where a service is configured, not who may bind to it.

    It used to render `binding: deployment` as "no per-component binding for
    postgresql-database", which contradicted the guide -- and the guide was right: a
    practice run bound postgres, redis and minio to two of three components with
    `--service` and watched the third come up without any `DATABASE_*`. Two documents that
    disagree about the model cost more than one that stays silent.
    """
    import json

    from zad_cli.api.registry import SNAPSHOT_PATH, _parse
    from zad_cli.commands.service import _binding_line

    for entry in _parse(json.loads(SNAPSHOT_PATH.read_text()), "snapshot").entries:
        line = _binding_line(entry)
        assert "no per-component" not in line, f"{entry.name}: {line}"
        if entry.binding:
            assert "--service" in line, f"{entry.name} says nothing about how a component gets its variables"


def test_a_layer_the_cli_cannot_write_is_marked_where_it_is_advertised():
    """`publish-on-web` lists `deployment-component` with no endpoint behind it.

    Trying it gives a good error naming the layers that do work, but you only got there by
    trying: `service list` and `service describe` advertised it like any other. Marking it
    where the layer is first shown is the difference between a dead end and a signpost.
    """
    import json

    from zad_cli.api.registry import SNAPSHOT_PATH, _parse

    catalog = _parse(json.loads(SNAPSHOT_PATH.read_text()), "snapshot")
    entry = catalog.get("publish-on-web")

    labelled = entry.targets_labelled()
    assert "deployment-component (not supported)" in labelled
    assert "component" in labelled, "the layers that do work keep their plain name"
    # The raw list is untouched: json output is the registry's answer, not our commentary.
    assert entry.targets == [t.split(" (")[0] for t in labelled]


@respx.mock
def test_a_list_shaped_config_says_it_writes_the_whole_list():
    """`persistent-storage`, `temp-storage` and `attachments` are lists, not objects.

    The endpoint is a PUT, so an entry left out is removed -- which is not obvious from a
    command called `set`. Asked in front of the write, because afterwards the other volume
    is already gone. See question 18 in RIG-Cluster's plans/vragen-uit-zad-cli.md.
    """
    respx.put(f"{API}/v2/projects/my-project/services/persistent-storage/config/component/web").mock(
        return_value=httpx.Response(200, json={"success": True})
    )

    result = run(
        "service",
        "config",
        "set",
        "persistent-storage",
        "--target",
        "component",
        "--component",
        "web",
        "--set",
        "[0].name=data1",
        "--set",
        "[0].size=1Gi",
        "--set",
        "[0].mount-path=/data1",
    )

    assert result.exit_code == 0, result.output
    combined = " ".join(result.output.split())
    assert "writes it whole" in combined
    assert "An entry not named here is removed" in combined
    # The measured consequence, not a euphemism: RIG-Cluster's answer to question 18 says
    # ArgoCD prunes "the PVC and its data immediately".
    assert "goes with the data on it" in combined
    assert "service config get persistent-storage" in combined


@respx.mock
def test_a_config_block_that_is_an_object_says_nothing_of_the_kind():
    respx.put(f"{API}/v2/projects/my-project/services/redis/config/project").mock(
        return_value=httpx.Response(200, json={"success": True})
    )

    result = run("service", "config", "set", "redis")

    assert result.exit_code == 0, result.output
    assert "whole list" not in result.output


def test_describe_names_the_fields_you_can_set():
    """`use` said which command configures a service and stopped there, so the first field
    was one call further on, in `service config schema` -- which is where a reader who came
    to `describe` for "how do I use this" stops looking."""
    result = run("-o", "json", "service", "describe", "sleep-mode")
    assert result.exit_code == 0, result.output
    fields = json.loads(result.stdout)["settings"]["project"][0]["fields"]

    by_name = {row["option"]: row for row in fields}
    # The key as you type it after --set, and the values you may put after the `=`. The
    # schema's own vocabulary ("boolean", "string") answers a question nobody asked at a
    # command line.
    assert by_name["enabled"]["values"] == "true | false"
    assert by_name["enabled"]["default"] == "false"
    assert by_name["wake-mode"]["values"] == "auto | confirm | manual"
    # A list is set per entry, so the option is the entry, not the list.
    assert "match[0]" in by_name


def test_describe_offers_a_command_you_can_run():
    result = run("-o", "json", "service", "describe", "sleep-mode")
    example = json.loads(result.stdout)["settings"]["project"][0]["example"]
    assert example == "zadctl service config set sleep-mode --set enabled=true"


def test_the_example_names_the_layer_when_there_is_more_than_one():
    """A service with two layers cannot be set without `--target`, so an example without
    one is an example that fails."""
    result = run("-o", "json", "service", "describe", "publish-on-web")
    settings = json.loads(result.stdout)["settings"]
    assert "--target component --component <name>" in settings["component"][0]["example"]
    assert "--target deployment --deployment <name>" in settings["deployment"][0]["example"]


def test_an_example_never_switches_a_protection_off():
    """`redis` has one field, on by default, that keeps the project to its own keys.
    Showing the value that changes something made turning it off *the* example for redis,
    with the sentence explaining that consequence not on screen."""
    result = run("-o", "json", "service", "describe", "redis")
    assert "acl-key-prefix=true" in json.loads(result.stdout)["settings"]["project"][0]["example"]


def test_a_body_with_two_shapes_describes_both():
    """`postgresql-database` is a oneOf: a database on the shared instance takes different
    fields from one of its own. Reading only the top level showed nothing at all for it."""
    result = run("-o", "json", "service", "describe", "postgresql-database")
    blocks = json.loads(result.stdout)["settings"]["project"]
    assert [b["variant"] for b in blocks] == ["scope=shared", "scope=project"]
    # Labelled by the field that picks the variant, and the example sets exactly that field.
    assert blocks[1]["example"].endswith("--set scope=project")


def test_a_list_shaped_service_gets_no_field_table():
    """`attachments` is a list of couplings, not a document: there is no field table to
    print, and `use` already points at the command that has the verbs for it."""
    result = run("-o", "json", "service", "describe", "attachments")
    assert json.loads(result.stdout)["settings"] == {}


def test_an_example_does_not_demonstrate_the_off_switch():
    """`health-check` accepts `none | tcp | http | https`, and taking the first value made
    `--set scheme=none` -- probing disabled -- the one example for a service that exists to
    probe."""
    result = run("-o", "json", "service", "describe", "health-check")
    example = json.loads(result.stdout)["settings"]["component"][0]["example"]
    assert example.endswith("--set scheme=tcp"), example


def test_the_values_column_carries_what_the_api_will_refuse():
    """A `pattern` or a range is the whole answer to "what may I put here"; leaving it out
    sends you to a 422 to learn it."""
    result = run("-o", "json", "service", "describe", "cross-domain-access")
    rows = {r["option"]: r for r in json.loads(result.stdout)["settings"]["project"][0]["fields"]}
    # Where the API names a source for the values, that beats the rule: "the components of
    # this project" is a shorter walk than a regex you still have to satisfy by hand. Both
    # of these carry one now, which is why neither shows its bounds.
    assert rows["inbound[0].to.port"]["values"].startswith("<De inkomende poorten")
    assert rows["inbound[0].name *"]["values"].startswith("<De namen van de regels")

    # And where it does not, the rule is what there is.
    postgres = run("-o", "json", "service", "describe", "postgresql-database")
    blocks = json.loads(postgres.stdout)["settings"]["project"]
    fields = {r["option"]: r for block in blocks for r in block["fields"]}
    assert fields["schemas[0].postfix *"]["values"] == "<text: max 32, ^[a-z][a-z0-9_]*$>"


def test_a_nested_option_is_named_the_way_you_type_it():
    """`cross-domain-access` is a list of objects two levels deep. The top level alone reads
    `inbound[0]` with no hint of what goes in it: a row that costs a line and answers
    nothing."""
    result = run("-o", "json", "service", "describe", "cross-domain-access")
    options = [r["option"] for r in json.loads(result.stdout)["settings"]["project"][0]["fields"]]
    assert "inbound[0].from.project" in options
    assert "inbound[0]" not in options


def test_a_pattern_survives_the_table(monkeypatch: pytest.MonkeyPatch):
    """Rich reads `[a-z0-9]` as markup and swallows it, so the regex arrived as
    `^([-a-z0-9]*)?$` -- wrong in a way you cannot see."""
    monkeypatch.setenv("COLUMNS", "300")
    result = run("service", "describe", "postgresql-database")
    assert "^[a-z][a-z0-9_]*$" in result.stdout


def test_describe_shows_how_to_set_several_options_at_once():
    """One example reads as the whole grammar, and the grammar it suggested was one call
    per setting -- which is not just slower: `service config set` writes the document
    whole, so the second call is a second body and the first one's settings are gone."""
    result = run("-o", "json", "service", "describe", "sleep-mode")
    block = json.loads(result.stdout)["settings"]["project"][0]
    assert block["example_multiple"].count("--set ") == 3
    assert block["example_multiple"].startswith(block["example"])


def test_one_option_gets_no_combined_example():
    """`redis` has a single setting; two lines would be the same line printed twice."""
    result = run("-o", "json", "service", "describe", "redis")
    assert json.loads(result.stdout)["settings"]["project"][0]["example_multiple"] == ""


def test_an_example_never_sets_a_value_to_nothing():
    """`description` defaults to the empty string, and `--set description=` is a line that
    sets nothing and looks like a typo."""
    result = run("-o", "json", "service", "describe", "sleep-mode")
    block = json.loads(result.stdout)["settings"]["project"][0]
    assert "=  " not in block["example_multiple"] and not block["example_multiple"].endswith("=")


# --- `zadctl service <name>` ---


def test_every_service_name_is_a_command():
    """`zadctl service sleep-mode` answered "No such command" for sixteen of twenty-one
    services, while five worked because they happen to need their own verbs. Which five is
    not something anyone can be expected to know."""
    for name in ("sleep-mode", "keycloak", "publish-on-web", "postgresql-database"):
        result = run("service", name, "--help")
        assert result.exit_code == 0, f"{name}: {result.output}"
        # "Options:" for a one-layer service, "Options (component):" for a layered one.
        assert "Options" in result.output, name


def test_the_service_help_carries_the_fields_and_a_command():
    """A service with no verbs of its own: the name resolves to a description of it."""
    result = run("service", "keycloak", "--help")
    flat = " ".join(result.output.split())
    assert "template" in flat
    assert "zadctl service config set keycloak --set" in flat
    # Short by design: the long form is one command away, and says so.
    assert "zadctl service describe keycloak" in flat


def test_a_service_with_verbs_still_says_what_you_can_set():
    """`sleep-mode` has `status` and `wake`, which would otherwise make it the one service
    whose help answers "here are two verbs" and nothing about its settings."""
    result = run("service", "sleep-mode", "--help")
    flat = " ".join(result.output.split())
    assert "status" in flat and "wake" in flat
    assert "wake-mode auto | confirm | manual" in flat
    assert "zadctl service describe sleep-mode" in flat


def test_a_service_name_on_its_own_describes_it():
    """A name with no verb is asking what it is -- for the services that have no verbs.
    `sleep-mode` grew `status` and `wake`, so it is a group now and answers with those."""
    plain = run("-o", "json", "service", "keycloak")
    described = run("-o", "json", "service", "describe", "keycloak")
    assert plain.exit_code == 0, plain.output
    assert json.loads(plain.stdout) == json.loads(described.stdout)


def test_a_service_with_its_own_verbs_keeps_them():
    """`persistent-storage` is a group, not a description: resolving it dynamically would
    have taken its verbs away."""
    result = run("service", "persistent-storage", "--help")
    assert result.exit_code == 0, result.output
    assert "add" in result.output and "delete" in result.output


def test_a_near_miss_is_named():
    result = run("service", "sleepmode")
    assert result.exit_code != 0
    assert "sleep-mode" in result.output


def test_the_two_screens_give_the_same_examples(monkeypatch: pytest.MonkeyPatch):
    """`describe` and `<name> --help` answer the same question and must not answer it
    differently. The combined example was added to one and not the other, so `--help`
    quietly went back to suggesting one call per setting."""
    monkeypatch.setenv("COLUMNS", "300")

    def commands(output: str) -> list[str]:
        return [" ".join(line.split()) for line in output.splitlines() if "$ zadctl" in line]

    described = commands(run("service", "describe", "sleep-mode").output)
    helped = commands(run("service", "sleep-mode", "--help").output)

    assert described == helped
    assert len(described) == 2, described  # one setting, and several at once


def test_an_example_survives_the_shell_it_is_pasted_into():
    """`--set match[0]=pr-*` is two globs in one flag: zsh answers "no matches found" and
    the command never runs. `<value>` is a redirection. An example you cannot paste is not
    an example."""
    result = run("-o", "json", "service", "describe", "cross-domain-access")
    example = json.loads(result.stdout)["settings"]["project"][0]["example"]
    assert "--set 'inbound[0].name=<value>'" in example


def test_a_plain_value_is_not_quoted_for_nothing():
    """Quoting everything would be safe and unreadable."""
    result = run("-o", "json", "service", "describe", "sleep-mode")
    assert json.loads(result.stdout)["settings"]["project"][0]["example"].endswith("--set enabled=true")


def test_an_index_is_not_presented_as_the_only_slot():
    """A table that only ever shows `active[0]` reads as "one of these fits here", which is
    a fair reading and a wrong one: the list has no ceiling. What is fixed is that `set`
    writes it whole, so the entries have to arrive in one call."""
    described = " ".join(run("service", "describe", "invite").output.split())
    helped = " ".join(run("service", "invite", "--help").output.split())
    for output in (described, helped):
        assert "[0] is the first entry, not the only one" in output
        assert "in one call" in output


def test_a_service_without_lists_says_nothing_about_indexes():
    assert "first entry" not in run("service", "describe", "redis").output
