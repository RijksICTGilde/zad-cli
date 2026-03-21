"""Restore commands: list, project, run, pvc, database, bucket."""

from __future__ import annotations

import typer

from zad_cli.api.client import ZadApiError
from zad_cli.helpers import get_helpers, require_project

app = typer.Typer(help="Manage restores.", no_args_is_help=True)


@app.command("list")
def list_snapshots(
    ctx: typer.Context,
    cluster: str = typer.Argument(help="Cluster name"),
    namespace: str = typer.Argument(help="Namespace"),
) -> None:
    """List available snapshots for restoration."""
    client, formatter = get_helpers(ctx)

    try:
        result = client.list_snapshots(cluster, namespace)
        formatter.render(result)
    except ZadApiError as e:
        formatter.render_error(str(e))
        raise typer.Exit(1) from e


@app.command()
def project(
    ctx: typer.Context,
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Restore a project deployment from snapshot.

    Requires ZAD_API_KEY and ZAD_PROJECT_ID (or --api-key and -p)
    """
    project_id = require_project(ctx)
    client, formatter = get_helpers(ctx)

    if not yes:
        typer.confirm(f"Restore project '{project_id}'? This may overwrite current data.", abort=True)

    try:
        result = client.restore_project(project_id)
        formatter.render(result)
        formatter.render_success(f"Project '{project_id}' restored.")
    except ZadApiError as e:
        formatter.render_error(str(e))
        raise typer.Exit(1) from e


@app.command()
def run(
    ctx: typer.Context,
    backup_run_id: str = typer.Argument(help="Backup run ID"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Restore from a specific backup run.

    Requires ZAD_API_KEY and ZAD_PROJECT_ID (or --api-key and -p)
    """
    project_id = require_project(ctx)
    client, formatter = get_helpers(ctx)

    if not yes:
        typer.confirm(f"Restore from backup run '{backup_run_id}'?", abort=True)

    try:
        result = client.restore_backup_run(project_id, backup_run_id)
        formatter.render(result)
        formatter.render_success("Restore completed.")
    except ZadApiError as e:
        formatter.render_error(str(e))
        raise typer.Exit(1) from e


@app.command()
def pvc(
    ctx: typer.Context,
    cluster: str = typer.Argument(help="Cluster name"),
    namespace: str = typer.Argument(help="Namespace"),
    pvc_name: str = typer.Argument(help="PVC name"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Restore a PVC from snapshot."""
    client, formatter = get_helpers(ctx)

    if not yes:
        typer.confirm(f"Restore PVC '{pvc_name}'?", abort=True)

    try:
        result = client.restore_pvc(cluster, namespace, pvc_name)
        formatter.render(result)
    except ZadApiError as e:
        formatter.render_error(str(e))
        raise typer.Exit(1) from e


@app.command()
def database(
    ctx: typer.Context,
    cluster: str = typer.Argument(help="Cluster name"),
    namespace: str = typer.Argument(help="Namespace"),
    reference: str = typer.Argument(help="Database reference name"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Restore a database from snapshot."""
    client, formatter = get_helpers(ctx)

    if not yes:
        typer.confirm(f"Restore database '{reference}'?", abort=True)

    try:
        result = client.restore_database(cluster, namespace, reference)
        formatter.render(result)
    except ZadApiError as e:
        formatter.render_error(str(e))
        raise typer.Exit(1) from e


@app.command()
def bucket(
    ctx: typer.Context,
    cluster: str = typer.Argument(help="Cluster name"),
    namespace: str = typer.Argument(help="Namespace"),
    reference: str = typer.Argument(help="Bucket reference name"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Restore a bucket from snapshot."""
    client, formatter = get_helpers(ctx)

    if not yes:
        typer.confirm(f"Restore bucket '{reference}'?", abort=True)

    try:
        result = client.restore_bucket(cluster, namespace, reference)
        formatter.render(result)
    except ZadApiError as e:
        formatter.render_error(str(e))
        raise typer.Exit(1) from e
