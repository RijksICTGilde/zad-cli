"""Whether this zadctl and the API it talks to still fit together.

The platform decides, not the CLI. Every request says which zadctl sent it
(``User-Agent: zadctl/<version>``), and the Operations Manager answers in one of three ways:

- ``426 Upgrade Required`` when this version is below the minimum it supports. The body
  names the minimum and where to upgrade; the CLI turns that into a :class:`Diagnosis`.
- ``X-ZADCTL-Recommended: <version>`` on an ordinary answer, when this version still works
  but a newer one is advised. Said once per run, on stderr.
- ``/version`` (public) publishes both under ``clients.zadctl``, so ``zadctl login`` can ask
  before it goes to Keycloak: a login never touches the API, and an old version that signs
  in at the wrong realm otherwise fails there with nothing that names the version.

A server that says nothing about it is an older server, and the CLI carries on as before.
Only a version this CLI can read is ever compared: a build from source (``0.0.0+local``)
is not refused on this side.
"""

from __future__ import annotations

import re
from typing import Any

import httpx

from zad_cli import __version__
from zad_cli.api.errors import Diagnosis, Fault

USER_AGENT = f"zadctl/{__version__}"
UPGRADE_URL = "https://github.com/RijksICTGilde/zad-cli#installation"
RECOMMENDED_HEADER = "X-ZADCTL-Recommended"
MINIMUM_HEADER = "X-ZADCTL-Minimum"

_VERSION = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")

# Once per run: one line saying a newer version is advised is information, the same line
# after every request of a playbook is noise.
_recommended_said = False


def headers() -> dict[str, str]:
    """The headers every request from this CLI carries."""
    return {"User-Agent": USER_AGENT}


def parse(version: object) -> tuple[int, int, int] | None:
    """``X.Y.Z`` as a tuple, or None for anything else (a dev build, a typo, nothing)."""
    if not isinstance(version, str):
        return None
    match = _VERSION.match(version.strip())
    return tuple(int(part) for part in match.groups()) if match else None  # type: ignore[return-value]


def below(required: object, current: str = __version__) -> bool:
    """Whether ``current`` is older than ``required``; False whenever either is unreadable."""
    have, want = parse(current), parse(required)
    return have is not None and want is not None and have < want


def web_url(api_url: str) -> str:
    """The host the API lives under, where ``/version`` is served (outside ``/api``)."""
    url = api_url.rstrip("/")
    if url.endswith("/api"):
        url = url[:-4]
    return url.rstrip("/")


def too_old(minimum: object, *, upgrade: object = None, summary: str | None = None) -> Diagnosis:
    """The diagnosis for a zadctl the platform no longer supports."""
    link = upgrade if isinstance(upgrade, str) and upgrade else UPGRADE_URL
    wanted = f", at least {minimum} is needed" if isinstance(minimum, str) and minimum else ""
    return Diagnosis(
        fault=Fault.USER_CONFIG,
        headline=f"zadctl {__version__} is too old for this API{wanted}.",
        summary=summary,
        next_steps=[
            f"Install the latest release: {link}",
            "Check with `zadctl version` that the new one is the one on your PATH.",
        ],
        status_code=426,
    )


def diagnose_426(response: httpx.Response) -> Diagnosis:
    """Read the platform's 426 into a diagnosis; the header backs up a body we cannot read."""
    try:
        body: Any = response.json()
    except ValueError:
        body = {}
    if not isinstance(body, dict):
        body = {}
    minimum = body.get("minimum") or response.headers.get(MINIMUM_HEADER)
    detail = body.get("detail")
    return too_old(minimum, upgrade=body.get("upgrade"), summary=detail if isinstance(detail, str) else None)


def say_recommended(recommended: object) -> None:
    """One line on stderr when a newer version is advised, at most once per run."""
    global _recommended_said
    if _recommended_said or not below(recommended):
        return
    _recommended_said = True
    from zad_cli.output.formatter import err_console

    err_console.print(
        f"[yellow]zadctl {__version__} works, but {recommended} is recommended for this API; "
        f"upgrade: {UPGRADE_URL}[/yellow]"
    )


def note_response(response: httpx.Response) -> None:
    """httpx response hook: pass on the platform's advice, if it gave any."""
    recommended = response.headers.get(RECOMMENDED_HEADER)
    if recommended:
        say_recommended(recommended)


def client_limits(info: object) -> dict[str, Any]:
    """``clients.zadctl`` from a ``/version`` answer, or an empty dict from an older server."""
    clients = info.get("clients") if isinstance(info, dict) else None
    limits = clients.get("zadctl") if isinstance(clients, dict) else None
    return limits if isinstance(limits, dict) else {}


def check_before_login(api_url: str, *, timeout: float = 5.0) -> Diagnosis | None:
    """Ask ``/version`` whether this zadctl is still supported, before signing in.

    Returns the diagnosis when it is not. Anything that stops the question from being
    answered (no network, an older server, an answer without the field) returns None: a
    check that cannot be made must not be what stops someone from signing in.
    """
    from zad_cli.api import registry

    # Offline means: do not reach out for the platform's metadata. The catalog honours it,
    # and so does this, which is also what keeps the test suite off the network.
    if registry.offline():
        return None
    try:
        response = httpx.get(f"{web_url(api_url)}/version", timeout=timeout, follow_redirects=True, headers=headers())
        if response.status_code == 426:
            return diagnose_426(response)
        response.raise_for_status()
        limits = client_limits(response.json())
    except (httpx.HTTPError, ValueError):
        return None
    if below(limits.get("minimum")):
        return too_old(limits.get("minimum"), upgrade=limits.get("upgrade"))
    say_recommended(limits.get("recommended"))
    return None


def _reset() -> None:
    """Forget that the advice was given; for tests, which share one process."""
    global _recommended_said
    _recommended_said = False
