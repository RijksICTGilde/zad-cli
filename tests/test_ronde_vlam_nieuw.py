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
