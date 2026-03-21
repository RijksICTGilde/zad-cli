"""Configuration hierarchy: CLI flags > env vars (ZAD_*) > config file > defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass

from zad_cli.config.context import DEFAULTS, get_context


@dataclass
class Settings:
    """Resolved settings from all sources."""

    api_url: str
    api_key: str
    output_format: str
    task_timeout: int
    task_poll_interval: int
    max_retries: int
    retry_delay: int

    @classmethod
    def resolve(
        cls,
        *,
        api_url: str | None = None,
        api_key: str | None = None,
        output_format: str | None = None,
        context: str | None = None,
    ) -> Settings:
        """Resolve settings: CLI flags > env vars > config file > defaults."""
        ctx = get_context(context)

        return cls(
            api_url=api_url or os.environ.get("ZAD_API_URL") or ctx.get("api_url", DEFAULTS["api_url"]),
            api_key=api_key or os.environ.get("ZAD_API_KEY") or "",
            output_format=output_format or os.environ.get("ZAD_OUTPUT_FORMAT") or ctx.get("output_format", "table"),
            task_timeout=int(
                os.environ.get("ZAD_TASK_TIMEOUT", 0) or ctx.get("task_timeout", DEFAULTS["task_timeout"])
            ),
            task_poll_interval=int(
                os.environ.get("ZAD_TASK_POLL_INTERVAL", 0)
                or ctx.get("task_poll_interval", DEFAULTS["task_poll_interval"])
            ),
            max_retries=int(os.environ.get("ZAD_MAX_RETRIES", 0) or ctx.get("max_retries", DEFAULTS["max_retries"])),
            retry_delay=int(os.environ.get("ZAD_RETRY_DELAY", 0) or ctx.get("retry_delay", DEFAULTS["retry_delay"])),
        )
