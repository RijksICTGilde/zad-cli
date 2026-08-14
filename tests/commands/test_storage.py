"""Volumes on a component, one at a time.

`persistent-storage` and `temp-storage` carry a list of entries, not a config document, so
the generic setter was the wrong shape: it writes the block whole, and naming one volume
removed the other. On persistent storage that prunes the PVC and the data on it.

The API grew a per-entry PATCH (question 18 in RIG-Cluster's plans/vragen-uit-zad-cli.md),
so `add` and `delete` name only the volume you are working on.

`delete`, not `unassign`: unassigning takes a binding away and leaves the thing itself, and a
volume has no second home to be left in. It exists only as this entry.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx
from typer.testing import CliRunner

from zad_cli.cli import app

API = "https://api.example.com"
CONFIG = f"{API}/v2/projects/my-project/services/persistent-storage/config/component/backend"

runner = CliRunner()


@pytest.fixture(autouse=True)
def _credentials(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ZAD_API_KEY", "test-key")
    monkeypatch.setenv("ZAD_PROJECT_ID", "my-project")
    monkeypatch.setenv("ZAD_API_URL", API)
    monkeypatch.setenv("ZAD_YES", "true")


def _ok():
    return httpx.Response(200, json={"success": True})


@respx.mock
def test_adding_a_volume_names_only_that_volume():
    route = respx.patch(CONFIG).mock(return_value=_ok())

    result = runner.invoke(
        app,
        ["service", "persistent-storage", "add", "data2", "-c", "backend", "--size", "1Gi", "--mount-path", "/data2"],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(route.calls.last.request.content) == {
        "add": [{"name": "data2", "size": "1Gi", "mount-path": "/data2"}]
    }


@respx.mock
def test_deleting_one_volume_names_only_its_key():
    route = respx.patch(CONFIG).mock(return_value=_ok())

    result = runner.invoke(app, ["service", "persistent-storage", "delete", "data2", "-c", "backend"])

    assert result.exit_code == 0, result.output
    assert json.loads(route.calls.last.request.content) == {"remove": ["data2"]}


@respx.mock
def test_deleting_a_volume_asks_first_and_says_what_it_costs(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("ZAD_YES", raising=False)
    route = respx.patch(CONFIG).mock(return_value=_ok())

    result = runner.invoke(app, ["service", "persistent-storage", "delete", "data2", "-c", "backend"], input="")

    assert result.exit_code != 0
    assert not route.called
    combined = " ".join(result.output.split())
    assert "prunes the volume and the data on it" in combined


@respx.mock
def test_temp_storage_is_the_same_commands_on_its_own_service():
    route = respx.patch(f"{API}/v2/projects/my-project/services/temp-storage/config/component/backend").mock(
        return_value=_ok()
    )

    result = runner.invoke(
        app,
        ["service", "temp-storage", "add", "cache", "-c", "backend", "--size", "500Mi", "--mount-path", "/tmp/cache"],
    )

    assert result.exit_code == 0, result.output
    assert route.called


@respx.mock
def test_list_shows_one_row_per_volume_of_that_component():
    document = {
        "service": "persistent-storage",
        "configurations": [
            {
                "target": "component",
                "component": "backend",
                "config": [{"name": "data1", "size": "1Gi", "mount-path": "/data1"}],
            },
            {
                "target": "component",
                "component": "web",
                "config": [{"name": "assets", "size": "2Gi", "mount-path": "/assets"}],
            },
        ],
    }
    respx.get(f"{API}/v2/projects/my-project/services/persistent-storage/config").mock(
        return_value=httpx.Response(200, json=document)
    )

    result = runner.invoke(app, ["-o", "json", "service", "persistent-storage", "list", "-c", "backend"])

    assert result.exit_code == 0, result.output
    assert [row["name"] for row in json.loads(result.stdout)] == ["data1"]


def test_storage_gets_no_top_level_keyword():
    """The entry point is `zadctl service <name>`; the root does not grow per service.

    `attachment`, `env` and `alias` sit at the root because they got there first. Adding one
    per service is how a root becomes a list nobody can hold in their head, and the registry
    keeps growing.
    """
    import typer.main

    from zad_cli.cli import app as root

    names = set(typer.main.get_command(root).commands)
    assert "storage" not in names
    assert "persistent-storage" not in names
