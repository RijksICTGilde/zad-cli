"""What a practice run of 17 August walked into, pinned so it cannot come back.

Ten findings; these are the ones that were ours. Two of them are the same shape as the worst
bug of the round before: a command that did less than it said and reported success. `-c a -c b
-c c` attached only `c`, and `config get api_key` answered with the key itself.

The other two are the price of earlier fixes. Escaping every cell stopped a regex being
swallowed, and then swallowed the one string that really was markup. Naming the SSO token
`sso_token` in `config list` and `token` in the env file meant `config get` could truthfully
answer "not set" about a token it had just displayed.
"""

from __future__ import annotations

import json
import re

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
    monkeypatch.setenv("ZAD_YES", "true")


# --- Every component named, not the last one ------------------------------------------


@respx.mock
def test_deployment_create_attaches_every_named_component():
    """`-c frontend -c backend -c worker --image x` kept `worker` and dropped the other two:
    no error, no warning, and `deployment describe` afterwards was the first place it showed.
    One image across several components is the ordinary shape of an app built from one repo."""
    route = respx.post(f"{API}/v2/projects/my-project/:upsert-deployment").mock(
        return_value=httpx.Response(200, json={"status": "success"})
    )

    result = runner.invoke(
        app,
        [
            "-o",
            "json",
            "deployment",
            "create",
            "productie",
            "-c",
            "frontend",
            "-c",
            "backend",
            "-c",
            "worker",
            "--image",
            "ghcr.io/org/app:v1",
        ],
    )

    assert result.exit_code == 0, result.output
    sent = json.loads(route.calls.last.request.content)
    assert [c["reference"] for c in sent["components"]] == ["frontend", "backend", "worker"]
    assert {c["image"] for c in sent["components"]} == {"ghcr.io/org/app:v1"}


@respx.mock
def test_one_component_still_works():
    route = respx.post(f"{API}/v2/projects/my-project/:upsert-deployment").mock(
        return_value=httpx.Response(200, json={"status": "success"})
    )

    result = runner.invoke(
        app, ["deployment", "create", "productie", "--component", "web", "--image", "ghcr.io/org/app:v1"]
    )

    assert result.exit_code == 0, result.output
    assert len(json.loads(route.calls.last.request.content)["components"]) == 1


def test_a_component_without_an_image_is_still_refused():
    result = runner.invoke(app, ["deployment", "create", "productie", "-c", "web", "-c", "api"])

    assert result.exit_code != 0
    assert "--component and --image go together" in " ".join(result.output.split())


# --- A secret is reported, never printed ----------------------------------------------


def test_config_get_does_not_print_the_api_key(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """It printed the project's key on stdout, which is the hole `project list --show-keys`
    was removed for. An agent quoting the output into a transcript then leaks a credential
    that does not expire."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env.zadctl").write_text("ZAD_API_KEY=supersecretvalue\n")
    monkeypatch.delenv("ZAD_API_KEY", raising=False)

    result = runner.invoke(app, ["config", "get", "api_key"])

    assert result.exit_code == 0, result.output
    assert "supersecretvalue" not in result.output
    assert "(set)" in result.output


def test_config_get_answers_to_the_name_config_list_shows(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """`config list` calls it `sso_token`; the env file calls it `token`. Asking by the name
    the CLI itself prints answered "not set" about a token it had just shown as EXPIRED."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env.zadctl").write_text("ZAD_SSO_TOKEN=nota.real.token\n")
    monkeypatch.delenv("ZAD_SSO_TOKEN", raising=False)

    result = runner.invoke(app, ["config", "get", "sso_token"])

    assert result.exit_code == 0, result.output
    assert "is not set" not in result.output
    assert "nota.real.token" not in result.output


