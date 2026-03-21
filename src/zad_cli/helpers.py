"""Shared helpers for command modules."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import typer

if TYPE_CHECKING:
    from zad_cli.api.client import ZadClient
    from zad_cli.output.formatter import OutputFormatter


def _ensure_client(ctx: typer.Context) -> None:
    """Lazily create the API client when first needed."""
    if ctx.obj.get("client"):
        return

    from zad_cli.api.client import ZadClient

    settings = ctx.obj["settings"]
    if not settings.api_key:
        print(
            "Error: ZAD_API_KEY not set.\nSet it in your environment, .env file, or pass --api-key.",
            file=sys.stderr,
        )
        raise typer.Exit(1)

    ctx.obj["client"] = ZadClient(
        api_url=settings.api_url,
        api_key=settings.api_key,
        max_retries=settings.max_retries,
        retry_delay=settings.retry_delay,
        task_timeout=settings.task_timeout,
        task_poll_interval=settings.task_poll_interval,
    )


def get_helpers(ctx: typer.Context) -> tuple[ZadClient, OutputFormatter]:
    """Get the API client and output formatter from context."""
    _ensure_client(ctx)
    return ctx.obj["client"], ctx.obj["formatter"]


def require_project(ctx: typer.Context) -> str:
    """Get project ID from the global --project flag or ZAD_PROJECT_ID."""
    settings = ctx.obj["settings"]
    if settings.project_id:
        return settings.project_id
    print("Error: project is required. Set ZAD_PROJECT_ID or pass --project/-p.", file=sys.stderr)
    raise typer.Exit(1)
