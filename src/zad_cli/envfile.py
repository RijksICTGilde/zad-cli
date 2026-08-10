"""The `.env` in the working directory: the one place this CLI writes.

Everything the CLI remembers lives here, next to the project it belongs to: the API URL,
the active project, its API key, the SSO token and the defaults. There is no file in the
home directory, on purpose.

A single store under ``~`` has one active project, so two terminals in two checkouts fight
over it: the one that logged in last decides what the other one talks to. Keeping the state
next to the code makes directories independent, which is the unit people actually work in.

The file holds secrets, so it is written 0600 and the CLI refuses to be quiet about a `.env`
that git would pick up.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

ENV_FILENAME = ".env"

# Setting name -> the variable it is spelled as. Nothing else is written.
ENV_VARS: dict[str, str] = {
    "api_url": "ZAD_API_URL",
    "api_key": "ZAD_API_KEY",
    "project": "ZAD_PROJECT_ID",
    "token": "ZAD_SSO_TOKEN",
    "refresh_token": "ZAD_SSO_REFRESH_TOKEN",
    "output": "ZAD_OUTPUT_FORMAT",
    "rollout": "ZAD_ROLLOUT",
    "yes": "ZAD_YES",
    "keycloak_url": "ZAD_KEYCLOAK_URL",
    "keycloak_realm": "ZAD_KEYCLOAK_REALM",
    "keycloak_client_id": "ZAD_KEYCLOAK_CLIENT_ID",
}

SECRET_VARS = frozenset({"ZAD_API_KEY", "ZAD_SSO_TOKEN", "ZAD_SSO_REFRESH_TOKEN"})


def env_path() -> Path:
    """The .env this run reads and writes: the one in the current directory."""
    return Path.cwd() / ENV_FILENAME


def read() -> dict[str, str]:
    """The file's contents as a mapping. Missing file is an empty one."""
    path = env_path()
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip("\"'")
    return values


def get(var: str) -> str:
    """One variable from the file. The environment is read by settings, not here."""
    return read().get(var, "")


def write(updates: dict[str, str | None]) -> Path:
    """Set or remove variables, keeping the rest of the file as it is.

    A value of ``None`` removes the line. Comments and unknown variables are preserved:
    this file is the user's, the CLI only edits the lines it owns.
    """
    path = env_path()
    lines = path.read_text().splitlines() if path.exists() else []
    remaining = dict(updates)

    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        key = stripped.partition("=")[0].strip() if "=" in stripped and not stripped.startswith("#") else None
        if key in remaining:
            value = remaining.pop(key)
            if value is not None:
                out.append(f"{key}={value}")
            # None drops the line entirely.
            continue
        out.append(line)

    for key, value in remaining.items():
        if value is not None:
            out.append(f"{key}={value}")

    path.write_text("\n".join(out).rstrip("\n") + "\n")
    # It holds an API key and an access token; nobody else on the machine needs to read it.
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    return path


LEGACY_DIR = Path.home() / ".config" / "zad"


def legacy_files() -> list[Path]:
    """The files a previous version wrote under ~, if they are still there.

    They are no longer read. Saying so once beats letting someone watch a stored API key
    stop working with no explanation, which is exactly what silence looks like from the
    other side.
    """
    return [p for p in (LEGACY_DIR / "config.toml", LEGACY_DIR / "credentials.toml") if p.exists()]


def is_git_ignored() -> bool | None:
    """Whether git would ignore this .env. ``None`` when there is no git to ask."""
    import subprocess

    try:
        result = subprocess.run(
            ["git", "check-ignore", "-q", str(env_path())],
            capture_output=True,
            cwd=str(Path.cwd()),
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode in (0, 1):
        return result.returncode == 0
    return None
