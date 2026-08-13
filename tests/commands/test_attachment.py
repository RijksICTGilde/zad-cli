"""`zad attachment`: the catalog, the coupling, and the line between them."""

from __future__ import annotations

import json

import httpx
import pytest
import respx
from typer.testing import CliRunner

from zad_cli.cli import app
from zad_cli.commands.attachment import MAX_ATTACHMENT_BYTES

API = "https://api.example.com"
CATALOG = f"{API}/v2/projects/my-project/services/attachments/attachment"
COMPONENT = f"{API}/v2/projects/my-project/services/attachments/component/web/attachment"

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


@pytest.fixture
def cert(tmp_path):
    path = tmp_path / "server.pem"
    path.write_text("---cert---")
    return path


# --- Catalog ---


@respx.mock
def test_add_uploads_to_the_catalog_without_coupling_anything(cert):
    route = respx.post(CATALOG).mock(return_value=_ok())
    result = run("attachment", "add", "server-cert", "--from-file", str(cert), "-y")
    assert result.exit_code == 0, result.output
    content = route.calls[0].request.content
    assert b"server-cert" in content
    assert b"---cert---" in content


@respx.mock
def test_update_replaces_the_content(cert):
    route = respx.put(f"{CATALOG}/server-cert").mock(return_value=_ok())
    result = run("attachment", "update", "server-cert", "--from-file", str(cert), "-y")
    assert result.exit_code == 0, result.output
    assert route.calls[0].request.url.params["upsert"] == "false"


@respx.mock
def test_update_can_upsert(cert):
    route = respx.put(f"{CATALOG}/server-cert").mock(return_value=_ok())
    run("attachment", "update", "server-cert", "--from-file", str(cert), "--upsert", "-y")
    assert route.calls[0].request.url.params["upsert"] == "true"


@respx.mock
def test_delete_refuses_an_attachment_in_use_by_default():
    route = respx.delete(f"{CATALOG}/server-cert").mock(return_value=_ok())
    result = run("attachment", "delete", "server-cert", "-y")
    assert result.exit_code == 0, result.output
    assert route.calls[0].request.url.params["confirm_in_use"] == "false"


# --- Coupling ---


@respx.mock
def test_assign_by_reference_sends_no_file():
    route = respx.post(COMPONENT).mock(return_value=_ok())
    result = run("attachment", "assign", "server-cert", "web", "--mount-path", "/etc/ssl/certs/server.pem", "-y")
    assert result.exit_code == 0, result.output
    content = route.calls[0].request.content
    assert b"reference" in content
    assert b"/etc/ssl/certs/server.pem" in content


@respx.mock
def test_assign_with_a_file_uploads_and_couples_in_one_call(cert):
    """Two calls can half-succeed and leave a catalog entry nothing uses."""
    route = respx.post(COMPONENT).mock(return_value=_ok())
    result = run(
        "attachment",
        "assign",
        "server-cert",
        "web",
        "--from-file",
        str(cert),
        "--mount-path",
        "/etc/x",
        "-y",
    )
    assert result.exit_code == 0, result.output
    content = route.calls[0].request.content
    assert b"---cert---" in content
    assert b"attachment_id" in content


@respx.mock
def test_replace_updates_an_existing_coupling():
    route = respx.put(f"{COMPONENT}/server-cert").mock(return_value=_ok())
    result = run("attachment", "assign", "server-cert", "web", "--mount-path", "/etc/x", "--replace", "-y")
    assert result.exit_code == 0, result.output
    assert route.call_count == 1


def test_mount_path_is_required_for_a_file():
    result = run("attachment", "assign", "server-cert", "web", "--dry-run", "-y")
    assert result.exit_code != 0
    assert "--mount-path" in result.output


def test_env_name_is_required_for_an_env_var():
    result = run("attachment", "assign", "server-cert", "web", "--provide-as", "env-var", "--dry-run", "-y")
    assert result.exit_code != 0
    assert "--env-name" in result.output


def test_an_unknown_provide_as_is_rejected():
    result = run("attachment", "assign", "server-cert", "web", "--provide-as", "volume", "--dry-run", "-y")
    assert result.exit_code != 0


