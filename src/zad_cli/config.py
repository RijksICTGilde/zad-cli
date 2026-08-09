"""Global config file at ~/.config/zad/config.toml.

Only stores settings that rarely change (api_url, rollout). Project-specific values
(api_key, project_id) live in the credentials store or in env vars.

The keys are a closed set. A file is a bad place to find out that ``rolout = "false"``
did nothing: nothing reads it, nothing complains, and the behaviour never changes. So an
unknown key is refused at the point where it is written, naming the ones that exist.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "zad"
CONFIG_PATH = CONFIG_DIR / "config.toml"

# key -> what it does. The only keys `zad config set` accepts.
KNOWN_KEYS: dict[str, str] = {
    "api_url": "Operations Manager API base URL",
    "rollout": "Roll changes out to the cluster by default (true/false)",
}


class UnknownConfigKeyError(ValueError):
    """A key that no setting reads was about to be written to the config file."""

    def __init__(self, key: str) -> None:
        super().__init__(f"Unknown config key '{key}'. Valid keys: {', '.join(sorted(KNOWN_KEYS))}")
        self.key = key


def load() -> dict[str, str]:
    """Load config file. Returns empty dict if missing."""
    if not CONFIG_PATH.exists():
        return {}
    return tomllib.loads(CONFIG_PATH.read_text())


def get(key: str) -> str:
    """Get a single value."""
    return load().get(key, "")


def set_value(key: str, value: str) -> Path:
    """Set a known value and save. Unknown keys are refused, typos included."""
    if key not in KNOWN_KEYS:
        raise UnknownConfigKeyError(key)
    if key == "rollout":
        from zad_cli.settings import parse_bool

        value = "true" if parse_bool(value, name="rollout") else "false"
    data = load()
    data[key] = value
    _save(data)
    return CONFIG_PATH


def _save(data: dict[str, str]) -> None:
    """Write config as TOML."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    lines = [f'{k} = "{v}"' for k, v in sorted(data.items())]
    CONFIG_PATH.write_text("\n".join(lines) + "\n")