def test_config_get_still_prints_what_is_not_secret(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env.zadctl").write_text("ZAD_API_URL=https://elsewhere.example/api\n")
    monkeypatch.delenv("ZAD_API_URL", raising=False)

    result = runner.invoke(app, ["config", "get", "api_url"])

    assert result.exit_code == 0, result.output
    assert "https://elsewhere.example/api" in result.output


# --- A status that is markup, in a table that escapes ----------------------------------


@respx.mock
def test_a_status_is_coloured_and_not_spelled_out():
    """`project status` printed a literal `[green]Healthy[/green]`: the escaping that keeps a
    regex from being swallowed doing exactly its job on the one string that wanted markup."""
    respx.get(f"{API}/v2/projects/my-project/status").mock(
        return_value=httpx.Response(
            200,
            json={
                "project": "my-project",
                "deployments": [{"deployment": "productie", "status": "Healthy", "components": 3, "errors": []}],
            },
        )
    )
    respx.get(f"{API}/v2/projects/my-project/deployments").mock(
        return_value=httpx.Response(
            200,
            json={
                "project": "my-project",
                "cluster": "sandboxed-local",
                "deployments": [
                    {
                        "name": "productie",
                        "project": "my-project",
                        "cluster": "sandboxed-local",
                        "namespace": "ns",
                        "status": "Healthy",
                        "urls": {},
                        "components": [],
                        "errors": [],
                    }
                ],
            },
        )
    )

    respx.get(f"{API}/subdomains").mock(return_value=httpx.Response(200, json={"subdomains": []}))

    result = runner.invoke(app, ["project", "status"])

    assert result.exit_code == 0, result.output
    assert "[green]" not in result.output
    assert "Healthy" in result.output


# --- The complete sentence, not the cut-off copy of it --------------------------------


def test_a_truncated_flat_message_gives_way_to_the_whole_one():
    """The platform sends the same error twice: flat and cut to a fixed length, and again on
    the subtask that raised it, in full. Both were on screen; the readable one was the one
    you had to scroll to."""
    from zad_cli.api.errors import diagnose_task_failure

    whole = (
        "Service 'attachments' needs a project-level decision that cannot be assumed, so it "
        "is not selected automatically; GET /api/v2/services/attachments lists the actions "
        "that put something there."
    )
    diagnosis = diagnose_task_failure(
        whole[:170],
        {"status": "partial", "error_type": "invalid_services"},
        subtasks=[
            {"name": "Component validatie", "status": "completed"},
            {"name": "Component toevoegen", "status": "failed", "error": whole},
        ],
    )

    assert diagnosis.summary == whole, diagnosis.summary
    assert diagnosis.summary is not None and not diagnosis.summary.endswith("actions ")


def test_a_message_that_is_not_a_prefix_is_left_alone():
    """The rule only ever picks the longer of two strings the API sent, and only when the
    short one starts the long one. Two different sentences stay two sentences."""
    from zad_cli.api.errors import diagnose_task_failure

    diagnosis = diagnose_task_failure(
        "Rollout stopped because the cluster refused the manifest.",
        {"status": "partial"},
        subtasks=[{"name": "Uitrollen", "status": "failed", "error": "Something else entirely happened."}],
    )

    assert diagnosis.summary == "Rollout stopped because the cluster refused the manifest."


# --- What the platform delivered in answer, and what the CLI does with it --------------


def test_a_categorised_task_failure_is_your_fault_and_exits_1():
    """`error_category` landed on 17 August because a failed task carried only `error_type`,
    a free string we would not guess from. An unselected service named on `component add` came
    out as `Unknown` and exit 3 -- "not attributable" -- when it was plainly the request."""
    from zad_cli.api.errors import Fault, diagnose_task_failure

    diagnosis = diagnose_task_failure(
        "Service 'attachments' needs a project-level decision that cannot be assumed",
        {"status": "partial", "error_type": "invalid_services", "error_category": "InvalidInput"},
    )

    assert diagnosis.fault is Fault.USER_INPUT
    assert diagnosis.exit_code == 1, "CI should stop, not retry a typo"


def test_a_category_we_do_not_know_still_reads_as_unattributable():
    """Loose coupling in the other direction: a tenth category arriving before this CLI knows
    it must not be read as somebody's fault."""
    from zad_cli.api.errors import Fault, diagnose_task_failure

    diagnosis = diagnose_task_failure(
        "Something happened", {"status": "partial", "error_category": "SomethingNewUpstream"}
    )

    assert diagnosis.fault is Fault.UNKNOWN
    assert diagnosis.exit_code == 3


def test_an_uncategorised_failure_keeps_the_old_text_scan():
    """Seven `*Result` schemas still carry no `error_category`, so the fallback stays load-bearing."""
    from zad_cli.api.errors import Fault, diagnose_task_failure

    diagnosis = diagnose_task_failure("The pod is in CrashLoopBackOff", {"status": "partial"})

    assert diagnosis.fault is Fault.USER_APP


def test_a_platform_managed_field_is_not_offered_as_an_option():
    """`minio-storage.revisions` is written by the platform, refused on a write and left out of
    a read -- and it was in the options table with required markers on the fields inside it, so
    a reader was invited to fill in a branch nobody may touch."""
    from zad_cli.commands.service import _leaves

    schema = {
        "properties": {
            "enable-versioning": {"type": "boolean"},
            "generation": {"type": "integer", "x-platform-managed": True},
            "revisions": {
                "type": "array",
                "x-platform-managed": True,
                "items": {
                    "type": "object",
                    "required": ["generation", "status"],
                    "properties": {"generation": {"type": "integer"}, "status": {"type": "string"}},
                },
            },
        }
    }

    keys = [key for key, _, _ in _leaves(schema["properties"], set())]

    assert keys == ["enable-versioning"], keys


# --- Two fields, one endpoint, two questions -------------------------------------------


def test_two_fields_reading_one_endpoint_do_not_share_an_answer():
    """The resolved-choices cache was keyed on the endpoint alone, which held while one
    endpoint fed one field. On 17 August `domain-format` started pointing at
    `base-domains[].supports-dots` -- the same clusters call, a different path -- and then
    showed the values of `base-domain`: domain names offered as hostname templates."""
    from zad_cli.commands.service import _values_from_source

    class _Response:
        @staticmethod
        def json():
            return {"clusters": [{"base-domains": [{"value": "apps.example.nl", "supports-dots": True}]}]}

    class _Client:
        max_retries = 0

        def _request(self, *_args, **_kwargs):
            return _Response()

    import zad_cli.commands.service as service_module

    original = service_module.get_helpers
    service_module.get_helpers = lambda _ctx: (_Client(), None)
    try:
        ctx = type("C", (), {"obj": {"settings": type("S", (), {"project_id": "p", "api_key": "k"})()}})()
        cache: dict[str, list[str]] = {}
        endpoint = "GET /api/v2/projects/{project_name}/clusters"
        domains = _values_from_source(ctx, {"endpoint": endpoint, "path": "clusters[].base-domains[].value"}, cache)
        dots = _values_from_source(
            ctx, {"endpoint": endpoint, "path": "clusters[].base-domains[].supports-dots"}, cache
        )
    finally:
        service_module.get_helpers = original

    assert domains == ["apps.example.nl"]
    assert dots != domains, "the path is the question, so it belongs in the cache key"


def test_a_closed_list_beats_a_source_that_only_constrains_it():
    """`domain-format` states eleven templates *and* points at a source saying, per domain,
    whether the dotted half applies. Those booleans are not values you may type."""
    from zad_cli.commands.service import _values_cell

    node = {
        "enum": ["component-deployment-project", "component.deployment.project"],
        "x-choices-source": {
            "endpoint": "GET /api/v2/projects/{project_name}/clusters",
            "path": "clusters[].base-domains[].supports-dots",
            "description": "Hangt af van het gekozen base-domain.",
        },
    }

    cell = _values_cell(node, live=["True", "False"])

    assert "component-deployment-project" in cell
    assert "True" not in cell and "Hangt af" not in cell


# --- A timestamp a reader can act on ---------------------------------------------------


def test_a_utc_timestamp_is_shown_in_the_reader_s_own_zone():
    """`Last sync attempt: 2026-08-12T05:51:02Z` was met with "no idea what that is". The API
    is right to send UTC -- that is an interchange format -- but it is not a reading."""
    from zad_cli.helpers import local_time

    shown = local_time("2026-08-12T05:51:02Z")

    # De vorm, niet een letter: de zonenaam zelf kan een T bevatten (CEST).
    assert re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", shown), shown
    assert "T05:51:02Z" not in shown, "de ISO-vorm is precies wat niemand kon lezen"


def test_the_time_and_the_age_agree_on_a_timestamp_without_a_zone():
    """They parsed separately once, and on a naive value one called it UTC and the other
    called it local -- so one line could report two different moments."""
    from datetime import UTC, datetime, timedelta

    from zad_cli.helpers import age, local_time

    naive = (datetime.now(UTC) - timedelta(hours=3)).replace(tzinfo=None).isoformat(timespec="seconds")

    assert age(naive) == "3 hours ago", age(naive)
    assert local_time(naive) == local_time(naive + "+00:00"), "the same moment, read twice"


def test_something_unreadable_is_passed_through_rather_than_swallowed():
    """This decorates a line in a command that already succeeded."""
    from zad_cli.helpers import age, local_time

    assert local_time("geen-datum") == "geen-datum"
    assert local_time(None) == "None"
    assert age("geen-datum") == ""


@respx.mock
def test_describe_shows_the_local_time_and_how_long_ago():
    from datetime import UTC, datetime, timedelta

    stamp = (datetime.now(UTC) - timedelta(days=6)).strftime("%Y-%m-%dT%H:%M:%SZ")
    respx.get(f"{API}/v2/projects/my-project/deployments/productie").mock(
        return_value=httpx.Response(
            200,
            json={
                "name": "productie",
                "project": "my-project",
                "cluster": "sandboxed-local",
                "namespace": "ns",
                "status": "Healthy",
                "sync_revision": "e2fbc15a54ea1234",
                "last_synced_at": stamp,
                "urls": {},
                "components": [],
                "errors": [],
            },
        )
    )

    result = runner.invoke(app, ["deployment", "describe", "productie"])

    assert result.exit_code == 0, result.output
    flat = " ".join(result.output.split())
    assert "6 days ago" in flat, flat
    assert stamp not in flat, "the raw UTC string is what nobody could read"
