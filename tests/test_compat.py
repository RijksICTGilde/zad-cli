"""Whether this zadctl and the API still fit together: the platform says so, the CLI listens.

The contract is the one the Operations Manager implements: `User-Agent: zadctl/<version>` on
every request, `426` with `minimum` and `upgrade` below the supported minimum, the
`X-ZADCTL-Recommended` header when a newer version is advised, and both limits under
`clients.zadctl` in the public `/version`.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx
from typer.testing import CliRunner

from zad_cli import __version__, compat
from zad_cli.api.client import ZadClient
from zad_cli.cli import app

runner = CliRunner()
API = "https://api.example.com/api"
WEB = "https://api.example.com"
KC = "https://keycloak.test.example"
ISSUER = f"{KC}/realms/operations-manager"

TOO_OLD = {
    "detail": "zadctl 0.1.0 wordt niet meer ondersteund",
    "client": "zadctl",
    "version": "0.1.0",
    "minimum": "99.0.0",
    "upgrade": "https://example.org/upgrade",
}


@pytest.fixture(autouse=True)
def _environment(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ZAD_API_KEY", "test-key")
    monkeypatch.setenv("ZAD_PROJECT_ID", "p")
    monkeypatch.setenv("ZAD_API_URL", API)
    monkeypatch.setenv("ZAD_KEYCLOAK_URL", KC)
    compat._reset()
    yield
    compat._reset()


def run(*args: str):
    return runner.invoke(app, list(args))


# --- Comparing versions ---


@pytest.mark.parametrize(
    ("current", "required", "expected"),
    [
        ("0.14.1", "0.15.0", True),
        ("0.14.1", "0.14.1", False),
        ("0.15.0", "0.14.9", False),
        ("0.9.0", "0.10.0", True),  # numbers, not strings
        ("0.0.0+local", "99.0.0", False),  # a build from source is never refused here
        ("0.14.1", None, False),
        ("0.14.1", "nonsense", False),
    ],
)
def test_below_compares_numbers_and_never_guesses(current, required, expected):
    assert compat.below(required, current) is expected


# --- Who is asking ---


@respx.mock
def test_api_requests_say_which_zadctl_sent_them():
    route = respx.get(f"{API}/v2/projects/p").mock(return_value=httpx.Response(200, json={}))
    ZadClient(api_url=API, api_key="k").project_detail("p")
    assert route.calls[0].request.headers["User-Agent"] == f"zadctl/{__version__}"


@respx.mock
def test_the_version_endpoint_is_asked_as_zadctl_too():
    route = respx.get(f"{WEB}/version").mock(return_value=httpx.Response(200, json={"name": "ZAD"}))
    ZadClient(api_url=API, api_key="k").server_version()
    assert route.calls[0].request.headers["User-Agent"] == f"zadctl/{__version__}"


# --- Below the minimum: 426 ---


@respx.mock
def test_a_426_names_the_minimum_and_how_to_upgrade():
    route = respx.get(f"{API}/v2/projects/p").mock(return_value=httpx.Response(426, json=TOO_OLD))
    result = run("project", "describe")
    output = " ".join(result.output.split())
    assert result.exit_code == 1
    assert f"zadctl {__version__} is too old for this API, at least 99.0.0 is needed" in output
    assert "https://example.org/upgrade" in output
    assert route.call_count == 1  # an old version does not get younger by asking again


@respx.mock
def test_a_426_in_json_is_an_object_ci_can_branch_on():
    respx.get(f"{API}/v2/projects/p").mock(return_value=httpx.Response(426, json=TOO_OLD))
    result = run("-o", "json", "project", "describe")
    error = json.loads(result.stdout)
    assert result.exit_code == 1
    assert error["fault"] == "UserConfig"
    assert error["status_code"] == 426


@respx.mock
def test_a_426_without_a_readable_body_still_has_the_header():
    respx.get(f"{API}/v2/projects/p").mock(
        return_value=httpx.Response(426, text="Upgrade Required", headers={"X-ZADCTL-Minimum": "98.0.0"})
    )
    result = run("project", "describe")
    assert "at least 98.0.0 is needed" in " ".join(result.output.split())


# --- Below the recommendation: a warning, once ---


@respx.mock
def test_the_recommendation_is_said_once_per_run(capsys: pytest.CaptureFixture[str]):
    respx.get(f"{API}/v2/projects/p").mock(
        return_value=httpx.Response(200, json={}, headers={"X-ZADCTL-Recommended": "99.0.0"})
    )
    client = ZadClient(api_url=API, api_key="k")
    client.project_detail("p")
    client.project_detail("p")
    err = " ".join(capsys.readouterr().err.split())
    assert err.count("99.0.0 is recommended for this API") == 1


@respx.mock
def test_no_warning_when_this_version_already_is_the_recommended_one(capsys: pytest.CaptureFixture[str]):
    respx.get(f"{API}/v2/projects/p").mock(
        return_value=httpx.Response(200, json={}, headers={"X-ZADCTL-Recommended": __version__})
    )
    ZadClient(api_url=API, api_key="k").project_detail("p")
    assert "recommended" not in capsys.readouterr().err


# --- Before signing in ---


def _keycloak_is_never_asked():
    return respx.get(f"{ISSUER}/.well-known/openid-configuration").mock(return_value=httpx.Response(500))


@respx.mock
def test_login_refuses_a_version_below_the_minimum_before_keycloak(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("ZAD_CATALOG_OFFLINE")
    respx.get(f"{WEB}/version").mock(
        return_value=httpx.Response(200, json={"name": "ZAD", "clients": {"zadctl": {"minimum": "99.0.0"}}})
    )
    keycloak = _keycloak_is_never_asked()
    result = run("login")
    assert result.exit_code == 1
    assert "too old for this API, at least 99.0.0 is needed" in " ".join(result.output.split())
    assert not keycloak.called


@respx.mock
def test_login_warns_below_the_recommendation_and_goes_on(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("ZAD_CATALOG_OFFLINE")
    respx.get(f"{WEB}/version").mock(
        return_value=httpx.Response(200, json={"clients": {"zadctl": {"minimum": None, "recommended": "99.0.0"}}})
    )
    keycloak = _keycloak_is_never_asked()
    result = run("login")
    assert "99.0.0 is recommended for this API" in " ".join(result.output.split())
    assert keycloak.called


@pytest.mark.parametrize(
    "answer",
    [
        httpx.Response(200, json={"name": "ZAD", "version": "abc123"}),  # an older server
        httpx.Response(404),
        httpx.Response(200, text="not json"),
    ],
)
@respx.mock
def test_login_goes_on_when_the_server_says_nothing_about_it(monkeypatch: pytest.MonkeyPatch, answer):
    monkeypatch.delenv("ZAD_CATALOG_OFFLINE")
    respx.get(f"{WEB}/version").mock(return_value=answer)
    keycloak = _keycloak_is_never_asked()
    run("login")
    assert keycloak.called


@respx.mock
def test_login_goes_on_when_the_version_endpoint_is_unreachable(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("ZAD_CATALOG_OFFLINE")
    respx.get(f"{WEB}/version").mock(side_effect=httpx.ConnectError("no route"))
    keycloak = _keycloak_is_never_asked()
    run("login")
    assert keycloak.called


# --- What `zadctl version` shows ---


@respx.mock
def test_version_shows_the_limits_the_server_gives():
    respx.get(f"{WEB}/version").mock(
        return_value=httpx.Response(
            200, json={"name": "ZAD", "clients": {"zadctl": {"minimum": "0.1.0", "recommended": "0.2.0"}}}
        )
    )
    info = json.loads(run("-o", "json", "version").stdout)
    assert info["server"]["zadctl"] == {"minimum": "0.1.0", "recommended": "0.2.0"}


@respx.mock
def test_version_leaves_the_limits_out_for_an_older_server():
    respx.get(f"{WEB}/version").mock(return_value=httpx.Response(200, json={"name": "ZAD"}))
    info = json.loads(run("-o", "json", "version").stdout)
    assert "zadctl" not in info["server"]
