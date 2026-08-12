"""Where the CLI keeps the API key and the SSO token: the `.env` in the working directory.

Two kinds of secret live here:

* a **project API key**, which every project-scoped call presents as ``X-API-Key``.
  ``project create`` returns it exactly once and ``project list`` returns it for projects
  the caller administers, so the CLI stores it rather than making the user copy it out of
  a response.
* the **SSO access token**, which only ``project list`` and ``project create`` use;
  they are the two calls that cannot present a project key, because you need the project
  name before you can have its key.

Both go in the same `.env` as the rest of the settings, next to the project they belong to.
There is no store under ``~``: a single shared file has one active project, and two
terminals in two checkouts then fight over which project the other one is talking to.

See :mod:`zad_cli.envfile` for the file itself, including its 0600 mode.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from zad_cli.envfile import ENV_VARS
from zad_cli.envfile import get as env_get
from zad_cli.envfile import write as env_write


def redact(value: str | None) -> str:
    """A secret as it may appear on screen: enough to recognise, not enough to use."""
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}{'*' * 8}{value[-2:]}"


def store_api_key(project: str, api_key: str) -> Path:
    """Remember the API key, and which project it belongs to.

    One directory means one project, so the key is not filed under a name: writing it
    together with the project it belongs to is what keeps the two from drifting apart.
    """
    return env_write({ENV_VARS["project"]: project, ENV_VARS["api_key"]: api_key})


def get_api_key(project: str | None = None) -> str | None:
    """The stored API key, environment first so a script can be explicit.

    ``project`` is accepted and ignored: the key in this directory belongs to the project
    in this directory. It stays in the signature so callers read as what they mean.
    """
    return os.environ.get(ENV_VARS["api_key"]) or env_get(ENV_VARS["api_key"]) or None


def store_token(token: str, refresh_token: str = "") -> Path:
    """Remember the SSO access token, and the refresh token that renews it."""
    updates: dict[str, str | None] = {ENV_VARS["token"]: token}
    if refresh_token:
        updates[ENV_VARS["refresh_token"]] = refresh_token
    return env_write(updates)


def get_refresh_token() -> str | None:
    return os.environ.get(ENV_VARS["refresh_token"]) or env_get(ENV_VARS["refresh_token"]) or None


def get_token(*, issuer: str = "", client_id: str = "") -> str | None:
    """The SSO access token, renewed first when it has expired.

    ``ZAD_SSO_TOKEN`` in the environment lets CI hand a token in without a login round
    trip, and works where the browser flow is not available. That one is used as given:
    a token someone passed in explicitly is theirs to manage.

    The stored one is renewed silently when it is past its `exp` and a refresh token is
    there. The access token lives five minutes on this platform, so without this every
    command a few minutes after signing in would ask you to sign in again.
    """
    from_env = os.environ.get(ENV_VARS["token"])
    if from_env:
        return from_env

    token = env_get(ENV_VARS["token"]) or None
    if not token or not issuer or not client_id:
        return token

    from zad_cli import auth

    exp = auth.expires_at(token)
    # A minute of slack: a token that expires while the request is in flight is as useless
    # as one that expired a minute ago.
    if not exp or exp - 60 > int(time.time()):
        return token

    refresh_token = get_refresh_token()
    if not refresh_token:
        return token
    try:
        token, refresh_token = auth.refresh(issuer, client_id, refresh_token)
    except Exception:  # noqa: BLE001 - a spent refresh token means signing in again, not crashing
        return token
    store_token(token, refresh_token)
    return token


def set_active_project(project: str) -> Path:
    """Record which project the CLI acts on in this directory."""
    return env_write({ENV_VARS["project"]: project})


def get_active_project() -> str | None:
    return os.environ.get(ENV_VARS["project"]) or env_get(ENV_VARS["project"]) or None


def forget_project() -> Path:
    """Forget the active project and its key, keeping the sign-in.

    For a project that no longer exists. Leaving its name and key behind points every
    later command at something deleted, and the 401 that follows reads like a credentials
    problem rather than the plain fact that the project is gone. The SSO token stays: you
    are still signed in, and `zad project list` is the natural next command.
    """
    return env_write({ENV_VARS["api_key"]: None, ENV_VARS["project"]: None})


def clear() -> Path:
    """Forget the token, the key and the project. Settings are left alone."""
    return env_write(
        {
            ENV_VARS["token"]: None,
            ENV_VARS["refresh_token"]: None,
            ENV_VARS["api_key"]: None,
            ENV_VARS["project"]: None,
        }
    )
