"""What a deployment is waiting on, when the thing it waits on is a person.

The API added `approvals` alongside `pending_rollout`, and says why: a domain or subdomain
is on request, so a write that claims one files the request. Without a word about it, "no
ingress appeared" is the first anyone hears of it -- on a deployment that reads Healthy,
because the platform did its part and published on the default address instead.

Nothing here interprets the notice. `status` can hold three values by its description and
none by its schema, so branching on those strings would be branching on a promise the spec
does not make; the API sends a `text` that says what it means, and that is what is shown.
"""

from __future__ import annotations

import httpx
import pytest
import respx
from typer.testing import CliRunner

from zad_cli.api.errors import approval_notices
from zad_cli.cli import app

API = "https://api.example.com"
runner = CliRunner()

_NOTICE = {
    "service": "publish-on-web",
    "type": "domain",
    "label": "Eigen domein",
    "subject": "app.example.nl",
    "status": "requested",
    "text": "Dit domein is aangevraagd en wacht op een beheerder. Tot die tijd publiceert "
    "de deployment op het standaard clusteradres.",
}


@pytest.fixture(autouse=True)
def _credentials(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ZAD_API_KEY", "test-key")
    monkeypatch.setenv("ZAD_PROJECT_ID", "my-project")
    monkeypatch.setenv("ZAD_API_URL", API)
    yield


def test_only_notices_that_say_something_are_kept():
    assert approval_notices({"approvals": [_NOTICE]}) == [_NOTICE]
    assert approval_notices({"approvals": [{"service": "x", "status": "none"}]}) == []
    assert approval_notices({"approvals": []}) == []
    assert approval_notices({}) == []
    assert approval_notices("not a dict") == []


@respx.mock
def test_a_write_that_files_a_request_says_so():
    """The call succeeded and the thing you asked for is not there: that gap is the whole
    reason this field exists."""
    respx.post(f"{API}/v2/projects/my-project/services/publish-on-web/config/component/web").mock(
        return_value=httpx.Response(200, json={"status": "ok"})
    )
    respx.put(f"{API}/v2/projects/my-project/services/publish-on-web/config/component/web").mock(
        return_value=httpx.Response(200, json={"status": "ok", "approvals": [_NOTICE]})
    )
    respx.get(f"{API}/v2/projects/my-project/services/publish-on-web/config").mock(
        return_value=httpx.Response(200, json={"service": "publish-on-web", "configurations": []})
    )

    result = runner.invoke(
        app,
        ["service", "config", "set", "publish-on-web", "--target", "component", "-c", "web", "--set", "tls=standard"],
    )
    assert result.exit_code == 0, result.output
    flat = " ".join(result.output.split())
    assert "Eigen domein - app.example.nl (requested)" in flat
    # The platform's own sentence, not a paraphrase of it.
    assert "publiceert de deployment op het standaard clusteradres" in flat


@respx.mock
def test_describe_says_it_too():
    """A deployment that reads Healthy while its domain was refused is the case this is
    for: the platform did its part, on an address nobody asked for."""
    denied = {**_NOTICE, "status": "denied", "message": "Domein niet van deze organisatie", "by": "beheerder@rig"}
    respx.get(f"{API}/v2/projects/my-project/deployments/productie").mock(
        return_value=httpx.Response(
            200,
            json={
                "name": "productie",
                "project": "my-project",
                # `cluster` is required by DeploymentDetail; a response without it is one
                # the client is right to refuse.
                "cluster": "sandboxed-local",
                "namespace": "ns",
                "status": "Healthy",
                "sync_revision": None,
                "last_synced_at": None,
                "urls": {},
                "components": [],
                "errors": [],
                "approvals": [denied],
            },
        )
    )

    result = runner.invoke(app, ["deployment", "describe", "productie"])
    assert result.exit_code == 0, result.output
    flat = " ".join(result.output.split())
    assert "(denied)" in flat
    assert "Domein niet van deze organisatie" in flat
    assert "beheerder@rig" in flat


@respx.mock
def test_what_is_saved_but_not_rolled_out_arrives_too():
    """Found while wiring the field above: `pending_rollout` was declared nowhere on the
    model either, so pydantic dropped it and the block `deployment describe` has code for
    could never fire."""
    respx.get(f"{API}/v2/projects/my-project/deployments/productie").mock(
        return_value=httpx.Response(
            200,
            json={
                "name": "productie",
                "project": "my-project",
                "cluster": "sandboxed-local",
                "namespace": "ns",
                "status": "Healthy",
                "urls": {},
                "components": [],
                "errors": [],
                "pending_rollout": {"count": 3},
            },
        )
    )

    result = runner.invoke(app, ["deployment", "describe", "productie"])
    assert result.exit_code == 0, result.output
    assert "3 change(s) saved but not rolled out" in " ".join(result.output.split())


_DENIED = {
    **_NOTICE,
    "status": "denied",
    "message": "Domein niet van deze organisatie",
    "text": "Dit domein is afgewezen. De deployment publiceert op het standaard clusteradres.",
}


@respx.mock
def test_a_refused_approval_can_fail_a_pipeline():
    """A refused domain does not stop a deployment: it publishes on the cluster's own
    address instead, healthy and answering, on a name nobody asked for. That is exactly the
    state that should not pass a pipeline quietly."""
    respx.put(f"{API}/v2/projects/my-project/services/publish-on-web/config/component/web").mock(
        return_value=httpx.Response(200, json={"status": "ok", "approvals": [_DENIED]})
    )
    respx.get(f"{API}/v2/projects/my-project/services/publish-on-web/config").mock(
        return_value=httpx.Response(200, json={"service": "publish-on-web", "configurations": []})
    )
    args = ["service", "config", "set", "publish-on-web", "--target", "component", "-c", "web", "--set", "tls=standard"]

    lenient = runner.invoke(app, args)
    assert lenient.exit_code == 0, lenient.output

    strict = runner.invoke(app, ["--strict", *args])
    assert strict.exit_code != 0
    assert "Refused" in strict.output


@respx.mock
def test_a_pending_approval_does_not():
    """Waiting is the normal state of a fresh request; failing on it would fail every first
    write that claims a domain."""
    respx.put(f"{API}/v2/projects/my-project/services/publish-on-web/config/component/web").mock(
        return_value=httpx.Response(200, json={"status": "ok", "approvals": [_NOTICE]})
    )
    respx.get(f"{API}/v2/projects/my-project/services/publish-on-web/config").mock(
        return_value=httpx.Response(200, json={"service": "publish-on-web", "configurations": []})
    )

    result = runner.invoke(
        app,
        [
            "--strict",
            "service",
            "config",
            "set",
            "publish-on-web",
            "--target",
            "component",
            "-c",
            "web",
            "--set",
            "tls=standard",
        ],
    )
    assert result.exit_code == 0, result.output


@respx.mock
def test_a_value_the_platform_filled_in_is_shown():
    """The write is the only place a generated invitation code is ever shown. Swallow this
    line and the invite you just made cannot be sent to anybody."""
    respx.patch(f"{API}/v2/projects/my-project/services/invite/config/project/active").mock(
        return_value=httpx.Response(
            200,
            json={
                "status": "success",
                "generated": {"services/invite/config/active[0]/key": "3ZcYzjxl1zVBVDSlGrBKUg"},
            },
        )
    )

    result = runner.invoke(app, ["service", "config", "patch", "invite", "--set", "add[0].key="])
    assert result.exit_code == 0, result.output
    flat = " ".join(result.output.split())
    assert "services/invite/config/active[0]/key = 3ZcYzjxl1zVBVDSlGrBKUg" in flat
