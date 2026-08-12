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
    """List available snapshots for restoration.

    The namespace must belong to your project: the API authenticates the key
    against the project and rejects any other namespace.

    [bold]Example:[/bold]

        $ zad restore list local rig-my-project
    """
    project_id = require_project(ctx)
    client, formatter = get_helpers(ctx)

    result = client.list_snapshots(cluster, namespace, project_name=project_id)
    snapshots = result.get("snapshots", result) if isinstance(result, dict) else result
    formatter.render(snapshots, title="Snapshots")


@app.command()
@handle_api_errors
def project(
    ctx: typer.Context,
    deployment: str = typer.Option(..., "--deployment", help="Deployment that holds the storage"),
    component: str = typer.Option(..., "--component", "-c", help="Component that owns the storage"),
    storage: str = typer.Option(..., "--storage", help="Storage name, the mount path identifier (e.g. 'data')"),
    snapshot_id: str = typer.Option(None, "--snapshot-id", help="Snapshot to restore (default: the latest)"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be sent without making the API call"),
) -> None:
    """Restore a storage volume from snapshot.

    Restores one storage volume of one component, not the whole project.
    Use 'zad restore list' to see which snapshots exist.

    [bold]Example:[/bold]

        $ zad restore project --deployment productie -c web --storage data
    """
    project_id = require_project(ctx)
    client, formatter = get_helpers(ctx)

    payload: dict = {"deployment_name": deployment, "component_name": component, "storage_name": storage}
    if snapshot_id:
        payload["snapshot_id"] = snapshot_id

    if dry_run:
        render_dry_run(formatter, "POST", f"/v1/restore/project/{project_id}", payload)
        return

    confirm_action(
        f"Restore storage '{storage}' of component '{component}' in deployment '{deployment}'? "
        "This overwrites the current data.",
        yes,
        ctx,
    )

    result = client.restore_project(project_id, payload)
    formatter.render(result)
    formatter.render_success(f"Storage '{storage}' restored.")


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

    confirm_action(f"Restore from backup run '{backup_run_id}'?", yes, ctx)

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
    """Restore a PVC from snapshot.

    The namespace must belong to your project: the API authenticates the key
    against the project and rejects any other namespace.

    [bold]Example:[/bold]

        $ zad restore pvc local rig-my-project my-pvc
    """
    project_id = require_project(ctx)
    client, formatter = get_helpers(ctx)

    if dry_run:
        render_dry_run(formatter, "POST", f"/v1/restore/pvc/{cluster}/{namespace}/{pvc_name}?project_name={project_id}")
        return

    confirm_action(f"Restore PVC '{pvc_name}'?", yes, ctx)

    result = client.restore_pvc(cluster, namespace, pvc_name, project_name=project_id)
    formatter.render(result)
    formatter.render_success(f"PVC '{pvc_name}' restored.")


@app.command()
@handle_api_errors
def database(
    ctx: typer.Context,
    deployment: str = typer.Argument(help="Deployment name"),
    reference: str = typer.Argument(help="Database reference name"),
    target_host: str = typer.Option(..., "--target-host", help="Target database host address"),
    target_dbname: str = typer.Option(..., "--target-dbname", help="Target database name"),
    target_username: str = typer.Option(..., "--target-username", help="Target database username"),
    target_password: str = typer.Option(
        ..., "--target-password", envvar="TARGET_DB_PASSWORD", help="Target database password"
    ),
    target_port: int = typer.Option(5432, "--target-port", help="Target database port"),
    snapshot_id: str = typer.Option(None, "--snapshot-id", help="Snapshot to restore (default: the latest)"),
    cluster: str = typer.Option(None, "--cluster", help="Cluster name (admin override, auto-resolved if omitted)"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be sent without making the API call"),
) -> None:
    """Restore a database from snapshot into a target database.

    The target options say where the snapshot is written to, and the API
    requires all four. The target is not resolved from the deployment: a
    restore that silently picks its own destination is not something you
    want to find out about afterwards.

    By default resolves the cluster/namespace from the deployment name,
    just like 'zad backup database' does. Use --cluster to override.

    [bold]Example:[/bold]

        $ zad restore database staging my-db \\
            --target-host db.internal --target-dbname app --target-username app
    """
    project_id = require_project(ctx)
    client, formatter = get_helpers(ctx)

    namespace = client.resolve_namespace(project_id, deployment)
    resolved_cluster = cluster or (namespace.split("-")[0] if "-" in namespace else "default")

    payload: dict = {
        "target_database_host": target_host,
        "target_database_port": target_port,
        "target_database_name": target_dbname,
        "target_database_user": target_username,
        "target_database_password": target_password,
    }
    if snapshot_id:
        payload["snapshot_id"] = snapshot_id

    if dry_run:
        render_dry_run(
            formatter,
            "POST",
            f"/v1/restore/database/{resolved_cluster}/{namespace}/{reference}?project_name={project_id}",
            payload,
        )
        return

    confirm_action(
        f"Restore database '{reference}' into '{target_dbname}' on {target_host}? This overwrites the target.",
        yes,
        ctx,
    )

    result = client.restore_database(resolved_cluster, namespace, reference, payload, project_name=project_id)
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

    confirm_action(f"Restore '{resource_type}' resource '{reference}' in deployment '{deployment}'?", yes, ctx)

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

    The namespace must belong to your project: the API authenticates the key
    against the project and rejects any other namespace.

    [bold]Example:[/bold]

        $ zad restore pvc-snapshots local rig-my-project app-data-pvc
    """
    project_id = require_project(ctx)
    client, formatter = get_helpers(ctx)

    result = client.list_pvc_snapshots(cluster, namespace, pvc_name, project_name=project_id)
    snapshots = result.get("snapshots", result) if isinstance(result, dict) else result
    formatter.render(snapshots, title="PVC snapshots")


@app.command()
@handle_api_errors
def bucket(
    ctx: typer.Context,
    deployment: str = typer.Argument(help="Deployment name"),
    reference: str = typer.Argument(help="Bucket reference name"),
    target_endpoint: str = typer.Option(..., "--target-endpoint", help="Target S3/MinIO endpoint URL"),
    target_bucket: str = typer.Option(..., "--target-bucket", help="Target bucket name"),
    target_access_key: str = typer.Option(
        ..., "--target-access-key", envvar="TARGET_S3_ACCESS_KEY", help="Target access key"
    ),
    target_secret_key: str = typer.Option(
        ..., "--target-secret-key", envvar="TARGET_S3_SECRET_KEY", help="Target secret key"
    ),
    clear_target: bool = typer.Option(False, "--clear-target", help="Empty the target bucket before restoring"),
    snapshot_id: str = typer.Option(None, "--snapshot-id", help="Snapshot to restore (default: the latest)"),
    cluster: str = typer.Option(None, "--cluster", help="Cluster name (admin override, auto-resolved if omitted)"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be sent without making the API call"),
) -> None:
    """Restore a bucket from snapshot into a target bucket.

    The target options say where the snapshot is written to, and the API
    requires all four. Without --clear-target the snapshot is written over
    whatever is already in the target bucket, and anything not in the
    snapshot stays behind.

    By default resolves the cluster/namespace from the deployment name,
    just like 'zad backup bucket' does. Use --cluster to override.

    [bold]Example:[/bold]

        $ zad restore bucket staging my-bucket \\
            --target-endpoint https://minio.internal --target-bucket app-data
    """
    project_id = require_project(ctx)
    client, formatter = get_helpers(ctx)

    namespace = client.resolve_namespace(project_id, deployment)
    resolved_cluster = cluster or (namespace.split("-")[0] if "-" in namespace else "default")

    payload: dict = {
        "target_minio_endpoint": target_endpoint,
        "target_bucket_name": target_bucket,
        "target_access_key": target_access_key,
        "target_secret_key": target_secret_key,
        "clear_target": clear_target,
    }
    if snapshot_id:
        payload["snapshot_id"] = snapshot_id

    if dry_run:
        render_dry_run(
            formatter,
            "POST",
            f"/v1/restore/bucket/{resolved_cluster}/{namespace}/{reference}?project_name={project_id}",
            payload,
        )
        return

    what = "empty and restore" if clear_target else "restore into"
    confirm_action(f"Bucket '{reference}': {what} '{target_bucket}' on {target_endpoint}?", yes, ctx)

    result = client.restore_bucket(resolved_cluster, namespace, reference, payload, project_name=project_id)
    formatter.render(result)
    formatter.render_success(f"Bucket '{reference}' restored.")
