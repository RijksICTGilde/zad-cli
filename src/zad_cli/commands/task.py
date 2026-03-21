"""Task commands: status, list, cancel."""

from __future__ import annotations

import typer

from zad_cli.api.client import ZadApiError
from zad_cli.helpers import get_helpers

app = typer.Typer(help="Manage async tasks.", no_args_is_help=True)


@app.command()
def status(
    ctx: typer.Context,
    task_id: str = typer.Argument(help="Task ID (UUID)"),
) -> None:
    """Show the current status of an async task."""
    client, formatter = get_helpers(ctx)

    try:
        result = client.get_task(task_id)
        formatter.render(result)
    except ZadApiError as e:
        formatter.render_error(str(e))
        raise typer.Exit(1) from e


@app.command("list")
def list_tasks(
    ctx: typer.Context,
    task_status: str = typer.Option(None, "--status", "-s", help="Filter: pending, running, completed, failed"),
    project: str = typer.Option(None, "--project", help="Filter by project name"),
) -> None:
    """List async tasks."""
    client, formatter = get_helpers(ctx)

    try:
        result = client.list_tasks(project=project, status=task_status)
        formatter.render(result)
    except ZadApiError as e:
        formatter.render_error(str(e))
        raise typer.Exit(1) from e


@app.command()
def cancel(
    ctx: typer.Context,
    task_id: str = typer.Argument(help="Task ID (UUID)"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Cancel a running task."""
    client, formatter = get_helpers(ctx)

    if not yes:
        typer.confirm(f"Cancel task '{task_id}'?", abort=True)

    try:
        result = client.cancel_task(task_id)
        formatter.render(result)
        formatter.render_success(f"Task '{task_id}' cancelled.")
    except ZadApiError as e:
        formatter.render_error(str(e))
        raise typer.Exit(1) from e
