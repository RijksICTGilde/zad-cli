"""Backup commands: create, list, status, delete, namespace, database, bucket."""

from __future__ import annotations

import typer

from zad_cli.helpers import confirm_action, get_helpers, handle_api_errors, render_dry_run, require_project

app = typer.Typer(
    help="Manage backups.\n\nMost commands require ZAD_API_KEY and ZAD_PROJECT_ID (or --api-key and -p).",
    no_args_is_help=True,
)


@app.command()
@handle_api_errors
def create(
    ctx: typer.Context,
    deployment: str = typer.Argument(help="Deployment name"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be sent without making the API call"),
) -> None:
    """Create a backup of a project deployment.

    [bold]Example:[/bold]

        $ zad backup create staging
    """
    project = require_project(ctx)
    client, formatter = get_helpers(ctx)

    if dry_run:
        render_dry_run(formatter, "POST", f"/v1/backup/project/{project}/deployment/{deployment}")
        return

    result = client.backup_project(project, deployment)
    formatter.render(result)
    formatter.render_success(f"Backup created for {project}/{deployment}.")


@app.command("list")
@handle_api_errors
def list_runs(
    ctx: typer.Context,
    deployment: str = typer.Argument(help="Deployment name"),
) -> None:
    """List backup runs for a deployment."""
    project = require_project(ctx)
    client, formatter = get_helpers(ctx)

    result = client.list_backup_runs(project, deployment)
    formatter.render(result)


@app.command()
@handle_api_errors
def status(ctx: typer.Context) -> None:
    """Show backup system status."""
    client, formatter = get_helpers(ctx)

    result = client.backup_status()
    formatter.render(result)


@app.command("delete")
@handle_api_errors
def delete_snapshot(
    ctx: typer.Context,
    deployment: str = typer.Argument(help="Deployment name"),
    snapshot_id: str = typer.Argument(help="Snapshot ID"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be sent without making the API call"),
) -> None:
    """Delete a backup snapshot.

    [bold]Example:[/bold]

        $ zad backup delete staging snap-123
    """
    project = require_project(ctx)
    client, formatter = get_helpers(ctx)

    if dry_run:
        render_dry_run(formatter, "DELETE", f"/v1/backup/snapshot/{project}/{deployment}/{snapshot_id}")
        return

    confirm_action(f"Delete snapshot '{snapshot_id}'?", yes, ctx)

    result = client.delete_snapshot(project, deployment, snapshot_id)
    formatter.render(result)
    formatter.render_success(f"Snapshot '{snapshot_id}' deleted.")
