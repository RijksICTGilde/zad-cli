"""Restore commands: list, project, run, pvc, database, bucket."""

from __future__ import annotations

import typer

app = typer.Typer(help="Manage restores.", no_args_is_help=True)


def _get_helpers(ctx: typer.Context):
    from zad_cli.cli import _ensure_client

    _ensure_client(ctx)
    return ctx.obj["client"], ctx.obj["formatter"]


@app.command("list")
def list_snapshots(
    ctx: typer.Context,
    cluster: str = typer.Argument(help="Cluster name"),
    namespace: str = typer.Argument(help="Namespace"),
) -> None:
    """List available snapshots for restoration."""
    client, formatter = _get_helpers(ctx)

    try:
        result = client.list_snapshots(cluster, namespace)
        formatter.render(result)
    except Exception as e:
        formatter.render_error(str(e))
        raise typer.Exit(1) from e


@app.command()
def project(
    ctx: typer.Context,
    project_name: str = typer.Argument(help="Project name"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Restore a project deployment from snapshot."""
    client, formatter = _get_helpers(ctx)

    if not yes:
        typer.confirm(f"Restore project '{project_name}'? This may overwrite current data.", abort=True)

    try:
        result = client.restore_project(project_name)
        formatter.render(result)
        formatter.render_success(f"Project '{project_name}' restored.")
    except Exception as e:
        formatter.render_error(str(e))
        raise typer.Exit(1) from e


@app.command()
def run(
    ctx: typer.Context,
    project_name: str = typer.Argument(help="Project name"),
    backup_run_id: str = typer.Argument(help="Backup run ID"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Restore from a specific backup run."""
    client, formatter = _get_helpers(ctx)

    if not yes:
        typer.confirm(f"Restore from backup run '{backup_run_id}'?", abort=True)

    try:
        result = client.restore_backup_run(project_name, backup_run_id)
        formatter.render(result)
        formatter.render_success("Restore completed.")
    except Exception as e:
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
    client, formatter = _get_helpers(ctx)

    if not yes:
        typer.confirm(f"Restore PVC '{pvc_name}'?", abort=True)

    try:
        result = client.restore_pvc(cluster, namespace, pvc_name)
        formatter.render(result)
    except Exception as e:
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
    client, formatter = _get_helpers(ctx)

    if not yes:
        typer.confirm(f"Restore database '{reference}'?", abort=True)

    try:
        result = client.restore_database(cluster, namespace, reference)
        formatter.render(result)
    except Exception as e:
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
    client, formatter = _get_helpers(ctx)

    if not yes:
        typer.confirm(f"Restore bucket '{reference}'?", abort=True)

    try:
        result = client.restore_bucket(cluster, namespace, reference)
        formatter.render(result)
    except Exception as e:
        formatter.render_error(str(e))
        raise typer.Exit(1) from e
