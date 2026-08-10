"""Where the CLI keeps API keys and the SSO token.

Two kinds of secret live here:

* a **project API key**, one per project, which every project-scoped call presents as
  ``X-API-Key``. ``project create`` returns it exactly once and ``project list`` returns
  it for projects the caller administers, so the CLI stores it rather than making the
  user copy it out of a response.
* the **SSO access token**, which only ``project list`` and ``project create`` use;
  they are the two calls that cannot present a project key, because you need the project
  name before you can have its key.

The file is ``~/.config/zad/credentials.toml`` with mode 0600, written atomically. An OS
keyring is used when one is available, with the file as the fallback; the file is not a
lesser mode, it is what makes this work on a CI runner and in a container.
"""

from __future__ import annotations

import os
import stat
import tomllib
from dataclasses import dataclass
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "zad"
CREDENTIALS_PATH = CONFIG_DIR / "credentials.toml"

KEYRING_SERVICE = "zad-cli"

# What a secret looks like once it is not the secret any more.
REDACTED = "********"


def redact(value: str | None) -> str:
    """Mask a secret for display or logging, keeping just enough to recognise it."""
    if not value:
        return ""
    if len(value) <= 8:
        return REDACTED
    return f"{value[:4]}{REDACTED}{value[-2:]}"


@dataclass
class Credentials:
    """The contents of the credentials file."""

    api_keys: dict[str, str]
    token: str | None = None
    active_project: str | None = None


def _keyring():
    """The keyring module, when it is installed and usable."""
    try:
        import keyring  # type: ignore[import-not-found]

        keyring.get_keyring()
        return keyring
    except Exception:
        return None


def _quote(value: str) -> str:
    """TOML basic string, escaping what must be escaped."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def load() -> Credentials:
    """Read the credentials file; an absent or unreadable file means no credentials."""
    if not CREDENTIALS_PATH.exists():
        return Credentials(api_keys={})
    try:
        data = tomllib.loads(CREDENTIALS_PATH.read_text())
    except (OSError, tomllib.TOMLDecodeError):
        return Credentials(api_keys={})
    projects = data.get("projects") or {}
    return Credentials(
        api_keys={name: str(entry.get("api_key", "")) for name, entry in projects.items() if isinstance(entry, dict)},
        token=data.get("token") or None,
        active_project=data.get("active_project") or None,
    )


def save(credentials: Credentials) -> Path:
    """Write the credentials file with 0600, replacing it atomically.

    Written to a temporary file in the same directory and renamed, so a crash halfway
    never leaves a truncated file, and the mode is set before any secret is in it.
    """
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    lines: list[str] = ["# Written by zad-cli. Contains secrets; keep mode 0600.", ""]
    if credentials.token:
        lines.append(f"token = {_quote(credentials.token)}")
    if credentials.active_project:
        lines.append(f"active_project = {_quote(credentials.active_project)}")
    for name in sorted(credentials.api_keys):
        key = credentials.api_keys[name]
        if not key:
            continue
        lines += ["", f"[projects.{name}]", f"api_key = {_quote(key)}"]

    temp = CREDENTIALS_PATH.with_suffix(".toml.tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, stat.S_IRUSR | stat.S_IWUSR)
    with os.fdopen(fd, "w") as handle:
        handle.write("\n".join(lines) + "\n")
    os.replace(temp, CREDENTIALS_PATH)
    os.chmod(CREDENTIALS_PATH, stat.S_IRUSR | stat.S_IWUSR)
    return CREDENTIALS_PATH


def store_api_key(project: str, api_key: str) -> Path:
    """Remember a project's API key, in the keyring when there is one."""
    keyring = _keyring()
    if keyring is not None:
        try:
            keyring.set_password(KEYRING_SERVICE, f"project:{project}", api_key)
        except Exception:
            keyring = None
    credentials = load()
    if keyring is None:
        credentials.api_keys[project] = api_key
    else:
        # Recorded without the secret, so `config list` can still say we know this project.
        credentials.api_keys.setdefault(project, "")
    return save(credentials)


def get_api_key(project: str) -> str | None:
    """The stored API key for a project, keyring first."""
    keyring = _keyring()
    if keyring is not None:
        try:
            found = keyring.get_password(KEYRING_SERVICE, f"project:{project}")
            if found:
                return found
        except Exception:
            pass
    return load().api_keys.get(project) or None


def store_token(token: str) -> Path:
    """Remember the SSO access token."""
    credentials = load()
    credentials.token = token
    return save(credentials)


def get_token() -> str | None:
    """The SSO access token: environment first, then the credentials file.

    ``ZAD_SSO_TOKEN`` exists so CI can hand a token in without a login round trip, and so
    the token-only commands work on a platform where the browser flow is not available.
    """
    return os.environ.get("ZAD_SSO_TOKEN") or load().token


def set_active_project(project: str) -> Path:
    """Record which project the CLI acts on when -p and ZAD_PROJECT_ID are absent."""
    credentials = load()
    credentials.active_project = project
    return save(credentials)


def get_active_project() -> str | None:
    return load().active_project


def clear() -> Path:
    """Forget everything: token, active project and every stored key."""
    keyring = _keyring()
    credentials = load()
    if keyring is not None:
        import contextlib

        for project in credentials.api_keys:
            with contextlib.suppress(Exception):
                keyring.delete_password(KEYRING_SERVICE, f"project:{project}")
    return save(Credentials(api_keys={}))
