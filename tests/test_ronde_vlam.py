"""What a practice run of 16 August walked into, pinned so it cannot come back.

Twelve findings; these are the ones that were ours. The binding bug that headed the list is
in `tests/commands/test_service_binding.py`, next to the command it belongs to.

The theme running through all of them is the same: the platform answered, the answer was
wrong or empty, and the CLI passed it on as though it were the truth. A subdomain check that
refuses every name is not a verdict on the name. A `--no-rollout` on an endpoint that has no
such parameter is not a deferral. A union error that says "does not match any of the accepted
shapes" is not the sentence the schema wrote three lines further down.
"""

from __future__ import annotations

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


# --- The subdomain check that refused everything ---

CHECK = f"{API}/v2/projects/my-project/subdomains/check/my-app"


@respx.mock
def test_the_subdomain_check_asks_under_the_project():
    """It used to be `GET /api/subdomains/check/{sub}`, with no project in the route -- and
    the platform legitimises an API key against the project it finds *in the route*, so every
    call was refused. Two practice runs read that refusal as "this name is taken"; one saw
    401 "Missing project_name parameter", the next saw 404 for every name including ones that
    certainly exist. The endpoint moved under the project on 16 August and answers now."""
    route = respx.get(CHECK).mock(return_value=httpx.Response(200, json={"subdomain": "my-app", "available": False}))

    result = runner.invoke(app, ["-o", "json", "project", "check-subdomain", "my-app", "apps.example.nl"])

    assert result.exit_code == 0, result.output
    assert route.called
    assert route.calls.last.request.url.params["base_domain"] == "apps.example.nl"
    assert '"available": false' in result.stdout


def test_the_subdomain_check_needs_a_project(monkeypatch: pytest.MonkeyPatch):
    """It did not use to, and that was the bug: the reservation is per project, so the
    question is too."""
    monkeypatch.delenv("ZAD_PROJECT_ID", raising=False)

    result = runner.invoke(app, ["project", "check-subdomain", "my-app", "apps.example.nl"])

    assert result.exit_code != 0
    assert "project is required" in result.output


# --- A 404 hint that pointed at an unrelated command ---------------------------------


@respx.mock
def test_the_not_found_hint_does_not_send_you_to_list_deployments():
    """It named `zadctl deployment list` for every 404 in the CLI, including a subdomain
    check. A hint that guesses the kind of thing you referenced guesses wrong."""
    respx.get(f"{API}/v2/projects/my-project/deployments/nope").mock(return_value=httpx.Response(404, json={}))

    result = runner.invoke(app, ["deployment", "describe", "nope"])

    assert result.exit_code != 0
    assert "deployment list" not in result.output
    assert "project describe" in " ".join(result.output.split())


@respx.mock
def test_a_404_on_a_path_this_api_does_not_have_says_that_instead():
    """A 404 means two opposite things and they need opposite answers. "That deployment does
    not exist" is a name you can correct; "this API has no such endpoint" is a version, and
    no amount of retyping helps. Two practice runs spent their time on the first reading of
    the second problem -- the subdomain check had moved, and the hint said check the
    spelling."""
    respx.get(f"{API}/verzonnen/pad").mock(return_value=httpx.Response(404, json={"detail": "Not Found"}))

    from zad_cli.api.client import ZadApiError, ZadClient

    client = ZadClient(api_url=API, api_key="k", max_retries=0)
    with pytest.raises(ZadApiError) as caught:
        client._request("GET", "/verzonnen/pad")

    diagnosis = caught.value.diagnosis
    assert diagnosis.headline == "This API has no such endpoint."
    assert diagnosis.exit_code == 2, "not the caller's input: exit 1 would say it was"
    assert any("--api-url" in step for step in diagnosis.next_steps)


@respx.mock
def test_a_404_on_a_path_that_does_exist_still_reads_as_a_missing_name():
    respx.get(f"{API}/v2/projects/my-project/deployments/nope").mock(
        return_value=httpx.Response(404, json={"detail": "Not Found"})
    )

    result = runner.invoke(app, ["deployment", "describe", "nope"])

    assert result.exit_code != 0
    assert "has no such endpoint" not in result.output


