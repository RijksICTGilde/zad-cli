"""The restore commands must send the request body the API requires.

All three of these returned 422 for months because they sent no body at all, while the
spec we vendor ourselves declared one as required. The tests below assert on what goes
over the wire, not on the exit code: a command that sends the wrong thing and gets a
mocked 200 back looks perfectly healthy from the outside.
"""

import json
from typing import Any

import pytest
from typer.testing import CliRunner

from zad_cli.cli import app


def _stub_client(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Capture the payload each restore method is called with."""
    seen: dict[str, Any] = {}

    class _StubClient:
        def __init__(self, *_args, **_kwargs):
            self.wait = True
            self.verbose = False

        def resolve_namespace(self, _project: str, deployment: str) -> str:
            return f"local-rig-{deployment}"

        def restore_project(self, project: str, payload: dict) -> dict:
            seen.update(method="restore_project", project=project, payload=payload)
            return {"success": True}

        def restore_database(self, cluster, namespace, reference, payload, project_name=None) -> dict:
            seen.update(
                method="restore_database",
                cluster=cluster,
                namespace=namespace,
                reference=reference,
                payload=payload,
                project_name=project_name,
            )
            return {"success": True}

        def restore_bucket(self, cluster, namespace, reference, payload, project_name=None) -> dict:
            seen.update(
                method="restore_bucket",
                cluster=cluster,
                namespace=namespace,
                reference=reference,
                payload=payload,
                project_name=project_name,
            )
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


def test_restore_project_sends_the_three_required_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _stub_client(monkeypatch)

    result = CliRunner().invoke(
        app, ["restore", "project", "--deployment", "productie", "-c", "web", "--storage", "data", "-y"]
    )

    assert result.exit_code == 0, result.output
    assert seen["payload"] == {"deployment_name": "productie", "component_name": "web", "storage_name": "data"}
    # Absent, not null: the API treats a missing snapshot_id as "the latest one".
    assert "snapshot_id" not in seen["payload"]


def test_restore_database_sends_the_target(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _stub_client(monkeypatch)

    result = CliRunner().invoke(
        app,
        [
            "restore", "database", "staging", "mydb",
            "--target-host", "db.internal",
            "--target-dbname", "app",
            "--target-username", "app-user",
            "--target-password", "hunter2hunter2",
            "--snapshot-id", "k1234abcd",
            "-y",
        ],
    )  # fmt: skip

    assert result.exit_code == 0, result.output
    assert seen["payload"] == {
        "target_database_host": "db.internal",
        "target_database_port": 5432,
        "target_database_name": "app",
        "target_database_user": "app-user",
        "target_database_password": "hunter2hunter2",
        "snapshot_id": "k1234abcd",
    }
    assert seen["project_name"] == "my-project"
    assert seen["namespace"] == "local-rig-staging"


def test_restore_bucket_sends_the_target(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _stub_client(monkeypatch)

    result = CliRunner().invoke(
        app,
        [
            "restore", "bucket", "staging", "mybucket",
            "--target-endpoint", "https://minio.internal",
            "--target-bucket", "app-data",
            "--target-access-key", "AKIAEXAMPLE",
            "--target-secret-key", "s3cr3ts3cr3t",
            "--clear-target",
            "-y",
        ],
    )  # fmt: skip

    assert result.exit_code == 0, result.output
    assert seen["payload"] == {
        "target_minio_endpoint": "https://minio.internal",
        "target_bucket_name": "app-data",
        "target_access_key": "AKIAEXAMPLE",
        "target_secret_key": "s3cr3ts3cr3t",
        "clear_target": True,
    }


@pytest.mark.parametrize(
    ("argv", "missing"),
    [
        (["restore", "project", "-y"], "--deployment"),
        (["restore", "database", "staging", "mydb", "-y"], "--target-host"),
        (["restore", "bucket", "staging", "mybucket", "-y"], "--target-endpoint"),
    ],
)
def test_restore_refuses_without_the_required_target(
    monkeypatch: pytest.MonkeyPatch, argv: list[str], missing: str
) -> None:
    """Better a usage error here than a 422 from the API after the confirmation prompt."""
    seen = _stub_client(monkeypatch)

    result = CliRunner().invoke(app, argv)

    assert result.exit_code != 0
    assert missing in result.output
    assert seen == {}


def test_dry_run_masks_the_target_password(monkeypatch: pytest.MonkeyPatch) -> None:
    """A dry run prints the body, so the body must not print secrets in the clear."""
    seen = _stub_client(monkeypatch)

    result = CliRunner().invoke(
        app,
        [
            "--output", "json",
            "restore", "database", "staging", "mydb",
            "--target-host", "db.internal",
            "--target-dbname", "app",
            "--target-username", "app-user",
            "--target-password", "hunter2hunter2",
            "--dry-run",
        ],
    )  # fmt: skip

    assert result.exit_code == 0, result.output
    assert seen == {}, "a dry run must not call the API"
    payload = json.loads(result.stdout)["payload"]
    assert payload["target_database_password"] == "hunt********r2"
    assert "hunter2hunter2" not in result.output
    # Everything that is not a secret stays readable, or the dry run stops being useful.
    assert payload["target_database_host"] == "db.internal"


def test_dry_run_masks_the_clone_source_password(monkeypatch: pytest.MonkeyPatch) -> None:
    """Same guarantee for the command that had this problem before restore did."""
    _stub_client(monkeypatch)

    result = CliRunner().invoke(
        app,
        [
            "--output", "json",
            "clone", "database", "staging",
            "--host", "src.internal",
            "--dbname", "app",
            "--username", "app-user",
            "--password", "hunter2hunter2",
            "--dry-run",
        ],
    )  # fmt: skip

    assert result.exit_code == 0, result.output
    assert "hunter2hunter2" not in result.output
