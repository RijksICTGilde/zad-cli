"""The two-way couplings, and the per-entry patch for list-shaped config.

`component assign` names the component first; `deployment assign` is the same call named
from the deployment, because which one reads better depends on what you are holding.
`service config patch` is the per-entry answer to the warning `service config set` prints
for a list: the PUT there writes the block whole, and an entry left out is removed.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx
from typer.testing import CliRunner

from zad_cli.cli import app

API = "https://api.example.com"
COMPONENTS = f"{API}/v2/projects/my-project/deployments/production/components"

runner = CliRunner()


@pytest.fixture(autouse=True)
def _credentials(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ZAD_API_KEY", "test-key")
    monkeypatch.setenv("ZAD_PROJECT_ID", "my-project")
    monkeypatch.setenv("ZAD_API_URL", API)
    monkeypatch.setenv("ZAD_YES", "true")


def _ok():
    return httpx.Response(200, json={"success": True})


# --- deployment assign: component assign, spelled from the deployment ---


@respx.mock
def test_deployment_assign_attaches_an_existing_component():
    route = respx.post(COMPONENTS).mock(return_value=_ok())

    result = runner.invoke(app, ["deployment", "assign", "production", "web", "--image", "img:1"])

    assert result.exit_code == 0, result.output
    assert json.loads(route.calls.last.request.content) == {"component_name": "web", "image": "img:1"}


@respx.mock
def test_deployment_assign_takes_both_names_as_options():
    route = respx.post(COMPONENTS).mock(return_value=_ok())

    result = runner.invoke(
        app,
        ["deployment", "assign", "--name", "production", "--component", "web", "--image", "img:1"],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(route.calls.last.request.content) == {"component_name": "web", "image": "img:1"}


@respx.mock
def test_deployment_assign_without_an_image_is_refused_before_a_call():
    route = respx.post(COMPONENTS).mock(return_value=_ok())

    result = runner.invoke(app, ["deployment", "assign", "production", "web"])

    assert result.exit_code != 0
    assert not route.called


@respx.mock
def test_deployment_assign_adds_so_it_does_not_ask(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("ZAD_YES", raising=False)
    route = respx.post(COMPONENTS).mock(return_value=_ok())

    result = runner.invoke(app, ["deployment", "assign", "production", "web", "--image", "img:1"], input="")

    assert result.exit_code == 0, result.output
    assert route.called


@respx.mock
def test_deployment_assign_dry_run_sends_nothing():
    route = respx.post(COMPONENTS).mock(return_value=_ok())

    result = runner.invoke(app, ["deployment", "assign", "production", "web", "--image", "img:1", "--dry-run"])

    assert result.exit_code == 0, result.output
    assert not route.called
    assert "components" in result.output


# --- service config patch: one entry, not the whole list ---


def _patch_route():
    return respx.patch(f"{API}/v2/projects/my-project/services/persistent-storage/config/component/web").mock(
        return_value=_ok()
    )


@respx.mock
def test_patch_removes_a_single_entry():
    route = _patch_route()

    result = runner.invoke(
        app, ["service", "config", "patch", "persistent-storage", "-c", "web", "--remove", "oude-data"]
    )

    assert result.exit_code == 0, result.output
    assert json.loads(route.calls.last.request.content) == {"remove": ["oude-data"]}


@respx.mock
def test_patch_adds_entries_via_set():
    route = _patch_route()

    result = runner.invoke(
        app,
        [
            "service",
            "config",
            "patch",
            "persistent-storage",
            "-c",
            "web",
            "--set",
            "add[0].name=data",
            "--set",
            "add[0].size=1Gi",
            "--set",
            "add[0].mount-path=/data",
        ],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(route.calls.last.request.content) == {
        "add": [{"name": "data", "size": "1Gi", "mount-path": "/data"}]
    }


@respx.mock
def test_patch_file_and_remove_flag_compose(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "patch.yaml").write_text("add:\n  - name: logs\n    size: 2Gi\n    mount-path: /logs\n")
    route = _patch_route()

    result = runner.invoke(
        app,
        ["service", "config", "patch", "persistent-storage", "-c", "web", "-f", "patch.yaml", "--remove", "old"],
    )

    assert result.exit_code == 0, result.output
    body = json.loads(route.calls.last.request.content)
    assert body["add"] == [{"name": "logs", "size": "2Gi", "mount-path": "/logs"}]
    assert body["remove"] == ["old"]


@respx.mock
def test_patch_without_add_or_remove_is_a_usage_error():
    route = _patch_route()

    result = runner.invoke(app, ["service", "config", "patch", "persistent-storage", "-c", "web"])

    assert result.exit_code != 0
    assert not route.called


@respx.mock
def test_a_layer_without_a_patch_endpoint_says_so_instead_of_sending():
    """`config set` writes a non-list block whole; a patch there would pretend."""
    route = respx.patch(f"{API}/v2/projects/my-project/services/keycloak/config/project").mock(return_value=_ok())

    result = runner.invoke(app, ["service", "config", "patch", "keycloak", "--remove", "x"])

    assert result.exit_code != 0
    assert "config set" in (result.output + (result.stderr or ""))
    assert not route.called


@respx.mock
def test_removing_an_entry_asks_first(monkeypatch: pytest.MonkeyPatch):
    """An entry that leaves a storage list takes its volume with it."""
    monkeypatch.delenv("ZAD_YES", raising=False)
    route = _patch_route()

    # Empty stdin: a prompt with nothing to read aborts, which is what proves it prompted.
    result = runner.invoke(
        app, ["service", "config", "patch", "persistent-storage", "-c", "web", "--remove", "oude-data"], input=""
    )

    assert result.exit_code != 0
    assert not route.called


@respx.mock
def test_only_adding_does_not_ask(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("ZAD_YES", raising=False)
    route = _patch_route()

    result = runner.invoke(
        app,
        [
            "service",
            "config",
            "patch",
            "persistent-storage",
            "-c",
            "web",
            "--set",
            "add[0].name=data",
            "--set",
            "add[0].size=1Gi",
            "--set",
            "add[0].mount-path=/data",
        ],
        input="",
    )

    assert result.exit_code == 0, result.output
    assert route.called


@respx.mock
def test_patch_dry_run_sends_nothing():
    route = _patch_route()

    result = runner.invoke(
        app, ["service", "config", "patch", "persistent-storage", "-c", "web", "--remove", "oude-data", "--dry-run"]
    )

    assert result.exit_code == 0, result.output
    assert not route.called


@respx.mock
def test_config_set_points_a_list_block_at_patch():
    """The warning for a whole-list write now names the command that edits one entry."""
    route = respx.put(f"{API}/v2/projects/my-project/services/persistent-storage/config/component/web").mock(
        return_value=_ok()
    )

    result = runner.invoke(
        app,
        [
            "service",
            "config",
            "set",
            "persistent-storage",
            "-c",
            "web",
            "--set",
            "[0].name=data",
            "--set",
            "[0].size=1Gi",
            "--set",
            "[0].mount-path=/data",
        ],
    )

    assert result.exit_code == 0, result.output
    assert route.called
    err = result.stderr or ""
    assert "service config patch persistent-storage" in err
