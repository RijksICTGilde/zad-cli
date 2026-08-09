"""SSO login against the platform's Keycloak realm.

Almost every endpoint authenticates with a project's own API key. Two cannot: listing
projects and creating one, because you need the project name before you can have its key.
Those take ``Authorization: Bearer <SSO access token>`` instead, and this module is how
the CLI gets one.

Two flows, in this order:

1. **Device authorization** — the CLI prints a URL and a code, you approve in any browser.
   Nothing listens locally, so it works over SSH and inside a container.
2. **Authorization code + PKCE on a loopback listener** — used when the realm or client
   does not offer the device grant. The listener binds ``127.0.0.1`` (never ``0.0.0.0``),
   serves exactly one request, and the ``state`` nonce must come back unchanged.

Both need the OAuth client to be configured for them: the device grant enabled, or the
loopback redirect URI registered. When neither is, ``ZAD_SSO_TOKEN`` (or
``zad login --token``) takes a token obtained elsewhere, which is also what CI uses.
"""

from __future__ import annotations

import base64
import hashlib
import http.server
import os
import secrets
import socket
import threading
import time
import urllib.parse
from dataclasses import dataclass

import httpx

DEFAULT_ISSUER = "https://keycloak.sandbox.rijksapp.dev/realms/operations-manager"
DEFAULT_CLIENT_ID = "rig-platform-operations-manager"

# The loopback port range Keycloak clients usually register. Any free one will do.
LOOPBACK_HOST = "127.0.0.1"


class LoginError(RuntimeError):
    """Login could not complete."""


@dataclass
class Endpoints:
    """The realm's OIDC endpoints, as it advertises them."""

    authorization: str
    token: str
    device: str | None

    @classmethod
    def discover(cls, issuer: str, *, timeout: float = 15.0) -> Endpoints:
        url = f"{issuer.rstrip('/')}/.well-known/openid-configuration"
        try:
            response = httpx.get(url, timeout=timeout, follow_redirects=True)
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as e:
            raise LoginError(f"Could not read the OIDC configuration at {url}: {e}") from e
        return cls(
            authorization=data["authorization_endpoint"],
            token=data["token_endpoint"],
            device=data.get("device_authorization_endpoint"),
        )


def _post(url: str, data: dict[str, str], *, timeout: float = 30.0) -> tuple[int, dict]:
    response = httpx.post(url, data=data, timeout=timeout, follow_redirects=True)
    try:
        return response.status_code, response.json()
    except ValueError:
        return response.status_code, {"error": "invalid_response", "error_description": response.text[:200]}


def device_login(endpoints: Endpoints, client_id: str, *, on_prompt, poll_ceiling: float = 300.0) -> str:
    """Device authorization grant. ``on_prompt`` shows the URL and the user code."""
    if not endpoints.device:
        raise LoginError("This realm does not advertise the device authorization grant.")

    status, start = _post(endpoints.device, {"client_id": client_id, "scope": "openid"})
    if status >= 400:
        raise LoginError(
            f"The device grant is not available for client '{client_id}': "
            f"{start.get('error_description') or start.get('error')}"
        )

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
            return payload["access_token"]
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


def loopback_login(endpoints: Endpoints, client_id: str, *, on_prompt, timeout: float = 300.0) -> str:
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
            "scope": "openid",
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
        raise LoginError("Timed out waiting for the browser to come back.")
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
        raise LoginError(f"Could not exchange the code: {payload.get('error_description') or payload.get('error')}")
    return payload["access_token"]


def issuer_for(api_url: str) -> str:
    """The OIDC issuer to log in against.

    ``ZAD_SSO_ISSUER`` wins; otherwise the realm on the same host as the API, which is how
    every deployment of this platform is laid out.
    """
    configured = os.environ.get("ZAD_SSO_ISSUER")
    if configured:
        return configured.rstrip("/")
    parsed = urllib.parse.urlparse(api_url)
    host = parsed.netloc
    if host.startswith("zad."):
        host = "keycloak." + host[len("zad.") :]
    return f"{parsed.scheme}://{host}/realms/operations-manager"


def client_id() -> str:
    """The OAuth client to log in as; ``ZAD_SSO_CLIENT_ID`` overrides the default."""
    return os.environ.get("ZAD_SSO_CLIENT_ID") or DEFAULT_CLIENT_ID
