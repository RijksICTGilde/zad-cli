"""Shared helpers for command modules."""

from __future__ import annotations

import functools
import sys
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

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
            "Error: ZAD_API_KEY not set.\nSet it in .env, as an environment variable, or pass --api-key.",
            file=sys.stderr,
        )
        raise typer.Exit(1)

    client = ZadClient(
        api_url=settings.api_url,
        api_key=settings.api_key,
        max_retries=settings.max_retries,
        retry_delay=settings.retry_delay,
        task_timeout=settings.task_timeout,
        task_poll_interval=settings.task_poll_interval,
    )
    client.wait = not ctx.obj.get("no_wait", False)
    ctx.obj["client"] = client


def get_helpers(ctx: typer.Context) -> tuple[ZadClient, OutputFormatter]:
    """Get the API client and output formatter from context."""
    _ensure_client(ctx)
    return ctx.obj["client"], ctx.obj["formatter"]


def require_project(ctx: typer.Context) -> str:
    """Get project ID from the global --project flag or ZAD_PROJECT_ID."""
    settings = ctx.obj["settings"]
    if settings.project_id:
        return settings.project_id
    print("Error: project is required. Set ZAD_PROJECT_ID in .env or pass -p.", file=sys.stderr)
    raise typer.Exit(1)


def handle_api_errors(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator that catches API and task errors and renders them via the formatter."""
    from zad_cli.api.client import TaskFailedError, TaskTimeoutError, ZadApiError

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except (ZadApiError, TaskFailedError, TaskTimeoutError) as e:
            ctx = kwargs.get("ctx") or next((a for a in args if isinstance(a, typer.Context)), None)
            formatter = ctx.obj["formatter"] if ctx else None
            details = getattr(e, "details", None)
            if formatter:
                formatter.render_error(str(e), details=details)
            else:
                print(f"Error: {e}", file=sys.stderr)
            raise typer.Exit(1) from e

    return wrapper


def confirm_action(message: str, yes: bool) -> None:
    """Ask for confirmation unless --yes was passed."""
    if not yes:
        typer.confirm(message, abort=True)


def complete_deployment(ctx: typer.Context, incomplete: str) -> list[str]:
    """Autocompletion callback for deployment names."""
    try:
        _ensure_client(ctx)
        client = ctx.obj["client"]
        settings = ctx.obj["settings"]
        if not settings.project_id:
            return []
        deployments = client.list_deployments(settings.project_id)
        return [d["deployment"] for d in deployments if d["deployment"].startswith(incomplete)]
    except Exception:
        return []


def complete_component(ctx: typer.Context, incomplete: str) -> list[str]:
    """Autocompletion callback for component names."""
    try:
        _ensure_client(ctx)
        client = ctx.obj["client"]
        settings = ctx.obj["settings"]
        if not settings.project_id:
            return []
        deployments = client.list_deployments(settings.project_id)
        names: set[str] = set()
        for dep in deployments:
            for comp in dep["components"]:
                if comp.startswith(incomplete):
                    names.add(comp)
        return sorted(names)
    except Exception:
        return []
