"""Task commands: status, list, wait, cancel."""

from __future__ import annotations

import typer

from zad_cli.helpers import get_helpers, handle_api_errors, render_dry_run

app = typer.Typer(help="Manage async tasks.", no_args_is_help=True)


@app.command()
@handle_api_errors
def wait(
    ctx: typer.Context,
    task_id: str = typer.Argument(help="Task ID (UUID)"),
) -> None:
    """Wait for an async task to complete.

    Blocks until the task finishes, showing a progress spinner.
    Useful after running a command with --no-wait.

    [bold]Example:[/bold]

        $ zadctl --no-wait deployment create staging --component web --image ghcr.io/org/app:v1

        $ zadctl task wait <task-id>
    """
    client, formatter = get_helpers(ctx)

    result = client.wait_for_task(task_id)
    formatter.render(result)
    formatter.render_success(f"Task '{task_id}' completed.")


@app.command()
@handle_api_errors
def status(
    ctx: typer.Context,
    task_id: str = typer.Argument(help="Task ID (UUID)"),
) -> None:
    """Show the current status of an async task."""
    client, formatter = get_helpers(ctx)

    result = client.get_task(task_id)
    formatter.render(result)


@app.command("list")
@handle_api_errors
def list_tasks(
    ctx: typer.Context,
    task_status: str = typer.Option(None, "--status", "-s", help="Filter: pending, running, completed, failed"),
    project_name: str = typer.Option(None, "--filter-project", help="Filter by project name"),
) -> None:
    """List async tasks."""
    client, formatter = get_helpers(ctx)

    result = client.list_tasks(project=project_name, status=task_status)
    formatter.render(result)


@app.command()
@handle_api_errors
def cancel(
    ctx: typer.Context,
    task_id: str = typer.Argument(help="Task ID (UUID)"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be sent without making the API call"),
) -> None:
    """Cancel a running task.

    [bold]Example:[/bold]

        $ zadctl task cancel 4afb5e44-e31c-48c0-a23e-c2098ea323f5
    """
    client, formatter = get_helpers(ctx)

    if dry_run:
        render_dry_run(formatter, "POST", f"/tasks/{task_id}/cancel")
        return

    result = client.cancel_task(task_id)
    formatter.render(result)
    formatter.render_success(f"Task '{task_id}' cancelled.")
