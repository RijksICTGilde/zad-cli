"""The `.env.zadctl` in the working directory: the one place this CLI writes.

Everything the CLI remembers lives here, next to the project it belongs to: the API URL,
the active project, its API key, the SSO token and the defaults. There is no file in the
home directory, on purpose.

A single store under ``~`` has one active project, so two terminals in two checkouts fight
over it: the one that logged in last decides what the other one talks to. Keeping the state
next to the code makes directories independent, which is the unit people actually work in.

The file holds secrets, so it is written 0600 and the CLI refuses to be quiet about one that
git would pick up.

**Why not plain `.env`.** That name belongs to whoever got to the directory first: docker
compose, a dotenv loader, a colleague's script. Writing there means editing a shared file and
setting it to 0600, which is a permission change nobody asked for on a file that is not ours,
and it puts an SSO token in the file most likely to be read by something else. `.env.zadctl`
is ours, and it is covered by the near-universal ``.env*`` ignore rule, so the token stays out
of commits without anyone having to think of it.

A `.env` that already carries `ZAD_` variables keeps working exactly as before, reads *and*
writes, because a working setup should not stop working over a rename. It is the one that
gets a recommendation, not a migration.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

ENV_FILENAME = ".env.zadctl"

# What this CLI wrote before it had a name of its own. Still read and still written when it
# is the file in use, so nothing breaks; see `active_is_legacy`.
LEGACY_ENV_FILENAME = ".env"

# Setting name -> the variable it is spelled as. Nothing else is written.
ENV_VARS: dict[str, str] = {
    "api_url": "ZAD_API_URL",
    "api_key": "ZAD_API_KEY",
    "project": "ZAD_PROJECT_ID",
    "token": "ZAD_SSO_TOKEN",
    "refresh_token": "ZAD_SSO_REFRESH_TOKEN",
    "output": "ZAD_OUTPUT_FORMAT",
    "table_style": "ZAD_TABLE_STYLE",
    "rollout": "ZAD_ROLLOUT",
    "yes": "ZAD_YES",
    "keycloak_url": "ZAD_KEYCLOAK_URL",
    "keycloak_realm": "ZAD_KEYCLOAK_REALM",
    "keycloak_client_id": "ZAD_KEYCLOAK_CLIENT_ID",
}

SECRET_VARS = frozenset({"ZAD_API_KEY", "ZAD_SSO_TOKEN", "ZAD_SSO_REFRESH_TOKEN"})


def _read_file(path: Path) -> dict[str, str]:
    """One env file's contents as a mapping. Missing file is an empty one."""
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


def env_path() -> Path:
    """The env file this run reads and writes, in the current directory.

    Three cases, in this order:

    1. `.env.zadctl` exists: that one, always. Making it is how you say you want it.
    2. no `.env.zadctl`, but a `.env` that carries `ZAD_` variables: that one. A setup that
       worked yesterday keeps working, including its writes -- moving someone's stored token
       to a new file behind their back is not an improvement.
    3. neither: `.env.zadctl`, which is what a first write creates.
    """
    cwd = Path.cwd()
    new = cwd / ENV_FILENAME
    if new.exists():
        return new
    legacy = cwd / LEGACY_ENV_FILENAME
    if legacy.exists() and any(key.startswith("ZAD_") for key in _read_file(legacy)):
        return legacy
    return new


def active_is_legacy() -> bool:
    """Whether this run is reading and writing a plain `.env` shared with other tools."""
    return env_path().name == LEGACY_ENV_FILENAME


def shadowed_legacy() -> Path | None:
    """A `.env` with ZAD_ variables that nothing reads, because `.env.zadctl` won.

    Being silent here is how an environment gets switched without anyone noticing: the
    `.env` still looks loaded, and the drift only shows as talking to the wrong API.
    """
    cwd = Path.cwd()
    new = cwd / ENV_FILENAME
    legacy = cwd / LEGACY_ENV_FILENAME
    if new.exists() and legacy.exists() and any(key.startswith("ZAD_") for key in _read_file(legacy)):
        return legacy
    return None


def read() -> dict[str, str]:
    """The active file's contents as a mapping. Missing file is an empty one."""
    return _read_file(env_path())


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
    if path.name == LEGACY_ENV_FILENAME:
        global _wrote_legacy
        _wrote_legacy = True
    return path


_wrote_legacy = False


def legacy_advice() -> str | None:
    """What to say about having just written to a shared `.env`, or None.

    Said after a write rather than on every command: that is the moment it is true and
    actionable, and it is the moment this CLI changed a file it does not own -- including
    its mode, since the file holds a token. A line on every unrelated command would be
    noise, and noise is how a recommendation gets filtered out.
    """
    if not _wrote_legacy:
        return None
    return (
        f"Wrote to {LEGACY_ENV_FILENAME}, which other tools read too, and set it to 0600.\n"
        f"  Recommended: keep zadctl's settings in {ENV_FILENAME} instead. It is covered by\n"
        f"  the usual `.env*` ignore rule, so the token stays out of git.\n"
        f"  Move them with: grep '^ZAD_' {LEGACY_ENV_FILENAME} > {ENV_FILENAME} && "
        f"chmod 600 {ENV_FILENAME}"
    )


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
