"""Unit tests for command-level helpers and rendering in commands/deployment.py."""

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
