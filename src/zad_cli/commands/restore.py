"""Restore commands: list, project, backup, pvc, database, bucket."""

from __future__ import annotations

import typer

from zad_cli.helpers import confirm_action, get_helpers, handle_api_errors, render_dry_run, require_project

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
    snapshots = result.get("snapshots", result) if isinstance(result, dict) else result
    formatter.render(snapshots, title="Snapshots")


@app.command()
@handle_api_errors
def project(
    ctx: typer.Context,
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be sent without making the API call"),
) -> None:
    """Restore a project deployment from snapshot.

    [bold]Example:[/bold]

        $ zad restore project
    """
    project_id = require_project(ctx)
    client, formatter = get_helpers(ctx)

    if dry_run:
        render_dry_run(formatter, "POST", f"/v1/restore/project/{project_id}")
        return

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
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be sent without making the API call"),
) -> None:
    """Restore from a specific backup run.

    [bold]Example:[/bold]

        $ zad restore backup staging run-456
    """
    project_id = require_project(ctx)
    client, formatter = get_helpers(ctx)

    if dry_run:
        render_dry_run(
            formatter, "POST", f"/v1/restore/project/{project_id}/deployment/{deployment}/run/{backup_run_id}"
        )
        return

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
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be sent without making the API call"),
) -> None:
    """Restore a PVC from snapshot (admin operation).

    [bold]Example:[/bold]

        $ zad restore pvc cluster-1 my-namespace my-pvc
    """
    client, formatter = get_helpers(ctx)

    if dry_run:
        render_dry_run(formatter, "POST", f"/v1/restore/pvc/{cluster}/{namespace}/{pvc_name}")
        return

    confirm_action(f"Restore PVC '{pvc_name}'?", yes)

    result = client.restore_pvc(cluster, namespace, pvc_name)
    formatter.render(result)
    formatter.render_success(f"PVC '{pvc_name}' restored.")


@app.command()
@handle_api_errors
def database(
    ctx: typer.Context,
    deployment: str = typer.Argument(help="Deployment name"),
    reference: str = typer.Argument(help="Database reference name"),
    cluster: str = typer.Option(None, "--cluster", help="Cluster name (admin override, auto-resolved if omitted)"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be sent without making the API call"),
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
    resolved_cluster = cluster or (namespace.split("-")[0] if "-" in namespace else "default")

    if dry_run:
        render_dry_run(formatter, "POST", f"/v1/restore/database/{resolved_cluster}/{namespace}/{reference}")
        return

    confirm_action(f"Restore database '{reference}' in deployment '{deployment}'?", yes)

    result = client.restore_database(resolved_cluster, namespace, reference)
    formatter.render(result)
    formatter.render_success(f"Database '{reference}' restored.")


@app.command("deployment")
@handle_api_errors
def restore_deployment(
    ctx: typer.Context,
    deployment: str = typer.Argument(help="Deployment name"),  # noqa: B008
    resource_type: str = typer.Option(..., "--resource-type", "-t", help="Resource type: pvc, database, or minio"),
    snapshot_id: str = typer.Option(..., "--snapshot-id", help="Snapshot ID to restore from"),
    component: str = typer.Option(..., "--component", "-c", help="Component name that owns the resource"),
    reference: str = typer.Option(..., "--reference", "-r", help="Reference name of the resource"),
    update_deployment: bool = typer.Option(
        True, "--update-deployment/--no-update-deployment", help="Trigger deployment refresh after restore"
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be sent without making the API call"),
) -> None:
    """Restore a resource for a deployment with versioning.

    Creates a new versioned resource from a snapshot and updates the
    deployment manifest to point to it.

    [bold]Example:[/bold]

        $ zad restore deployment staging --resource-type database --snapshot-id k1234abcd \\
            --component backend --reference staging-db
    """
    project_id = require_project(ctx)
    client, formatter = get_helpers(ctx)

    payload: dict = {
        "resource_type": resource_type,
        "snapshot_id": snapshot_id,
        "component_name": component,
        "reference_name": reference,
        "update_deployment": update_deployment,
    }

    if dry_run:
        render_dry_run(formatter, "POST", f"/v1/restore/project/{project_id}/deployment/{deployment}", payload)
        return

    confirm_action(f"Restore '{resource_type}' resource '{reference}' in deployment '{deployment}'?", yes)

    result = client.restore_deployment_resource(project_id, deployment, payload)
    formatter.render(result)
    formatter.render_success(f"Resource '{reference}' restored in deployment '{deployment}'.")


@app.command("pvc-snapshots")
@handle_api_errors
def pvc_snapshots(
    ctx: typer.Context,
    cluster: str = typer.Argument(help="Cluster name"),  # noqa: B008
    namespace: str = typer.Argument(help="Kubernetes namespace"),  # noqa: B008
    pvc_name: str = typer.Argument(help="PVC name"),  # noqa: B008
) -> None:
    """List available snapshots for a specific PVC.

    [bold]Example:[/bold]

        $ zad restore pvc-snapshots local my-namespace app-data-pvc
    """
    client, formatter = get_helpers(ctx)

    result = client.list_pvc_snapshots(cluster, namespace, pvc_name)
    snapshots = result.get("snapshots", result) if isinstance(result, dict) else result
    formatter.render(snapshots, title="PVC snapshots")


@app.command()
@handle_api_errors
def bucket(
    ctx: typer.Context,
    deployment: str = typer.Argument(help="Deployment name"),
    reference: str = typer.Argument(help="Bucket reference name"),
    cluster: str = typer.Option(None, "--cluster", help="Cluster name (admin override, auto-resolved if omitted)"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be sent without making the API call"),
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
    resolved_cluster = cluster or (namespace.split("-")[0] if "-" in namespace else "default")

    if dry_run:
        render_dry_run(formatter, "POST", f"/v1/restore/bucket/{resolved_cluster}/{namespace}/{reference}")
        return

    confirm_action(f"Restore bucket '{reference}' in deployment '{deployment}'?", yes)

    result = client.restore_bucket(resolved_cluster, namespace, reference)
    formatter.render(result)
    formatter.render_success(f"Bucket '{reference}' restored.")
