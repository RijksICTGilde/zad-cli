"""SSO login against the platform's Keycloak realm.

Almost every endpoint authenticates with a project's own API key. Two cannot: listing
projects and creating one, because you need the project name before you can have its key.
Those take ``Authorization: Bearer <SSO access token>`` instead, and this module is how
the CLI gets one.

Two flows, in this order:

1. **Device authorization**: the CLI prints a URL and a code, you approve in any browser.
   Nothing listens locally, so it works over SSH and inside a container.
2. **Authorization code + PKCE on a loopback listener**: used when the realm or client
   does not offer the device grant. The listener binds ``127.0.0.1`` (never ``0.0.0.0``),
   serves exactly one request, and the ``state`` nonce must come back unchanged.

Both need the OAuth client to be configured for them: the device grant enabled, or the
loopback redirect URI registered. When neither is, ``ZAD_SSO_TOKEN`` (or
``zadctl login --token``) takes a token obtained elsewhere, which is also what CI uses.

*Which* Keycloak, realm and client is a setting resolved in :mod:`zad_cli.settings`
(flag > env > config > default), never derived from the API host: production is
``keycloak.rijksapp.nl`` with realm ``rig-platform``, which does not follow from
``operations-manager.…rijksapps.nl`` by any rule.

The API only accepts a token minted for it, so the ``aud`` claim is read back after every
flow and a token without :data:`REQUIRED_AUDIENCE` is refused instead of stored. Reading
is all that happens: no signature is checked and no crypto dependency is taken, because
verifying the token is the API's job, not the CLI's.
"""

from __future__ import annotations

import base64
import hashlib
import http.server
import json
import secrets
import socket
import threading
import time
import urllib.parse
from dataclasses import dataclass, field

import httpx

from zad_cli.settings import (
    DEFAULT_KEYCLOAK_CLIENT_ID,
    DEFAULT_KEYCLOAK_REALM,
    DEFAULT_KEYCLOAK_URL,
)

# Which Keycloak, which realm and which client is a *setting*, resolved in settings.py
# through flag > env > config > default. These are re-exported so nothing has to import
# two modules to know what the defaults are.
__all__ = [
    "DEFAULT_KEYCLOAK_CLIENT_ID",
    "DEFAULT_KEYCLOAK_REALM",
    "DEFAULT_KEYCLOAK_URL",
    "REQUIRED_AUDIENCE",
    "AudienceError",
    "Endpoints",
    "LoginError",
    "audience_scope",
    "check_audience",
    "device_login",
    "loopback_login",
    "token_audiences",
    "token_claims",
]

# The API only accepts an access token that was minted for it. Keycloak puts this in
# `aud` either through a client scope of this name or through an audience mapper on the
# client; which one is a property of the realm, so it is discovered, not assumed.
REQUIRED_AUDIENCE = "zad-api"

# The loopback port range Keycloak clients usually register. Any free one will do.
LOOPBACK_HOST = "127.0.0.1"


class LoginError(RuntimeError):
    """Login could not complete."""


class AudienceError(LoginError):
    """A token came back without the audience the API requires.

    This is not something the person logging in can fix from here, so the message says
    so, and names the client that has to be changed.
    """

    def __init__(self, *, client_id: str, issuer: str, found: list[str]) -> None:
        heard = ", ".join(found) if found else "(none)"
        super().__init__(
            f"The token has no '{REQUIRED_AUDIENCE}' audience, so the API would reject it with a bare 401. "
            f"Its aud is: {heard}. This is a server-side setting: the OAuth client '{client_id}' at {issuer} "
            f"needs an audience mapper (or a '{REQUIRED_AUDIENCE}' client scope) that puts "
            f"'{REQUIRED_AUDIENCE}' in the access token. The token was not stored."
        )
        self.client_id = client_id
        self.issuer = issuer
        self.found = found


def client_not_configured(client_id: str, issuer: str, detail: str) -> LoginError:
    """The error for a client that Keycloak does not have, or does not allow this flow.

    Whoever turns this on later has only the message to go on, so it carries the client
    name, the realm it is missing from, and everything that has to be set on it.
    """
    realm = issuer.rstrip("/").rsplit("/realms/", 1)[-1]
    return LoginError(
        f"{detail} The OAuth client '{client_id}' does not exist in realm '{realm}' at {issuer}, "
        f"or it is not set up for this flow. Someone with Keycloak access has to create it: a public "
        f"client with id '{client_id}', 'OAuth 2.0 Device Authorization Grant' enabled, a "
        f"'http://{LOOPBACK_HOST}:*/callback' redirect URI for the browser flow, and an audience mapper "
        f"that puts '{REQUIRED_AUDIENCE}' in the access token. Point at a different Keycloak with "
        f"`zadctl config set keycloak_url <url>` (also: keycloak_realm, keycloak_client_id)."
    )


