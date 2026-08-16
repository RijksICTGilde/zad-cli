"""Unit tests for command-level helpers and rendering in commands/deployment.py."""

import json
from typing import Any

import pytest
from typer.testing import CliRunner

from zad_cli.cli import app
from zad_cli.commands.deployment import _status_color


@pytest.mark.parametrize(
    "status,expected",
    [
        ("Healthy", "green"),
        ("Degraded", "red"),
        ("Missing", "red"),
        ("OutOfSync", "red"),
        ("Suspended", "red"),
        ("Progressing", "yellow"),
        ("Pending", "yellow"),
        ("Unavailable", "dim"),
        ("Unknown", "dim"),
        ("", "dim"),
    ],
)
def test_status_color(status: str, expected: str) -> None:
    assert _status_color(status) == expected


def _stub_describe(monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any]) -> None:
    """Stub the client describe_deployment + the Settings auth so the command runs."""

    class _StubClient:
        def __init__(self, *_args, **_kwargs):
            self.wait = True
            self.verbose = False

        def describe_deployment(self, _project: str, _deployment: str) -> dict[str, Any]:
            return payload

        def close(self) -> None:
            pass

    monkeypatch.setenv("ZAD_API_KEY", "test-key")
    monkeypatch.setenv("ZAD_PROJECT_ID", "my-project")
    monkeypatch.setenv("ZAD_API_URL", "https://api.example.com")
    monkeypatch.setattr("zad_cli.helpers.ZadClient", _StubClient, raising=False)
    # The import inside _ensure_client uses a deferred import; patch that attribute too.
    import zad_cli.api.client as client_module

    monkeypatch.setattr(client_module, "ZadClient", _StubClient)


