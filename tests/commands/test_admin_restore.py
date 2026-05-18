"""Rendering tests for the admin and restore list commands.

These guard the fix where the API returns a wrapper object
({"marks": [...]} / {"snapshots": [...]}) but the command must render
the inner list as a table, not dump the wrapper as a single row.
"""

import re
from typing import Any

import pytest
from typer.testing import CliRunner

from zad_cli.cli import app


def _flat(text: str) -> str:
    """Collapse whitespace so Rich's terminal line-wrapping doesn't break substring checks."""
    return re.sub(r"\s+", " ", text)


def _stub_client(monkeypatch: pytest.MonkeyPatch, **methods: Any) -> None:
    class _StubClient:
        def __init__(self, *_args, **_kwargs):
            self.wait = True
            self.verbose = False

        def close(self) -> None:
            pass

    for name, value in methods.items():
        setattr(_StubClient, name, lambda self, *a, _v=value, **k: _v)

    monkeypatch.setenv("ZAD_API_KEY", "test-key")
    monkeypatch.setenv("ZAD_PROJECT_ID", "my-project")
    monkeypatch.setenv("ZAD_API_URL", "https://api.example.com")
    monkeypatch.setattr("zad_cli.helpers.ZadClient", _StubClient, raising=False)
    import zad_cli.api.client as client_module

    monkeypatch.setattr(client_module, "ZadClient", _StubClient)


def test_admin_list_extracts_marks_into_table(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_client(
        monkeypatch,
        list_admin_marked={"marks": [{"id": "m-1", "resource": "ns/pvc-a"}]},
    )

    result = CliRunner().invoke(app, ["admin", "list"])

    assert result.exit_code == 0, result.output
    assert "m-1" in result.output
    assert "ns/pvc-a" in result.output
    assert "Marked for deletion" in _flat(result.output)
    # The wrapper key must not leak as a column header.
    assert "Marks" not in result.output


def test_admin_list_empty_shows_no_results(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_client(monkeypatch, list_admin_marked={"marks": []})

    result = CliRunner().invoke(app, ["admin", "list"])

    assert result.exit_code == 0, result.output
    assert "No results" in result.output


def test_restore_pvc_snapshots_extracts_snapshots(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_client(
        monkeypatch,
        list_pvc_snapshots={"snapshots": [{"id": "snap-1", "timestamp": "2026-05-18T00:00:00Z"}]},
    )

    result = CliRunner().invoke(app, ["restore", "pvc-snapshots", "local", "ns", "app-pvc"])

    assert result.exit_code == 0, result.output
    assert "snap-1" in result.output
    assert "PVC snapshots" in _flat(result.output)
