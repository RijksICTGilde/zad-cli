"""Backup commands: create, list, status, delete, namespace, database, bucket."""

from __future__ import annotations

import typer

app = typer.Typer(help="Manage backups.", no_args_is_help=True)


def _get_helpers(ctx: typer.Context):
    from zad_cli.cli import _ensure_client

    _ensure_client(ctx)
    return ctx.obj["client"], ctx.obj["formatter"]


@app.command()
def create(
    ctx: typer.Context,
    project: str = typer.Argument(help="Project name"),
    deployment: str = typer.Argument(help="Deployment name"),
) -> None:
    """Create a backup of a project deployment."""
    client, formatter = _get_helpers(ctx)

    try:
        result = client.backup_project(project, deployment)
        formatter.render(result)
        formatter.render_success(f"Backup created for {project}/{deployment}.")
    except Exception as e:
        formatter.render_error(str(e))
        raise typer.Exit(1) from e


@app.command("list")
def list_runs(
    ctx: typer.Context,
    project: str = typer.Argument(help="Project name"),
    deployment: str = typer.Argument(help="Deployment name"),
) -> None:
    """List backup runs for a deployment."""
    client, formatter = _get_helpers(ctx)

    try:
        result = client.list_backup_runs(project, deployment)
        formatter.render(result)
    except Exception as e:
        formatter.render_error(str(e))
        raise typer.Exit(1) from e


@app.command()
def status(ctx: typer.Context) -> None:
    """Show backup system status."""
    client, formatter = _get_helpers(ctx)
    try:
        result = client.backup_status()
        formatter.render(result)
    except Exception as e:
        formatter.render_error(str(e))
        raise typer.Exit(1) from e


@app.command("delete")
def delete_snapshot(
    ctx: typer.Context,
    snapshot_id: str = typer.Argument(help="Snapshot ID"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Delete a backup snapshot."""
    client, formatter = _get_helpers(ctx)

    if not yes:
        typer.confirm(f"Delete snapshot '{snapshot_id}'?", abort=True)

    try:
        result = client.delete_snapshot(snapshot_id)
        formatter.render(result)
        formatter.render_success(f"Snapshot '{snapshot_id}' deleted.")
    except Exception as e:
        formatter.render_error(str(e))
        raise typer.Exit(1) from e


@app.command()
def namespace(
    ctx: typer.Context,
    ns: str = typer.Argument(help="Namespace to backup"),
) -> None:
    """Backup an entire namespace."""
    client, formatter = _get_helpers(ctx)

    try:
        result = client.backup_namespace(ns)
        formatter.render(result)
    except Exception as e:
        formatter.render_error(str(e))
        raise typer.Exit(1) from e


@app.command()
def database(
    ctx: typer.Context,
    ns: str = typer.Argument(help="Namespace"),
    reference: str = typer.Argument(help="Database reference name"),
) -> None:
    """Backup a database."""
    client, formatter = _get_helpers(ctx)

    try:
        result = client.backup_database(ns, reference)
        formatter.render(result)
    except Exception as e:
        formatter.render_error(str(e))
        raise typer.Exit(1) from e


@app.command()
def bucket(
    ctx: typer.Context,
    ns: str = typer.Argument(help="Namespace"),
    reference: str = typer.Argument(help="Bucket reference name"),
) -> None:
    """Backup a bucket."""
    client, formatter = _get_helpers(ctx)

    try:
        result = client.backup_bucket(ns, reference)
        formatter.render(result)
    except Exception as e:
        formatter.render_error(str(e))
        raise typer.Exit(1) from e
