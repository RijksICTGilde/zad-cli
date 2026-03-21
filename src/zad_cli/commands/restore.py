"""Restore commands: list, project, backup, pvc, database, bucket."""

from __future__ import annotations

import typer

from zad_cli.helpers import confirm_action, get_helpers, handle_api_errors, require_project

app = typer.Typer(
    help="Restore from backups and snapshots.\n\nAdmin commands (list, pvc) require cluster and namespace args.",
    no_args_is_help=True,
)


@app.command("list")
@handle_api_errors
def list_snapshots(
    ctx: typer.Context,
    cluster: str = typer.Argument(help="Cluster name"),
    namespace: str = typer.Argument(help="Kubernetes namespace"),
) -> None:
    """List available snapshots for restoration (admin operation)."""
    client, formatter = get_helpers(ctx)

    result = client.list_snapshots(cluster, namespace)
    formatter.render(result)


@app.command()
@handle_api_errors
def project(
    ctx: typer.Context,
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Restore a project deployment from snapshot."""
    project_id = require_project(ctx)
    client, formatter = get_helpers(ctx)

    confirm_action(f"Restore project '{project_id}'? This may overwrite current data.", yes)

    result = client.restore_project(project_id)
    formatter.render(result)
    formatter.render_success(f"Project '{project_id}' restored.")


@app.command()
@handle_api_errors
def backup(
    ctx: typer.Context,
    deployment: str = typer.Argument(help="Deployment name"),
    backup_run_id: str = typer.Argument(help="Backup run ID"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Restore from a specific backup run."""
    project_id = require_project(ctx)
    client, formatter = get_helpers(ctx)

    confirm_action(f"Restore from backup run '{backup_run_id}'?", yes)

    result = client.restore_backup_run(project_id, deployment, backup_run_id)
    formatter.render(result)
    formatter.render_success("Restore completed.")


@app.command()
@handle_api_errors
def pvc(
    ctx: typer.Context,
    cluster: str = typer.Argument(help="Cluster name"),
    namespace: str = typer.Argument(help="Kubernetes namespace"),
    pvc_name: str = typer.Argument(help="PVC name"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Restore a PVC from snapshot (admin operation)."""
    client, formatter = get_helpers(ctx)

    confirm_action(f"Restore PVC '{pvc_name}'?", yes)

    result = client.restore_pvc(cluster, namespace, pvc_name)
    formatter.render(result)


@app.command()
@handle_api_errors
def database(
    ctx: typer.Context,
    deployment: str = typer.Argument(help="Deployment name"),
    reference: str = typer.Argument(help="Database reference name"),
    cluster: str = typer.Option(None, "--cluster", help="Cluster name (admin override, auto-resolved if omitted)"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Restore a database from snapshot.

    By default resolves the cluster/namespace from the deployment name,
    just like 'zad backup database' does. Use --cluster to override.

    [bold]Example:[/bold]

        $ zad restore database staging my-db
    """
    project_id = require_project(ctx)
    client, formatter = get_helpers(ctx)

    namespace = client.resolve_namespace(project_id, deployment)
    confirm_action(f"Restore database '{reference}' in deployment '{deployment}'?", yes)

    resolved_cluster = cluster or (namespace.split("-")[0] if "-" in namespace else "default")
    result = client.restore_database(resolved_cluster, namespace, reference)
    formatter.render(result)
    formatter.render_success(f"Database '{reference}' restored.")


@app.command()
@handle_api_errors
def bucket(
    ctx: typer.Context,
    deployment: str = typer.Argument(help="Deployment name"),
    reference: str = typer.Argument(help="Bucket reference name"),
    cluster: str = typer.Option(None, "--cluster", help="Cluster name (admin override, auto-resolved if omitted)"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Restore a bucket from snapshot.

    By default resolves the cluster/namespace from the deployment name,
    just like 'zad backup bucket' does. Use --cluster to override.

    [bold]Example:[/bold]

        $ zad restore bucket staging my-bucket
    """
    project_id = require_project(ctx)
    client, formatter = get_helpers(ctx)

    namespace = client.resolve_namespace(project_id, deployment)
    confirm_action(f"Restore bucket '{reference}' in deployment '{deployment}'?", yes)

    resolved_cluster = cluster or (namespace.split("-")[0] if "-" in namespace else "default")
    result = client.restore_bucket(resolved_cluster, namespace, reference)
    formatter.render(result)
    formatter.render_success(f"Bucket '{reference}' restored.")