def test_the_mount_path_belongs_to_the_coupling_not_the_file():
    """The same catalog entry can land on a different path per component."""
    first = run(
        "-o",
        "json",
        "attachment",
        "assign",
        "server-cert",
        "web",
        "--mount-path",
        "/etc/a",
        "--dry-run",
        "-y",
    )
    second = run(
        "-o",
        "json",
        "attachment",
        "assign",
        "server-cert",
        "api",
        "--mount-path",
        "/etc/b",
        "--dry-run",
        "-y",
    )
    assert json.loads(first.stdout)["payload"]["path"] == "/etc/a"
    assert json.loads(second.stdout)["payload"]["path"] == "/etc/b"
    assert "/component/web/" in json.loads(first.stdout)["endpoint"]
    assert "/component/api/" in json.loads(second.stdout)["endpoint"]


# --- Uploads ---


def test_a_file_over_the_limit_is_refused_before_uploading(tmp_path):
    big = tmp_path / "big.bin"
    big.write_bytes(b"x" * (MAX_ATTACHMENT_BYTES + 1))
    result = run("attachment", "add", "big", "--from-file", str(big), "--dry-run", "-y")
    assert result.exit_code != 0
    # Rich wraps the message and draws a border through it, so match on the byte count.
    assert str(MAX_ATTACHMENT_BYTES) in " ".join(result.output.split())


def test_an_empty_file_is_refused(tmp_path):
    empty = tmp_path / "empty.txt"
    empty.write_text("")
    result = run("attachment", "add", "empty", "--from-file", str(empty), "--dry-run", "-y")
    assert result.exit_code != 0


def test_a_missing_file_is_refused():
    result = run("attachment", "add", "gone", "--from-file", "/nope/gone.pem", "--dry-run", "-y")
    assert result.exit_code != 0


@respx.mock
def test_the_content_can_come_from_stdin():
    route = respx.post(CATALOG).mock(return_value=_ok())
    result = runner.invoke(app, ["attachment", "add", "server-cert", "--from-file", "-", "-y"], input="---cert---")
    assert result.exit_code == 0, result.output
    assert b"---cert---" in route.calls[0].request.content


# --- Reading ---


# The document as the sandbox returns it: a catalogue of files on the project layer, where
# `config` is a dict, and the couplings on a component layer, where `config` is a list.
REAL_DOCUMENT = {
    "service": "attachments",
    "configurations": [
        {
            "target": "project",
            "component": None,
            "config": {"data": [{"id": "app-config", "filename": "app-config.yaml", "content": "-----BEGIN AGE..."}]},
        },
        {
            "target": "component",
            "component": "backend",
            "config": [{"reference": "app-config", "provide-as": "file", "path": "/etc/app/app-config.yaml"}],
        },
    ],
}


@respx.mock
def test_list_flattens_the_couplings():
    """The document as the API really returns it.

    This test used to invent a shape -- flat and keyed by component -- and passed for
    months while the command found nothing against the real thing and fell back to
    printing the whole encrypted document. A test that agrees with the code and with
    nothing else is worse than no test: it is a reason not to look.
    """
    respx.get(f"{API}/v2/projects/my-project/services/attachments/config").mock(
        return_value=httpx.Response(200, json=REAL_DOCUMENT)
    )

    result = run("-o", "json", "attachment", "list")

    assert result.exit_code == 0, result.output
    rows = json.loads(result.stdout)
    assert rows[0]["reference"] == "app-config"
    assert rows[0]["component"] == "backend"
    assert rows[0]["path"] == "/etc/app/app-config.yaml"


@respx.mock
def test_list_can_filter_by_component():
    document = {
        "service": "attachments",
        "configurations": [
            {"target": "component", "component": "web", "config": [{"reference": "a", "provide-as": "file"}]},
            {"target": "component", "component": "api", "config": [{"reference": "b", "provide-as": "file"}]},
        ],
    }
    respx.get(f"{API}/v2/projects/my-project/services/attachments/config").mock(
        return_value=httpx.Response(200, json=document)
    )

    rows = json.loads(run("-o", "json", "attachment", "list", "--component", "web").stdout)
    assert [row["reference"] for row in rows] == ["a"]


@respx.mock
def test_list_survives_a_project_that_has_both_layers():
    """`config` is a dict on the project layer and a list on a component layer.

    Assuming one shape crashed the command with `AttributeError: 'list' object has no
    attribute 'get'`, on every project that had ever used an attachment -- which is every
    project where the command matters.
    """
    respx.get(f"{API}/v2/projects/my-project/services/attachments/config").mock(
        return_value=httpx.Response(200, json=REAL_DOCUMENT)
    )

    result = run("attachment", "list")

    assert result.exit_code == 0, result.output
    assert "Traceback" not in result.output
