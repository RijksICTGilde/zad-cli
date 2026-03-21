"""Context/profile management for ~/.zad/config.yml.

Config file format:

    current-context: production
    contexts:
      production:
        api_url: https://operations-manager.rig.prd1.gn2.quattro.rijksapps.nl/api
        output_format: table
"""

from pathlib import Path

import yaml

CONFIG_PATH = Path.home() / ".zad" / "config.yml"

DEFAULTS = {
    "api_url": "https://operations-manager.rig.prd1.gn2.quattro.rijksapps.nl/api",
    "output_format": "table",
    "task_timeout": 300,
    "task_poll_interval": 3,
    "max_retries": 3,
    "retry_delay": 2,
}


def _load_raw() -> dict:
    """Load raw config file."""
    if CONFIG_PATH.exists():
        return yaml.safe_load(CONFIG_PATH.read_text()) or {}
    return {}


def _save_raw(data: dict) -> Path:
    """Save raw config to disk."""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))
    return CONFIG_PATH


def get_current_context_name() -> str:
    """Get the name of the active context."""
    data = _load_raw()
    return data.get("current-context", "default")


def get_context(name: str | None = None) -> dict:
    """Get settings for a context, merged with defaults."""
    data = _load_raw()
    context_name = name or data.get("current-context", "default")
    contexts = data.get("contexts", {})
    context_data = contexts.get(context_name, {})
    return {**DEFAULTS, **context_data}


def set_context(name: str) -> Path:
    """Set the active context."""
    data = _load_raw()
    data["current-context"] = name
    return _save_raw(data)


def list_contexts() -> list[str]:
    """List available context names."""
    data = _load_raw()
    contexts = data.get("contexts", {})
    return sorted(contexts.keys()) if contexts else ["default"]


def set_value(key: str, value: str, context_name: str | None = None) -> Path:
    """Set a value in a context."""
    data = _load_raw()
    context_name = context_name or data.get("current-context", "default")

    if "contexts" not in data:
        data["contexts"] = {}
    if context_name not in data["contexts"]:
        data["contexts"][context_name] = {}

    if key in ("task_timeout", "task_poll_interval", "max_retries", "retry_delay"):
        data["contexts"][context_name][key] = int(value)
    else:
        data["contexts"][context_name][key] = value

    return _save_raw(data)


def get_value(key: str, context_name: str | None = None) -> str:
    """Get a single value from a context."""
    ctx = get_context(context_name)
    return str(ctx.get(key, DEFAULTS.get(key, "")))
