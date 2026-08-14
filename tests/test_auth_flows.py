"""Both login flows and the audience check, against a mocked Keycloak.

A real login cannot be automated (it needs a human in a browser), so what is exercised
here is everything around it: which scope is asked for, what happens when the OAuth client
is missing, and what happens when the token comes back without the audience the API wants.
"""

from __future__ import annotations

import base64
import json
import threading
import time

import httpx
import pytest
import respx
from typer.testing import CliRunner

from zad_cli import auth, credentials
from zad_cli.cli import app
from zad_cli.commands import login

KC = "https://keycloak.test.example"
ISSUER = f"{KC}/realms/rig-platform"
DISCOVERY = f"{ISSUER}/.well-known/openid-configuration"

runner = CliRunner()


@pytest.fixture(autouse=True)
def _environment(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ZAD_API_URL", "https://api.example.com")
    monkeypatch.setenv("ZAD_KEYCLOAK_URL", KC)
    for name in ("ZAD_SSO_ISSUER", "ZAD_SSO_CLIENT_ID", "ZAD_KEYCLOAK_REALM", "ZAD_KEYCLOAK_CLIENT_ID"):
        monkeypatch.delenv(name, raising=False)
    yield


def run(*args: str):
    return runner.invoke(app, list(args))


def jwt(claims: dict) -> str:
    body = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"header.{body}.signature"


def discovery(*, device: bool = True, scopes: list[str] | None = None) -> dict:
    data = {
        "issuer": ISSUER,
        "authorization_endpoint": f"{ISSUER}/protocol/openid-connect/auth",
        "token_endpoint": f"{ISSUER}/protocol/openid-connect/token",
        "scopes_supported": scopes if scopes is not None else ["openid", "profile"],
    }
    if device:
        data["device_authorization_endpoint"] = f"{ISSUER}/protocol/openid-connect/auth/device"
    return data


def mock_discovery(**kwargs) -> None:
    respx.get(DISCOVERY).mock(return_value=httpx.Response(200, json=discovery(**kwargs)))


# --- The audience, read from the token ---


def test_a_token_carrying_the_audience_passes():
    token = jwt({"aud": ["zad-api", "account"]})
    auth.check_audience(token, client_id="zad-cli", issuer=ISSUER)


def test_a_string_aud_counts_too():
    auth.check_audience(jwt({"aud": "zad-api"}), client_id="zad-cli", issuer=ISSUER)


def test_a_token_without_the_audience_is_refused_and_names_the_server_side():
    with pytest.raises(auth.AudienceError) as excinfo:
        auth.check_audience(jwt({"aud": ["account"]}), client_id="zad-cli", issuer=ISSUER)
    message = str(excinfo.value)
    assert "zad-api" in message
    assert "zad-cli" in message
    assert "account" in message
    assert "audience mapper" in message


def test_a_token_that_is_not_a_jwt_cannot_be_checked_and_is_left_alone():
    auth.check_audience("plain-token", client_id="zad-cli", issuer=ISSUER)


def test_reading_aud_needs_no_signature_check():
    assert auth.token_audiences(jwt({"aud": ["a", "b", 3]})) == ["a", "b"]
    assert auth.token_audiences("not.a.jwt") == []


# --- Which scope is asked for is what the realm advertises ---


def test_a_realm_with_an_audience_client_scope_is_asked_for_it():
    endpoints = auth.Endpoints(authorization="a", token="t", device=None, scopes_supported=["openid", "zad-api"])
    assert auth.audience_scope(endpoints) == "openid zad-api"


def test_a_realm_without_it_is_not_asked_for_a_scope_it_would_refuse():
    """There the audience comes from a mapper on the client; asking by name is invalid_scope."""
    endpoints = auth.Endpoints(authorization="a", token="t", device=None, scopes_supported=["openid", "profile"])
    assert auth.audience_scope(endpoints) == "openid"


@respx.mock
def test_the_device_flow_asks_for_the_advertised_audience_scope():
    mock_discovery(scopes=["openid", "zad-api"])
    device = respx.post(f"{ISSUER}/protocol/openid-connect/auth/device").mock(
        return_value=httpx.Response(
            200,
            json={"device_code": "d", "user_code": "ABCD", "verification_uri": "https://verify", "interval": 0},
        )
    )
    respx.post(f"{ISSUER}/protocol/openid-connect/token").mock(
        return_value=httpx.Response(200, json={"access_token": jwt({"aud": "zad-api", "preferred_username": "rob"})})
    )

    result = run("login", "--device")
    assert result.exit_code == 0, result.output
    assert "scope=openid+zad-api" in device.calls[0].request.content.decode()
    assert credentials.get_token()


# --- The device flow ---


@respx.mock
def test_the_device_flow_stores_the_token_and_names_you():
    mock_discovery()
    respx.post(f"{ISSUER}/protocol/openid-connect/auth/device").mock(
        return_value=httpx.Response(
            200,
            json={"device_code": "d", "user_code": "ABCD", "verification_uri": "https://verify", "interval": 0},
        )
    )
    respx.post(f"{ISSUER}/protocol/openid-connect/token").mock(
        return_value=httpx.Response(200, json={"access_token": jwt({"aud": "zad-api", "preferred_username": "rob"})})
    )

    result = run("login", "--device")
    assert result.exit_code == 0, result.output
    assert "rob" in result.output
    assert "ABCD" in result.output


@respx.mock
def test_a_device_token_without_the_audience_is_not_stored():
    mock_discovery()
    respx.post(f"{ISSUER}/protocol/openid-connect/auth/device").mock(
        return_value=httpx.Response(
            200,
            json={"device_code": "d", "user_code": "ABCD", "verification_uri": "https://verify", "interval": 0},
        )
    )
    respx.post(f"{ISSUER}/protocol/openid-connect/token").mock(
        return_value=httpx.Response(200, json={"access_token": jwt({"aud": ["account"]})})
    )

    result = run("login", "--device")
    assert result.exit_code == 2
    assert not credentials.get_token()
    assert "zad-api" in result.output


@respx.mock
def test_a_missing_client_says_what_has_to_be_created():
    """Verified against the real Keycloak on 2026-08-09: the client zad-cli does not exist yet."""
    mock_discovery()
    respx.post(f"{ISSUER}/protocol/openid-connect/auth/device").mock(
        return_value=httpx.Response(401, json={"error": "invalid_client"})
    )

    result = run("login", "--device")
    assert result.exit_code == 2
    output = " ".join(result.output.split())
    assert "zad-cli" in output
    assert "rig-platform" in output
    assert "audience mapper" in output or "zad-api" in output


@respx.mock
def test_an_unreachable_realm_says_where_it_looked():
    respx.get(DISCOVERY).mock(return_value=httpx.Response(404))
    result = run("login", "--device")
    assert result.exit_code == 2
    assert "keycloak.test.example" in " ".join(result.output.split())


# --- The loopback flow ---


@respx.mock
def test_the_loopback_flow_exchanges_the_code_with_pkce(monkeypatch: pytest.MonkeyPatch):
    mock_discovery(device=False, scopes=["openid", "zad-api"])
    token_route = respx.post(f"{ISSUER}/protocol/openid-connect/token").mock(
        return_value=httpx.Response(200, json={"access_token": jwt({"aud": "zad-api"})})
    )

    # Stand in for the browser: whatever URL is shown, answer the callback with the state
    # the CLI put in it.
    import urllib.parse

    def fake_browser(url: str, code: str) -> None:
        query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        assert query["scope"] == ["openid zad-api"]
        assert query["code_challenge_method"] == ["S256"]
        redirect = query["redirect_uri"][0]
        # In a thread, because the listener only answers after on_prompt returns.
        threading.Thread(
            target=httpx.get, args=(f"{redirect}?code=the-code&state={query['state'][0]}",), daemon=True
        ).start()

    monkeypatch.setattr("zad_cli.commands.login._make_prompt", lambda _open: fake_browser)
    respx.route(host="127.0.0.1").pass_through()

    result = run("login", "--browser")
    assert result.exit_code == 0, result.output
    body = urllib.parse.parse_qs(token_route.calls[0].request.content.decode())
    assert body["grant_type"] == ["authorization_code"]
    assert body["code"] == ["the-code"]
    assert body["code_verifier"]
    assert credentials.get_token()


@respx.mock
def test_a_callback_with_the_wrong_state_is_discarded(monkeypatch: pytest.MonkeyPatch):
    mock_discovery(device=False)
    import urllib.parse

    def fake_browser(url: str, code: str) -> None:
        query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        target = f"{query['redirect_uri'][0]}?code=the-code&state=iets-anders"
        threading.Thread(target=httpx.get, args=(target,), daemon=True).start()

    monkeypatch.setattr("zad_cli.commands.login._make_prompt", lambda _open: fake_browser)
    respx.route(host="127.0.0.1").pass_through()

    result = run("login", "--browser")
    assert result.exit_code == 2
    assert not credentials.get_token()


# --- --token keeps working, and says when the token will not be accepted ---


def test_a_hand_supplied_token_without_the_audience_is_stored_with_a_warning():
    result = run("login", "--token", jwt({"aud": ["account"]}))
    assert result.exit_code == 0, result.output
    assert credentials.get_token()
    assert "zad-api" in result.output


def test_the_sign_in_url_is_opened_in_a_browser(monkeypatch: pytest.MonkeyPatch):
    """What every comparable CLI does: print the URL *and* open it."""
    opened: list[str] = []
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url) or True)

    prompt = login._make_prompt(True)
    prompt("https://keycloak.example/auth?x=1", "ABCD-1234")

    assert opened == ["https://keycloak.example/auth?x=1"]


