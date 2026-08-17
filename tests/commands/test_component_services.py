"""`component update --service` adds; it never quietly takes something away.

The flag used to replace the whole list, on a command whose own help says "Only the fields
you specify change; all others remain as-is". Naming one service therefore unbound every
other one. A practice run hit it while unpublishing a component: the attachment coupling was
gone afterwards, and nothing had said so.

The API grew `add_services` / `remove_services` in answer to that (questions 16 and 17 in
RIG-Cluster's `plans/vragen-uit-zad-cli.md`), so the merge happens where the data is. This
CLI does not read the list first: two callers adding at the same moment would each compute a
list from before the other landed, and one addition would vanish.

`--replace-services` is the old meaning under a name that says what it does.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx
from typer.testing import CliRunner

from zad_cli.cli import app

API = "https://api.example.com"
COMPONENTS = f"{API}/v2/projects/my-project/components"
UPDATE = f"{API}/v2/projects/my-project/components/backend"

runner = CliRunner()


@pytest.fixture(autouse=True)
def _credentials(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ZAD_API_KEY", "test-key")
    monkeypatch.setenv("ZAD_PROJECT_ID", "my-project")
    monkeypatch.setenv("ZAD_API_URL", API)
    monkeypatch.setenv("ZAD_YES", "true")


def _run(*args: str):
    respx.patch(UPDATE).mock(return_value=httpx.Response(200, json={"success": True}))
    listing = respx.get(COMPONENTS).mock(return_value=httpx.Response(200, json={"components": []}))
    result = runner.invoke(app, ["component", "update", "backend", *args])
    assert result.exit_code == 0, result.output
    body = json.loads(respx.patch(UPDATE).calls.last.request.content)
    return body, listing


@respx.mock
def test_adding_a_service_names_only_that_service():
    body, listing = _run("--service", "minio-storage")

    assert body["add_services"] == ["minio-storage"]
    assert "services" not in body, "sending the full list is what loses the config behind it"
    assert not listing.called, "nothing has to be read first, so two callers cannot race"


@respx.mock
def test_removing_is_a_flag_of_its_own():
    body, _ = _run("--remove-service", "redis")

    assert body["remove_services"] == ["redis"]
    assert "services" not in body


@respx.mock
def test_adding_and_removing_in_one_call():
    body, _ = _run("--service", "minio-storage", "--remove-service", "redis")

    assert body["add_services"] == ["minio-storage"]
    assert body["remove_services"] == ["redis"]


@respx.mock
def test_replace_still_exists_for_when_that_is_what_you_mean():
    body, _ = _run("--replace-services", "--service", "redis")

    assert body["services"] == ["redis"]
    assert "add_services" not in body, "the two are mutually exclusive in the API"


@respx.mock
def test_an_update_that_is_not_about_services_says_nothing_about_them():
    body, listing = _run("--memory-limit", "512Mi")

    assert body == {"memory_limit": "512Mi"}
    assert not listing.called


@respx.mock
def test_an_unknown_service_is_refused_before_anything_is_sent():
    patch = respx.patch(UPDATE).mock(return_value=httpx.Response(200, json={"success": True}))

    result = runner.invoke(app, ["component", "update", "backend", "--service", "postgress"])

    assert result.exit_code != 0
    assert not patch.called
