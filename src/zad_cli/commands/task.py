"""Task commands: status, list, wait, cancel."""

from __future__ import annotations

import typer

from zad_cli.helpers import confirm_action, get_helpers, handle_api_errors

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

        $ zad --no-wait project deploy -d staging --component web --image ghcr.io/org/app:v1

        $ zad task wait <task-id>
    """
    client, formatter = get_helpers(ctx)

    result = client._poll_task(f"/tasks/{task_id}")
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
    project: str = typer.Option(None, "--project", help="Filter by project name"),
) -> None:
    """List async tasks."""
    client, formatter = get_helpers(ctx)

    result = client.list_tasks(project=project, status=task_status)
    formatter.render(result)


@app.command()
@handle_api_errors
def cancel(
    ctx: typer.Context,
    task_id: str = typer.Argument(help="Task ID (UUID)"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Cancel a running task."""
    client, formatter = get_helpers(ctx)

    confirm_action(f"Cancel task '{task_id}'?", yes)

    result = client.cancel_task(task_id)
    formatter.render(result)
    formatter.render_success(f"Task '{task_id}' cancelled.")
