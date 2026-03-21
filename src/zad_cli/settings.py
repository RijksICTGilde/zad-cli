"""Settings resolved from CLI flags > env vars / .env > config file > defaults.

Precedence (highest wins):
  1. CLI flags (--api-key, --api-url, -p, -o)
  2. Environment variables / .env file (ZAD_API_KEY, ZAD_API_URL, ZAD_PROJECT_ID)
  3. Config file (~/.config/zad/config.toml) - only for api_url
  4. Built-in defaults

.env is loaded at CLI startup via python-dotenv.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from zad_cli.config import get as config_get

DEFAULT_API_URL = "https://operations-manager.rig.prd1.gn2.quattro.rijksapps.nl/api"


@dataclass
class Settings:
    """Resolved settings."""

    api_url: str
    api_key: str
    project_id: str
    output_format: str
    verbose: bool = False
    task_timeout: int = 300
    task_poll_interval: int = 3
    max_retries: int = 3
    retry_delay: int = 2

    @classmethod
    def resolve(
        cls,
        *,
        api_url: str | None = None,
        api_key: str | None = None,
        project_id: str | None = None,
        output_format: str | None = None,
        verbose: bool = False,
    ) -> Settings:
        return cls(
            api_url=api_url or os.environ.get("ZAD_API_URL") or config_get("api_url") or DEFAULT_API_URL,
            api_key=api_key or os.environ.get("ZAD_API_KEY") or "",
            project_id=project_id or os.environ.get("ZAD_PROJECT_ID") or "",
            output_format=output_format or os.environ.get("ZAD_OUTPUT_FORMAT") or "table",
            verbose=verbose,
        )
