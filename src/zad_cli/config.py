"""Global config file at ~/.config/zad/config.toml.

Only stores settings that rarely change (api_url, rollout, the Keycloak environment).
Project-specific values (api_key, project_id) live in the credentials store or in env vars.

The keys are a closed set. A file is a bad place to find out that ``rolout = "false"``
did nothing: nothing reads it, nothing complains, and the behaviour never changes. So an
unknown key is refused at the point where it is written, naming the ones that exist.

The *values* are read back as whatever TOML says they are. ``zad config set`` writes
strings, but this file is documented as editable by hand, and by hand ``rollout = false``
is the natural thing to write. So every reader takes the TOML type it finds, not the one
this module happens to write.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

CONFIG_DIR = Path.home() / ".config" / "zad"
CONFIG_PATH = CONFIG_DIR / "config.toml"

# key -> what it does. The only keys `zad config set` accepts.
KNOWN_KEYS: dict[str, str] = {
    "api_url": "Operations Manager API base URL",
    "rollout": "Roll changes out to the cluster by default (true/false)",
    "keycloak_url": "Keycloak base URL used by `zad login`",
    "keycloak_realm": "Keycloak realm used by `zad login`",
    "keycloak_client_id": "OAuth client `zad login` signs in as",
}


class UnknownConfigKeyError(ValueError):
    """A key that no setting reads was about to be written to the config file."""

    def __init__(self, key: str) -> None:
        super().__init__(f"Unknown config key '{key}'. Valid keys: {', '.join(sorted(KNOWN_KEYS))}")
        self.key = key


def load() -> dict[str, Any]:
    """Load config file. Returns empty dict if missing."""
    if not CONFIG_PATH.exists():
        return {}
    return tomllib.loads(CONFIG_PATH.read_text())


def get(key: str) -> Any:
    """Get a single value, in whatever type the file wrote it."""
    return load().get(key, "")


def as_text(value: Any) -> str:
    """One value as the CLI spells it: TOML booleans included."""
    if isinstance(value, bool):
        return "true" if value else "false"
    return "" if value is None else str(value)


def set_value(key: str, value: str) -> Path:
    """Set a known value and save. Unknown keys are refused, typos included."""
    if key not in KNOWN_KEYS:
        raise UnknownConfigKeyError(key)
    if key == "rollout":
        from zad_cli.settings import parse_bool

        value = "true" if parse_bool(value, name="rollout") else "false"
    if key == "keycloak_url":
        value = _require_url(value)
    data = load()
    data[key] = value
    _save(data)
    return CONFIG_PATH


def _require_url(value: str) -> str:
    """A Keycloak base URL, without the trailing slash that would double up in the issuer."""
    from zad_cli.settings import InvalidSettingError

    text = value.strip()
    if not text.startswith(("http://", "https://")):
        raise InvalidSettingError(f"keycloak_url must start with http:// or https://, got: {value}")
    return text.rstrip("/")


def _quote(value: Any) -> str:
    """A TOML basic string. Backslashes and quotes are escaped, or the file will not parse."""
    text = as_text(value)
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _save(data: dict[str, Any]) -> None:
    """Write config as TOML."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    lines = [f"{k} = {_quote(v)}" for k, v in sorted(data.items())]
    CONFIG_PATH.write_text("\n".join(lines) + "\n")
