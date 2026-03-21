"""Backup commands: create, list, status, delete, namespace, database, bucket."""

from __future__ import annotations

import typer

from zad_cli.api.client import ZadApiError
from zad_cli.helpers import get_helpers, require_project

app = typer.Typer(help="Manage backups.", no_args_is_help=True)


@app.command()
def create(
    ctx: typer.Context,
    deployment: str = typer.Argument(help="Deployment name"),
) -> None:
    """Create a backup of a project deployment.

    Requires ZAD_API_KEY and ZAD_PROJECT_ID (or --api-key and -p)
    """
    project = require_project(ctx)
    client, formatter = get_helpers(ctx)

    try:
        result = client.backup_project(project, deployment)
        formatter.render(result)
        formatter.render_success(f"Backup created for {project}/{deployment}.")
    except ZadApiError as e:
        formatter.render_error(str(e))
        raise typer.Exit(1) from e


@app.command("list")
def list_runs(
    ctx: typer.Context,
    deployment: str = typer.Argument(help="Deployment name"),
) -> None:
    """List backup runs for a deployment.

    Requires ZAD_API_KEY and ZAD_PROJECT_ID (or --api-key and -p)
    """
    project = require_project(ctx)
    client, formatter = get_helpers(ctx)

    try:
        result = client.list_backup_runs(project, deployment)
        formatter.render(result)
    except ZadApiError as e:
        formatter.render_error(str(e))
        raise typer.Exit(1) from e


@app.command()
def status(ctx: typer.Context) -> None:
    """Show backup system status."""
    client, formatter = get_helpers(ctx)
    try:
        result = client.backup_status()
        formatter.render(result)
    except ZadApiError as e:
        formatter.render_error(str(e))
        raise typer.Exit(1) from e


@app.command("delete")
def delete_snapshot(
    ctx: typer.Context,
    snapshot_id: str = typer.Argument(help="Snapshot ID"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Delete a backup snapshot."""
    client, formatter = get_helpers(ctx)

    if not yes:
        typer.confirm(f"Delete snapshot '{snapshot_id}'?", abort=True)

    try:
        result = client.delete_snapshot(snapshot_id)
        formatter.render(result)
        formatter.render_success(f"Snapshot '{snapshot_id}' deleted.")
    except ZadApiError as e:
        formatter.render_error(str(e))
        raise typer.Exit(1) from e


@app.command()
def namespace(
    ctx: typer.Context,
    ns: str = typer.Argument(help="Namespace to backup"),
) -> None:
    """Backup an entire namespace."""
    client, formatter = get_helpers(ctx)

    try:
        result = client.backup_namespace(ns)
        formatter.render(result)
    except ZadApiError as e:
        formatter.render_error(str(e))
        raise typer.Exit(1) from e


@app.command()
def database(
    ctx: typer.Context,
    ns: str = typer.Argument(help="Namespace"),
    reference: str = typer.Argument(help="Database reference name"),
) -> None:
    """Backup a database."""
    client, formatter = get_helpers(ctx)

    try:
        result = client.backup_database(ns, reference)
        formatter.render(result)
    except ZadApiError as e:
        formatter.render_error(str(e))
        raise typer.Exit(1) from e


@app.command()
def bucket(
    ctx: typer.Context,
    ns: str = typer.Argument(help="Namespace"),
    reference: str = typer.Argument(help="Bucket reference name"),
) -> None:
    """Backup a bucket."""
    client, formatter = get_helpers(ctx)

    try:
        result = client.backup_bucket(ns, reference)
        formatter.render(result)
    except ZadApiError as e:
        formatter.render_error(str(e))
        raise typer.Exit(1) from e