def test_describe_renders_healthy_deployment(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_describe(
        monkeypatch,
        {
            "deployment": "staging",
            "project": "my-project",
            "namespace": "ns-staging",
            "components": [{"name": "web", "image": "ghcr.io/org/web:v1"}],
            "urls": {"web": "https://staging.example.com"},
            "status": "Healthy",
            "sync_revision": "abc123def456" + "0" * 28,
            "last_synced_at": "2026-05-07T09:00:00Z",
            "errors": [],
        },
    )

    runner = CliRunner()
    result = runner.invoke(app, ["deployment", "describe", "staging"])

    assert result.exit_code == 0, result.output
    assert "staging" in result.output
    assert "Healthy" in result.output
    # Truncated to the first 12 chars; the trailing zero-padding must not appear.
    assert "abc123def456" in result.output
    assert "abc123def4560" not in result.output
    assert "Last sync attempt" in result.output
    assert "https://staging.example.com" in result.output
    # No errors table when healthy.
    assert "Errors" not in result.output


def test_describe_uses_the_cli_table_style(monkeypatch: pytest.MonkeyPatch) -> None:
    """The components table was the one table drawn with Unicode boxes, ignoring the
    setting. Pinned with `ascii` because that is now the style you have to ask for: the
    point is that this table follows the setting, whichever way it is set."""
    monkeypatch.setenv("ZAD_TABLE_STYLE", "ascii")
    _stub_describe(
        monkeypatch,
        {
            "deployment": "staging",
            "project": "my-project",
            "namespace": "ns-staging",
            "components": [{"name": "web", "image": "ghcr.io/org/web:v1"}],
            "urls": {},
            "status": "Healthy",
            "sync_revision": None,
            "last_synced_at": None,
            "errors": [],
        },
    )

    result = CliRunner().invoke(app, ["deployment", "describe", "staging"])

    assert result.exit_code == 0, result.output
    assert "━" not in result.output and "┃" not in result.output
    assert "+" in result.output


def test_describe_adds_what_the_coupling_does_not_carry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Name and image alone is what made `project describe` the better answer to the
    narrower question. The definitions one call away carry ports, services and mounts."""
    monkeypatch.setenv("COLUMNS", "200")  # wide enough that nothing is dropped

    class _StubClient:
        def __init__(self, *_args, **_kwargs):
            self.wait = True
            self.verbose = False

        def describe_deployment(self, _project, _deployment):
            return {
                "deployment": "staging",
                "project": "my-project",
                "namespace": "ns-staging",
                "components": [{"name": "web", "image": "ghcr.io/org/web:v1"}],
                "urls": {},
                "status": "Healthy",
                "sync_revision": None,
                "last_synced_at": None,
                "errors": [],
            }

        def project_components(self, _project):
            return {
                "components": [
                    {
                        "name": "web",
                        "ports": {"inbound": [8080]},
                        "services": ["redis"],
                        "attachments": [{"reference": "app-config"}],
                    }
                ]
            }

        def close(self) -> None:
            pass

    monkeypatch.setenv("ZAD_API_KEY", "test-key")
    monkeypatch.setenv("ZAD_PROJECT_ID", "my-project")
    monkeypatch.setenv("ZAD_API_URL", "https://api.example.com")
    import zad_cli.api.client as client_module

    monkeypatch.setattr(client_module, "ZadClient", _StubClient)

    result = CliRunner().invoke(app, ["deployment", "describe", "staging"])

    assert result.exit_code == 0, result.output
    flat = " ".join(result.output.split())
    assert "8080" in flat and "redis" in flat and "app-config" in flat


def test_describe_survives_a_definitions_endpoint_that_does_not_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    """An older API without the components endpoint still gets name and image."""

    class _StubClient:
        def __init__(self, *_args, **_kwargs):
            self.wait = True
            self.verbose = False

        def describe_deployment(self, _project, _deployment):
            return {
                "deployment": "staging",
                "project": "my-project",
                "namespace": "ns-staging",
                "components": [{"name": "web", "image": "ghcr.io/org/web:v1"}],
                "urls": {},
                "status": "Healthy",
                "sync_revision": None,
                "last_synced_at": None,
                "errors": [],
            }

        def project_components(self, _project):
            raise RuntimeError("404")

        def close(self) -> None:
            pass

    monkeypatch.setenv("ZAD_API_KEY", "test-key")
    monkeypatch.setenv("ZAD_PROJECT_ID", "my-project")
    monkeypatch.setenv("ZAD_API_URL", "https://api.example.com")
    import zad_cli.api.client as client_module

    monkeypatch.setattr(client_module, "ZadClient", _StubClient)

    result = CliRunner().invoke(app, ["deployment", "describe", "staging"])

    assert result.exit_code == 0, result.output
    assert "web" in result.output and "ghcr.io/org/web:v1" in result.output


def test_describe_renders_degraded_deployment_with_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_describe(
        monkeypatch,
        {
            "deployment": "staging",
            "project": "my-project",
            "namespace": "ns-staging",
            "components": [{"name": "web", "image": "ghcr.io/org/web:bad"}],
            "urls": {},
            "status": "Degraded",
            "sync_revision": "deadbeefcafe" + "0" * 28,
            "last_synced_at": "2026-05-07T08:00:00Z",
            "errors": [
                {
                    "resource": "Pod/web-7c9d8f-xxxxx",
                    "message": "Back-off pulling image ghcr.io/org/web:bad",
                    "category": "ImagePull",
                    "explanation": "Container image cannot be pulled.",
                }
            ],
        },
    )

    runner = CliRunner()
    result = runner.invoke(app, ["deployment", "describe", "staging"])

    assert result.exit_code == 0, result.output
    assert "Degraded" in result.output
    assert "Errors" in result.output
    assert "ImagePull" in result.output
    assert "Back-off pulling image" in result.output
    assert "Container image cannot be pulled." in result.output


def _stub_client(monkeypatch: pytest.MonkeyPatch, **methods: Any) -> None:
    """Install a stub ZadClient exposing the given methods, plus auth env."""

    class _StubClient:
        def __init__(self, *_args, **_kwargs):
            self.wait = True
            self.verbose = False

        def close(self) -> None:
            pass

    for name, fn in methods.items():
        setattr(_StubClient, name, staticmethod(fn))

    monkeypatch.setenv("ZAD_API_KEY", "test-key")
    monkeypatch.setenv("ZAD_PROJECT_ID", "my-project")
    monkeypatch.setenv("ZAD_API_URL", "https://api.example.com")
    import zad_cli.api.client as client_module

    monkeypatch.setattr(client_module, "ZadClient", _StubClient)
    monkeypatch.setattr("zad_cli.helpers.ZadClient", _StubClient, raising=False)


def test_list_shows_issues_column(monkeypatch: pytest.MonkeyPatch) -> None:
    def _list(_project: str) -> list[dict[str, Any]]:
        return [
            {
                "deployment": "staging",
                "project": "my-project",
                "namespace": "ns-staging",
                "components": ["web"],
                "status": "Degraded",
                "urls": {},
                "sync_revision": None,
                "last_synced_at": None,
                "errors": [{"category": "ImagePull", "resource": "Pod/web", "message": "back-off"}],
            }
        ]

    _stub_client(monkeypatch, list_deployments=_list)
    result = CliRunner().invoke(app, ["deployment", "list"])
    assert result.exit_code == 0, result.output
    assert "Issues" in result.output
    assert "ImagePull" in result.output


def _degraded_result() -> dict[str, Any]:
    return {
        "status": "success",
        "processing": {
            "status": "completed",
            "component_failures": [{"component": "web", "failure_type": "CrashLoop", "message": "exited 1"}],
        },
    }


def test_create_surfaces_warnings_but_exits_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_client(monkeypatch, upsert_deployment=lambda _p, _payload: _degraded_result())
    result = CliRunner().invoke(app, ["deployment", "create", "staging", "--component", "web", "--image", "x:1", "-y"])
    assert result.exit_code == 0, result.output
    assert "unhealthy" in result.output.lower()


def test_create_strict_exits_nonzero_on_warnings(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_client(monkeypatch, upsert_deployment=lambda _p, _payload: _degraded_result())
    result = CliRunner().invoke(
        app, ["--strict", "deployment", "create", "staging", "--component", "web", "--image", "x:1", "-y"]
    )
    assert result.exit_code == 1, result.output
    assert "unhealthy" in result.output.lower()


def test_create_strict_exit_code_follows_fault_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    """--strict honors the per-fault exit code: a 'degraded' status is UNKNOWN (exit 3),
    not a hardcoded 1."""
    _stub_client(monkeypatch, upsert_deployment=lambda _p, _payload: {"status": "degraded", "message": "half up"})
    result = CliRunner().invoke(
        app, ["--strict", "deployment", "create", "staging", "--component", "web", "--image", "x:1", "-y"]
    )
    assert result.exit_code == 3, result.output


# --- 1.0: manifests on `deployment create` ---


def _deployment_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ZAD_API_KEY", "test-key")
    monkeypatch.setenv("ZAD_PROJECT_ID", "my-project")
    monkeypatch.setenv("ZAD_API_URL", "https://api.example.com")


def test_create_accepts_a_manifest(tmp_path, monkeypatch: pytest.MonkeyPatch):
    _deployment_env(monkeypatch)
    manifest = tmp_path / "staging.yaml"
    manifest.write_text(
        "components:\n"
        "  - name: web\n"
        "    image: ghcr.io/org/app:v1.0\n"
        "  - name: api\n"
        "    image: ghcr.io/org/api:v1.0\n"
        "subdomain: staging\n"
    )
    result = CliRunner().invoke(
        app, ["-o", "json", "deployment", "create", "staging", "-f", str(manifest), "--dry-run", "-y"]
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)["payload"]
    # The wire format calls it "reference"; the manifest calls it "name".
    assert [c["reference"] for c in payload["components"]] == ["web", "api"]
    assert payload["subdomain"] == "staging"


def test_set_overrides_a_field_of_the_manifest(tmp_path, monkeypatch: pytest.MonkeyPatch):
    _deployment_env(monkeypatch)
    manifest = tmp_path / "staging.yaml"
    manifest.write_text("components:\n  - name: web\n    image: ghcr.io/org/app:v1.0\n")
    result = CliRunner().invoke(
        app,
        [
            "-o",
            "json",
            "deployment",
            "create",
            "staging",
            "-f",
            str(manifest),
            "--set",
            "components[0].image=ghcr.io/org/app:v1.3",
            "--dry-run",
            "-y",
        ],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["payload"]["components"][0]["image"] == "ghcr.io/org/app:v1.3"


def test_flags_win_over_the_manifest(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """A shared manifest plus one flag is the point; the flag has to win."""
    _deployment_env(monkeypatch)
    manifest = tmp_path / "staging.yaml"
    manifest.write_text("components:\n  - name: web\n    image: i\nsubdomain: from-file\n")
    result = CliRunner().invoke(
        app,
        [
            "-o",
            "json",
            "deployment",
            "create",
            "staging",
            "-f",
            str(manifest),
            "--subdomain",
            "from-flag",
            "--dry-run",
            "-y",
        ],
    )
    assert json.loads(result.stdout)["payload"]["subdomain"] == "from-flag"


def test_a_component_list_travels_as_a_document(monkeypatch: pytest.MonkeyPatch):
    """What `--components` used to do, and the reason it could go: a list of components is a
    document, and `-f -` already takes one. This is the call zad-actions makes today."""
    _deployment_env(monkeypatch)
    result = CliRunner().invoke(
        app,
        ["-o", "json", "deployment", "create", "staging", "-f", "-", "--dry-run", "-y"],
        input='{"components": [{"name": "web", "image": "ghcr.io/org/app:v1.0"}]}',
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["payload"]["components"][0]["reference"] == "web"


def test_create_generate_skeleton_needs_no_credentials():
    result = CliRunner().invoke(app, ["-o", "json", "deployment", "create", "x", "--generate-skeleton"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["components"][0]["name"] == "web"


def test_create_without_components_makes_an_empty_deployment(monkeypatch: pytest.MonkeyPatch):
    """A deployment that runs nothing yet is a valid state while the parts are built up."""
    _deployment_env(monkeypatch)
    result = CliRunner().invoke(app, ["-o", "json", "deployment", "create", "staging", "--dry-run", "-y"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)["payload"]
    assert payload["deploymentName"] == "staging"
    # Absent, not []: the upsert merges what it is given, so an empty list must not read
    # as "remove the components that are there".
    assert "components" not in payload


def test_create_with_half_the_pair_is_an_error(monkeypatch: pytest.MonkeyPatch):
    """--component without --image is a slip, not a request for an empty deployment."""
    _deployment_env(monkeypatch)
    result = CliRunner().invoke(app, ["deployment", "create", "staging", "--component", "web", "--dry-run", "-y"])
    assert result.exit_code != 0
    assert "go together" in result.output


# --- delete: "deleted" must mean something was deleted ---
#
# The API used to answer 404 for a deployment that does not exist. It now completes the
# task with deleted: false / already_absent: true, and reporting that as "deleted" claims
# an action that never happened.

import httpx  # noqa: E402
import respx  # noqa: E402

from zad_cli.api.errors import Fault  # noqa: E402

_ABSENT = {
    "status": "completed",
    "deleted": False,
    "already_absent": True,
    "message": "Deployment 'ghost' bestond niet (meer) in project 'p'; er is niets verwijderd",
}


@pytest.fixture
def _delete_credentials(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ZAD_API_KEY", "test-key")
    monkeypatch.setenv("ZAD_PROJECT_ID", "p")
    monkeypatch.setenv("ZAD_API_URL", "https://api.example.com")
    yield


def _mock_delete(payload: dict[str, Any]) -> None:
    respx.delete("https://api.example.com/v2/projects/p/ghost").mock(return_value=httpx.Response(200, json=payload))


@respx.mock
def test_delete_of_an_absent_deployment_does_not_claim_it_deleted(_delete_credentials):
    _mock_delete(_ABSENT)
    result = CliRunner().invoke(app, ["deployment", "delete", "ghost", "-y"])
    assert result.exit_code != 0
    # The false claim, specifically: "Nothing was deleted." is the honest one.
    assert "'ghost' deleted." not in " ".join(result.output.split())
    assert "does not exist" in " ".join(result.output.split())


@respx.mock
def test_ignore_not_found_makes_an_absent_deployment_a_success(_delete_credentials):
    _mock_delete(_ABSENT)
    result = CliRunner().invoke(app, ["deployment", "delete", "ghost", "-y", "--ignore-not-found"])
    assert result.exit_code == 0, result.output
    assert "already deleted" in result.output


@respx.mock
@pytest.mark.parametrize("mocked", ["body", "404"])
def test_absent_delete_leaves_one_json_document_on_stdout(_delete_credentials, mocked: str):
    """json mode must stay parseable: a payload plus a diagnosis is two documents.

    The three tests above look at result.output as text, so they never noticed that
    stdout carried both. CI branches on the json error object, and json.loads() of two
    concatenated documents fails with "Extra data".
    """
    if mocked == "body":
        _mock_delete(_ABSENT)
    else:
        respx.delete("https://api.example.com/v2/projects/p/ghost").mock(
            return_value=httpx.Response(404, json={"detail": "not found"})
        )
    result = CliRunner().invoke(app, ["-o", "json", "deployment", "delete", "ghost", "-y"])
    assert result.exit_code != 0
    payload = json.loads(result.stdout)
    assert payload["fault"] == Fault.USER_INPUT.value


@respx.mock
def test_ignore_not_found_stdout_is_one_json_document(_delete_credentials):
    _mock_delete(_ABSENT)
    result = CliRunner().invoke(app, ["-o", "json", "deployment", "delete", "ghost", "-y", "--ignore-not-found"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {"deleted": False, "reason": "not_found"}


@respx.mock
def test_a_real_deletion_still_reports_success(_delete_credentials):
    _mock_delete({"status": "completed", "deleted": True, "deployment": "ghost"})
    result = CliRunner().invoke(app, ["deployment", "delete", "ghost", "-y"])
    assert result.exit_code == 0, result.output
    assert "'ghost' deleted." in " ".join(result.output.split())


def _capture_component_call(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Capture the payload `component add` / `component update` send."""
    seen: dict[str, Any] = {}

    class _StubClient:
        def __init__(self, *_args, **_kwargs):
            self.wait = True
            self.verbose = False

        def add_component(self, _project: str, payload: dict) -> dict:
            seen.update(payload)
            return {"success": True}

        def update_component(self, _project: str, _name: str, payload: dict) -> dict:
            seen.update(payload)
            return {"success": True}

        def close(self) -> None:
            pass

    monkeypatch.setenv("ZAD_API_KEY", "test-key")
    monkeypatch.setenv("ZAD_PROJECT_ID", "my-project")
    monkeypatch.setenv("ZAD_API_URL", "https://api.example.com")
    monkeypatch.setattr("zad_cli.helpers.ZadClient", _StubClient, raising=False)
    import zad_cli.api.client as client_module

    monkeypatch.setattr(client_module, "ZadClient", _StubClient)
    return seen


def test_rewrite_is_sent_when_asked_for(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _capture_component_call(monkeypatch)

    result = CliRunner().invoke(app, ["component", "add", "api", "--path", "/api", "--rewrite", "/"])

    assert result.exit_code == 0, result.output
    assert seen["path"] == "/api"
    assert seen["rewrite"] == "/"


def test_rewrite_is_absent_when_not_asked_for(monkeypatch: pytest.MonkeyPatch) -> None:
    """The API has no default for it, so sending null would change existing behaviour."""
    seen = _capture_component_call(monkeypatch)

    result = CliRunner().invoke(app, ["component", "add", "api", "--path", "/api"])

    assert result.exit_code == 0, result.output
    assert "rewrite" not in seen
