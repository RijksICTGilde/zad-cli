"""Global config file at ~/.config/zad/config.toml.

Only stores settings that rarely change (like api_url).
Project-specific values (api_key, project_id) come from env vars.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "zad"
CONFIG_PATH = CONFIG_DIR / "config.toml"


def load() -> dict[str, str]:
    """Load config file. Returns empty dict if missing."""
    if not CONFIG_PATH.exists():
        return {}
    return tomllib.loads(CONFIG_PATH.read_text())


def get(key: str) -> str:
    """Get a single value."""
    return load().get(key, "")


def set_value(key: str, value: str) -> Path:
    """Set a value and save."""
    data = load()
    data[key] = value
    _save(data)
    return CONFIG_PATH


def _save(data: dict[str, str]) -> None:
    """Write config as TOML."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    lines = [f'{k} = "{v}"' for k, v in sorted(data.items())]
    CONFIG_PATH.write_text("\n".join(lines) + "\n")