@dataclass
class Endpoints:
    """The realm's OIDC endpoints, as it advertises them."""

    authorization: str
    token: str
    device: str | None
    issuer: str = ""
    scopes_supported: list[str] = field(default_factory=list)

    @classmethod
    def discover(cls, issuer: str, *, timeout: float = 15.0) -> Endpoints:
        url = f"{issuer.rstrip('/')}/.well-known/openid-configuration"
        try:
            response = httpx.get(url, timeout=timeout, follow_redirects=True)
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as e:
            raise LoginError(f"Could not read the OIDC configuration at {url}: {e}") from e
        scopes = data.get("scopes_supported") or []
        return cls(
            authorization=data["authorization_endpoint"],
            token=data["token_endpoint"],
            device=data.get("device_authorization_endpoint"),
            issuer=data.get("issuer") or issuer.rstrip("/"),
            scopes_supported=[s for s in scopes if isinstance(s, str)],
        )


def audience_scope(endpoints: Endpoints, audience: str = REQUIRED_AUDIENCE) -> str:
    """The scope to ask with, given how this realm hands out the audience.

    Two arrangements exist and they are mutually exclusive. If the realm has a client
    scope named after the API, it only lands in the token when it is asked for, and the
    realm advertises it in ``scopes_supported``. If instead the client carries an
    audience mapper, the audience comes along by itself and asking for it by name is
    refused as an invalid scope. So the discovery document decides, not this code.
    """
    if audience in endpoints.scopes_supported:
        return f"openid {audience}"
    return "openid"


def token_claims(token: str) -> dict:
    """The JWT payload, or {} when the token is not a readable JWT.

    Read, never trusted: the CLI verifies no signature and authorises nothing on these.
    That is the API's job, and doing it here would buy a crypto dependency for nothing.
    """
    parts = token.split(".")
    if len(parts) != 3:
        return {}
    try:
        padded = parts[1] + "=" * (-len(parts[1]) % 4)
        claims = json.loads(base64.urlsafe_b64decode(padded))
    except Exception:  # noqa: BLE001 - an unreadable token is still a usable token
        return {}
    return claims if isinstance(claims, dict) else {}


def token_audiences(token: str) -> list[str]:
    """Everything the token's ``aud`` names; it is a string or a list, per the JWT spec."""
    aud = token_claims(token).get("aud")
    if isinstance(aud, str):
        return [aud]
    if isinstance(aud, list):
        return [a for a in aud if isinstance(a, str)]
    return []


def check_audience(token: str, *, client_id: str, issuer: str, audience: str = REQUIRED_AUDIENCE) -> None:
    """Raise ``AudienceError`` unless the token carries the audience the API demands.

    A token that is not a JWT is left alone: it cannot be inspected, and the CLI is not
    the thing that validates tokens.
    """
    if not token_claims(token):
        return
    found = token_audiences(token)
    if audience not in found:
        raise AudienceError(client_id=client_id, issuer=issuer, found=found)


def _post(url: str, data: dict[str, str], *, timeout: float = 30.0) -> tuple[int, dict]:
    response = httpx.post(url, data=data, timeout=timeout, follow_redirects=True)
    try:
        return response.status_code, response.json()
    except ValueError:
        return response.status_code, {"error": "invalid_response", "error_description": response.text[:200]}


def device_login(
    endpoints: Endpoints,
    client_id: str,
    *,
    on_prompt,
    poll_ceiling: float = 300.0,
    scope: str | None = None,
) -> str:
    """Device authorization grant. ``on_prompt`` shows the URL and the user code."""
    if not endpoints.device:
        raise LoginError("This realm does not advertise the device authorization grant.")

    status, start = _post(endpoints.device, {"client_id": client_id, "scope": scope or audience_scope(endpoints)})
    if status >= 400:
        error = start.get("error")
        detail = start.get("error_description") or error or f"HTTP {status}"
        if error in ("invalid_client", "unauthorized_client"):
            raise client_not_configured(client_id, endpoints.issuer, f"Keycloak answered '{detail}'.")
        raise LoginError(f"The device grant is not available for client '{client_id}': {detail}")

    on_prompt(
        start.get("verification_uri_complete") or start.get("verification_uri", ""),
        start.get("user_code", ""),
    )

    interval = float(start.get("interval", 5))
    deadline = time.time() + min(float(start.get("expires_in", poll_ceiling)), poll_ceiling)
    while time.time() < deadline:
        time.sleep(interval)
        status, payload = _post(
            endpoints.token,
            {
                "client_id": client_id,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "device_code": start["device_code"],
            },
        )
        if status < 400 and payload.get("access_token"):
            return payload["access_token"], payload.get("refresh_token") or ""
        error = payload.get("error")
        if error == "authorization_pending":
            continue
        if error == "slow_down":
            interval += 5
            continue
        raise LoginError(f"Login failed: {payload.get('error_description') or error}")
    raise LoginError("Timed out waiting for the login to be approved.")


