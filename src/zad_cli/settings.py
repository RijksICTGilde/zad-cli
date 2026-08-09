"""Settings resolved from CLI flags > env vars / .env > config file > defaults.

Precedence (highest wins):
  1. CLI flags (--api-key, --api-url, -p, -o, --rollout/--no-rollout)
  2. Environment variables / .env file (ZAD_API_KEY, ZAD_API_URL, ZAD_PROJECT_ID, ZAD_ROLLOUT)
  3. Credentials store (~/.config/zad/credentials.toml): the active project and its key
  4. Config file (~/.config/zad/config.toml): api_url, rollout
  5. Built-in defaults

Every setting also records *where* its value came from, in ``Settings.sources``, so
``zad config list`` can say why the CLI behaves the way it does instead of only what it
is doing.

.env is loaded at CLI startup via python-dotenv.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field

from zad_cli.config import get as config_get

DEFAULT_API_URL = "https://operations-manager.rig.prd1.gn2.quattro.rijksapps.nl/api"

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


class InvalidSettingError(ValueError):
    """A setting was given a value it cannot have."""


def parse_bool(raw: str, *, name: str) -> bool:
    """Read a boolean the way a config file and an environment variable both write one."""
    value = raw.strip().lower()
    if value in _TRUE:
        return True
    if value in _FALSE:
        return False
    raise InvalidSettingError(f"{name} must be true or false, got: {raw}")


def _int_env(name: str, default: int) -> int:
    """Read an integer from an environment variable with a clear error on invalid values."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        print(f"Error: {name} must be an integer, got: {raw}", file=sys.stderr)
        raise SystemExit(1) from None


def _first(*candidates: tuple[str, object | None]) -> tuple[object | None, str]:
    """The first candidate that has a value, and the name of where it came from."""
    for source, value in candidates:
        if value is not None and value != "":
            return value, source
    return None, "default"


@dataclass
class Settings:
    """Resolved settings."""

    api_url: str
    api_key: str
    project_id: str
    output_format: str
    verbose: bool = False
    rollout: bool = True
    task_timeout: int = 300
    task_poll_interval: int = 3
    max_retries: int = 3
    retry_delay: int = 2
    # setting name -> "flag", "env", "credentials", "config" or "default"
    sources: dict[str, str] = field(default_factory=dict)

    @classmethod
    def resolve(
        cls,
        *,
        api_url: str | None = None,
        api_key: str | None = None,
        project_id: str | None = None,
        output_format: str | None = None,
        verbose: bool = False,
        rollout: bool | None = None,
    ) -> Settings:
        # The credentials store is below flags and the environment: `zad project use`
        # records a default, it does not override a script that was explicit about which
        # project it means.
        from zad_cli import credentials

        resolved_project, project_source = _first(
            ("flag", project_id),
            ("env", os.environ.get("ZAD_PROJECT_ID")),
            ("credentials", credentials.get_active_project()),
        )
        project = str(resolved_project or "")

        resolved_key, key_source = _first(
            ("flag", api_key),
            ("env", os.environ.get("ZAD_API_KEY")),
            ("credentials", credentials.get_api_key(project) if project else None),
        )

        resolved_url, url_source = _first(
            ("flag", api_url),
            ("env", os.environ.get("ZAD_API_URL")),
            ("config", config_get("api_url")),
        )

        resolved_output, output_source = _first(
            ("flag", output_format),
            ("env", os.environ.get("ZAD_OUTPUT_FORMAT")),
        )

        # bool | None, not bool: "the user typed --rollout" and "nobody said anything"
        # have to stay distinguishable, or the flag would always beat the config file.
        env_rollout = os.environ.get("ZAD_ROLLOUT")
        config_rollout = config_get("rollout")
        try:
            if rollout is not None:
                resolved_rollout, rollout_source = rollout, "flag"
            elif env_rollout:
                resolved_rollout, rollout_source = parse_bool(env_rollout, name="ZAD_ROLLOUT"), "env"
            elif config_rollout:
                resolved_rollout, rollout_source = (
                    parse_bool(config_rollout, name="rollout in the config file"),
                    "config",
                )
            else:
                resolved_rollout, rollout_source = True, "default"
        except InvalidSettingError as e:
            print(f"Error: {e}", file=sys.stderr)
            raise SystemExit(1) from None

        return cls(
            api_url=str(resolved_url or DEFAULT_API_URL),
            api_key=str(resolved_key or ""),
            project_id=project,
            output_format=str(resolved_output or "table"),
            verbose=verbose,
            rollout=resolved_rollout,
            task_timeout=_int_env("ZAD_TASK_TIMEOUT", 300),
            task_poll_interval=_int_env("ZAD_TASK_POLL_INTERVAL", 3),
            max_retries=_int_env("ZAD_MAX_RETRIES", 3),
            retry_delay=_int_env("ZAD_RETRY_DELAY", 2),
            sources={
                "api_url": url_source,
                "api_key": key_source,
                "project": project_source,
                "output": output_source,
                "rollout": rollout_source,
            },
        )
