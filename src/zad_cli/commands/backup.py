"""Backup commands: create, list, status, delete, namespace, database, bucket."""

from __future__ import annotations

import typer

from zad_cli.helpers import confirm_action, get_helpers, handle_api_errors, require_project

app = typer.Typer(help="Manage backups.", no_args_is_help=True)


@app.command()
@handle_api_errors
def create(
    ctx: typer.Context,
    deployment: str = typer.Argument(help="Deployment name"),
) -> None:
    """Create a backup of a project deployment.

    Requires ZAD_API_KEY and ZAD_PROJECT_ID (or --api-key and -p)
    """
    project = require_project(ctx)
    client, formatter = get_helpers(ctx)

    result = client.backup_project(project, deployment)
    formatter.render(result)
    formatter.render_success(f"Backup created for {project}/{deployment}.")


@app.command("list")
@handle_api_errors
def list_runs(
    ctx: typer.Context,
    deployment: str = typer.Argument(help="Deployment name"),
) -> None:
    """List backup runs for a deployment.

    Requires ZAD_API_KEY and ZAD_PROJECT_ID (or --api-key and -p)
    """
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
) -> None:
    """Delete a backup snapshot.

    Requires ZAD_API_KEY and ZAD_PROJECT_ID (or --api-key and -p)
    """
    project = require_project(ctx)
    client, formatter = get_helpers(ctx)

    confirm_action(f"Delete snapshot '{snapshot_id}'?", yes)

    result = client.delete_snapshot(project, deployment, snapshot_id)
    formatter.render(result)
    formatter.render_success(f"Snapshot '{snapshot_id}' deleted.")


@app.command()
@handle_api_errors
def namespace(
    ctx: typer.Context,
    namespace: str = typer.Argument(help="Namespace to backup"),
) -> None:
    """Backup an entire namespace."""
    client, formatter = get_helpers(ctx)

    result = client.backup_namespace(namespace)
    formatter.render(result)


@app.command()
@handle_api_errors
def database(
    ctx: typer.Context,
    namespace: str = typer.Argument(help="Namespace"),
    reference: str = typer.Argument(help="Database reference name"),
) -> None:
    """Backup a database."""
    client, formatter = get_helpers(ctx)

    result = client.backup_database(namespace, reference)
    formatter.render(result)


@app.command()
@handle_api_errors
def bucket(
    ctx: typer.Context,
    namespace: str = typer.Argument(help="Namespace"),
    reference: str = typer.Argument(help="Bucket reference name"),
) -> None:
    """Backup a bucket."""
    client, formatter = get_helpers(ctx)

    result = client.backup_bucket(namespace, reference)
    formatter.render(result)