# --- The attachment writes that could not be deferred ---


@respx.mock
def test_attachment_writes_defer_like_everything_else(tmp_path):
    """Five attachment endpoints took no `rollout` parameter, so `--no-rollout` was ignored:
    the change landed on the cluster and appeared in no pending list. Measured that way on 16
    August; fixed upstream the next morning, which is why this asserts the ordinary sentence
    rather than a warning about the exception."""
    respx.post(f"{API}/v2/projects/my-project/services/attachments/attachment").mock(
        return_value=httpx.Response(200, json={"status": "success"})
    )
    respx.get(f"{API}/v2/projects/my-project/pending-rollout").mock(return_value=httpx.Response(200, json={"count": 1}))

    payload = tmp_path / "payload.txt"
    payload.write_text("x=1")
    result = runner.invoke(app, ["--no-rollout", "attachment", "add", "conf", "--from-file", str(payload)])

    assert result.exit_code == 0, result.output
    assert "Saved without rolling out" in " ".join(result.output.split())


# --- A union error that would not say what it wanted ---------------------------------


def test_a_union_names_the_shapes_it_will_take():
    """`--set restrict-access.enabled=true` answered "does not match any of the accepted
    shapes for this field", while the branches spell out that enabling it means naming a
    role. Someone had to open the raw schema to find that out."""
    from zad_cli.manifest import ManifestError, validate_against_schema

    schema = {
        "properties": {
            "restrict-access": {
                "anyOf": [
                    {
                        "type": "object",
                        "anyOf": [
                            {"properties": {"enabled": {"const": False}}},
                            {"properties": {"role": {"type": "string"}}, "required": ["role"]},
                            {"properties": {"realm-role": {"type": "string"}}, "required": ["realm-role"]},
                        ],
                    },
                    {"type": "null"},
                ]
            }
        }
    }

    with pytest.raises(ManifestError) as caught:
        validate_against_schema({"restrict-access": {"enabled": True}}, schema, what="keycloak (project) config")

    message = str(caught.value)
    assert "enabled=false" in message
    assert "'role'" in message and "'realm-role'" in message


def test_an_optional_field_reports_the_shape_that_matters():
    """`anyOf: [X, null]` is how a Pydantic spec spells every optional field. Calling that
    "two accepted shapes" buries the one complaint worth reading."""
    from zad_cli.manifest import ManifestError, validate_against_schema

    schema = {
        "properties": {
            "size": {"anyOf": [{"type": "object", "required": ["value"], "properties": {}}, {"type": "null"}]}
        }
    }

    with pytest.raises(ManifestError) as caught:
        validate_against_schema({"size": {}}, schema, what="a config")

    message = str(caught.value)
    assert "accepted shapes" not in message, message
    assert "value" in message


# --- Values that were only discoverable by reading the platform's source -------------


@respx.mock
def test_the_base_domains_a_cluster_offers_can_be_completed():
    """`deployment create --base-domain` had no way to show them, so a run read the
    platform's source to learn that its own domain was on offer. The spec says where they
    live -- an `x-choices-source` on the field -- and that is what this resolves."""
    from zad_cli.commands.service import base_domain_choices

    respx.get(f"{API}/v2/projects/my-project/clusters").mock(
        return_value=httpx.Response(
            200,
            json={
                "clusters": [{"name": "sandboxed-local", "base-domains": [{"value": ""}, {"value": "apps.example.nl"}]}]
            },
        )
    )

    assert "apps.example.nl" in base_domain_choices()


def test_the_hostname_templates_come_from_the_request_schema():
    from zad_cli.helpers import complete_domain_format

    values = complete_domain_format(None, "")

    assert "component-deployment-project" in values
    assert complete_domain_format(None, "component.") == [v for v in values if v.startswith("component.")], (
        "a prefix filters rather than starts over"
    )