def test_no_open_only_prints(monkeypatch: pytest.MonkeyPatch):
    """Headless, SSH and scripts: a browser launched there is a surprise, not a service."""
    opened: list[str] = []
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url) or True)

    login._make_prompt(False)("https://keycloak.example/auth", "")

    assert opened == []


def test_a_browser_that_will_not_open_is_not_fatal(monkeypatch: pytest.MonkeyPatch):
    """The URL is on screen either way, so a failed launch is a note, not an error."""
    monkeypatch.setattr("webbrowser.open", lambda url: False)

    login._make_prompt(True)("https://keycloak.example/auth", "")


# --- Staying signed in ---


def _jwt(exp: int) -> str:
    """A readable JWT with an exp. No signature: nothing here verifies one."""
    head = base64.urlsafe_b64encode(b'{"alg":"none"}').rstrip(b"=").decode()
    body = base64.urlsafe_b64encode(json.dumps({"exp": exp, "aud": "zad-api"}).encode()).rstrip(b"=").decode()
    return f"{head}.{body}.x"


@respx.mock
def test_an_expired_token_is_renewed_without_asking(monkeypatch: pytest.MonkeyPatch):
    """The access token lives five minutes; re-authenticating that often is unusable."""
    mock_discovery()
    credentials.store_token(_jwt(int(time.time()) - 10), "refresh-1")
    fresh = _jwt(int(time.time()) + 300)
    route = respx.post(f"{ISSUER}/protocol/openid-connect/token").mock(
        return_value=httpx.Response(200, json={"access_token": fresh, "refresh_token": "refresh-2"})
    )

    got = credentials.get_token(issuer=ISSUER, client_id="zad-cli")

    assert got == fresh
    assert route.called
    assert route.calls.last.request.content.decode().count("grant_type=refresh_token") == 1
    # The new refresh token replaces the used one, or the next renewal fails.
    assert credentials.get_refresh_token() == "refresh-2"