def _pkce_pair() -> tuple[str, str]:
    """A PKCE verifier and its S256 challenge."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).decode().rstrip("=")
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).decode().rstrip("=")
    return verifier, challenge


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    """Serves exactly the one redirect the browser makes, and nothing else."""

    result: dict[str, str] = {}

    def do_GET(self) -> None:  # noqa: N802 - the name is BaseHTTPRequestHandler's
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        type(self).result = {k: v[0] for k, v in query.items()}
        body = b"<html><body><p>You can close this window and return to the terminal.</p></body></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:  # noqa: A002, ANN002 - the base class's signature
        """Silence the default stderr access log."""


def loopback_login(
    endpoints: Endpoints, client_id: str, *, on_prompt, timeout: float = 300.0, scope: str | None = None
) -> str:
    """Authorization code + PKCE, with a one-request listener on 127.0.0.1."""
    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(24)

    with socket.socket() as probe:
        probe.bind((LOOPBACK_HOST, 0))
        port = probe.getsockname()[1]
    redirect_uri = f"http://{LOOPBACK_HOST}:{port}/callback"

    server = http.server.HTTPServer((LOOPBACK_HOST, port), _CallbackHandler)
    server.timeout = timeout
    _CallbackHandler.result = {}

    query = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "response_type": "code",
            "scope": scope or audience_scope(endpoints),
            "redirect_uri": redirect_uri,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )
    on_prompt(f"{endpoints.authorization}?{query}", "")

    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()
    thread.join(timeout)
    server.server_close()

    result = _CallbackHandler.result
    if not result:
        # Keycloak refuses an unknown client on its own error page and never redirects,
        # so from here that failure is indistinguishable from a browser nobody opened.
        raise LoginError(
            "Timed out waiting for the browser to come back. If the page said the client was not found, "
            f"the client '{client_id}' does not exist at {endpoints.issuer}."
        )
    if result.get("state") != state:
        raise LoginError("The login response did not carry the expected state; it was discarded.")
    if "code" not in result:
        raise LoginError(f"Login failed: {result.get('error_description') or result.get('error') or 'no code'}")

    status, payload = _post(
        endpoints.token,
        {
            "client_id": client_id,
            "grant_type": "authorization_code",
            "code": result["code"],
            "redirect_uri": redirect_uri,
            "code_verifier": verifier,
        },
    )
    if status >= 400 or not payload.get("access_token"):
        detail = payload.get("error_description") or payload.get("error") or f"HTTP {status}"
        if payload.get("error") in ("invalid_client", "unauthorized_client"):
            raise client_not_configured(client_id, endpoints.issuer, f"Keycloak answered '{detail}'.")
        raise LoginError(f"Could not exchange the code: {detail}")
    return payload["access_token"], payload.get("refresh_token") or ""


def refresh(issuer: str, client_id: str, refresh_token: str) -> tuple[str, str]:
    """Trade a refresh token for a new access token.

    The access token on this platform lives five minutes, which is unusable if every
    command that outlives it means signing in again. The refresh token is what the OAuth
    flow hands over for exactly this, so it is used rather than thrown away.

    Raises LoginError when the refresh token is spent too; the caller signs in again.
    """
    endpoints = Endpoints.discover(issuer)
    status, payload = _post(
        endpoints.token,
        {"grant_type": "refresh_token", "client_id": client_id, "refresh_token": refresh_token},
    )
    if status >= 400 or not payload.get("access_token"):
        detail = payload.get("error_description") or payload.get("error") or f"HTTP {status}"
        raise LoginError(f"Could not refresh the session: {detail}")
    return payload["access_token"], payload.get("refresh_token") or refresh_token


def expires_at(token: str) -> int:
    """The token's `exp`, or 0 when it does not say."""
    exp = token_claims(token).get("exp")
    return int(exp) if isinstance(exp, (int, float)) else 0
