"""Settings the CLI remembers, written to the `.env` in the working directory.

There is no config file under ``~``: see :mod:`zad_cli.envfile` for why. This module is the
named-setting layer on top of it, so ``zadctl config set rollout false`` writes ``ZAD_ROLLOUT``
and not a key nothing reads.

The keys are a closed set. A file is a bad place to find out that ``ZAD_ROLOUT=false`` did
nothing: nothing reads it, nothing complains, and the behaviour never changes. So an unknown
key is refused at the point where it is written, naming the ones that exist.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from zad_cli.envfile import ENV_VARS, env_path
from zad_cli.envfile import get as env_get
from zad_cli.envfile import write as env_write

# key -> what it does. The only keys `zadctl config set` accepts.
KNOWN_KEYS: dict[str, str] = {
    "api_url": "Operations Manager API base URL",
    "output": "Default output format: table, json or yaml",
    "table_style": "How tables are drawn: lines, ascii or plain",
    "rollout": "Roll changes out to the cluster by default (true/false)",
    "yes": "Answer confirmation prompts with yes by default (true/false)",
    "keycloak_url": "Keycloak base URL used by `zadctl login`",
    "keycloak_realm": "Keycloak realm used by `zadctl login`",
    "keycloak_client_id": "OAuth client `zadctl login` signs in as",
}


class UnknownConfigKeyError(ValueError):
    """A key that no setting reads was about to be written to the .env file."""

    def __init__(self, key: str) -> None:
        super().__init__(f"Unknown config key '{key}'. Valid keys: {', '.join(sorted(KNOWN_KEYS))}")
        self.key = key


def path() -> Path:
    """Where settings are written: the .env in the current directory."""
    return env_path()


def get(key: str) -> str:
    """One setting, read from the .env file."""
    var = ENV_VARS.get(key)
    return env_get(var) if var else ""


def as_text(value: Any) -> str:
    """One value as the CLI spells it."""
    if isinstance(value, bool):
        return "true" if value else "false"
    return "" if value is None else str(value)


def set_value(key: str, value: str) -> Path:
    """Set a known setting and save. Unknown keys are refused, typos included."""
    if key not in KNOWN_KEYS:
        raise UnknownConfigKeyError(key)
    if key in ("rollout", "yes"):
        from zad_cli.settings import parse_bool

        value = "true" if parse_bool(value, name=key) else "false"
    if key == "output":
        value = _require_output_format(value)
    if key == "keycloak_url":
        value = _require_url(value)
    return env_write({ENV_VARS[key]: value})


def unset(key: str) -> Path:
    """Remove a setting, so the layer below it decides again."""
    if key not in KNOWN_KEYS:
        raise UnknownConfigKeyError(key)
    return env_write({ENV_VARS[key]: None})


def _require_output_format(value: str) -> str:
    """One of the formats the formatter can actually render.

    Caught here rather than at render time: this file is written once and read on every
    later run, so a typo would otherwise fail somewhere far away from where it was made.
    """
    from zad_cli.settings import VALID_OUTPUT_FORMATS, InvalidSettingError

    text = value.strip().lower()
    if text not in VALID_OUTPUT_FORMATS:
        raise InvalidSettingError(f"output must be one of {', '.join(sorted(VALID_OUTPUT_FORMATS))}, got: {value}")
    return text


def _require_url(value: str) -> str:
    """A Keycloak base URL, without the trailing slash that would double up in the issuer."""
    from zad_cli.settings import InvalidSettingError

    text = value.strip()
    if not text.startswith(("http://", "https://")):
        raise InvalidSettingError(f"keycloak_url must start with http:// or https://, got: {value}")
    return text.rstrip("/")