@respx.mock
def test_a_token_that_is_still_valid_is_not_renewed():
    mock_discovery()
    valid = _jwt(int(time.time()) + 3600)
    credentials.store_token(valid, "refresh-1")
    route = respx.post(f"{ISSUER}/protocol/openid-connect/token")

    assert credentials.get_token(issuer=ISSUER, client_id="zad-cli") == valid
    assert not route.called


@respx.mock
def test_a_spent_refresh_token_does_not_crash_the_command():
    """It means signing in again, which the 401 handler already says how to do."""
    mock_discovery()
    expired = _jwt(int(time.time()) - 10)
    credentials.store_token(expired, "refresh-1")
    respx.post(f"{ISSUER}/protocol/openid-connect/token").mock(
        return_value=httpx.Response(400, json={"error": "invalid_grant"})
    )

    assert credentials.get_token(issuer=ISSUER, client_id="zad-cli") == expired


def test_a_token_handed_in_by_the_environment_is_left_alone(monkeypatch: pytest.MonkeyPatch):
    """Explicitly passed in means someone else manages its lifetime."""
    credentials.store_token(_jwt(int(time.time()) - 10), "refresh-1")
    monkeypatch.setenv("ZAD_SSO_TOKEN", "van-buiten")
    assert credentials.get_token(issuer=ISSUER, client_id="zad-cli") == "van-buiten"


def test_a_rejected_refresh_token_is_said_out_loud(monkeypatch, tmp_path, capsys):
    """An expired session that cannot renew itself must not look like never having signed in.

    The failure used to be swallowed, so the next command reported a bare 401 and "Run
    `zadctl login`" -- which reads as "you have no token" while the token was right there,
    expired, next to a refresh token the server had already rejected. Two practice runs lost
    their first minutes to it.
    """
    import time

    from zad_cli import auth, credentials

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ZAD_SSO_TOKEN", raising=False)
    expired = jwt({"exp": int(time.time()) - 3600})
    credentials.store_token(expired, "spent-refresh-token")

    def refuse(*_args, **_kwargs):
        raise auth.LoginError("invalid_grant")

    monkeypatch.setattr(auth, "refresh", refuse)

    returned = credentials.get_token(issuer=ISSUER, client_id="zad-cli")

    # The expired token still comes back: the call that uses it decides what that means.
    assert returned == expired
    said = capsys.readouterr().err
    assert "expired and could not be renewed" in said
    assert "invalid_grant" in said
    assert "zadctl login" in said
