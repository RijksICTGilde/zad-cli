"""Deployment commands: list, describe, create, update-image, refresh, delete."""

from __future__ import annotations

import json

import typer

from zad_cli.api.models import Component, UpsertDeploymentRequest
from zad_cli.helpers import (
    complete_deployment,
    confirm_action,
    get_helpers,
    handle_api_errors,
    render_dry_run,
    require_project,
)

app = typer.Typer(
    help="Manage deployments.\n\nMost commands require ZAD_API_KEY and ZAD_PROJECT_ID (or --api-key and -p).",
    no_args_is_help=True,
)


@app.command("list")
@handle_api_errors
def list_deployments(ctx: typer.Context) -> None:
    """List all deployments in a project.

    [bold]Example:[/bold]

        $ zad deployment list
    """
    project = require_project(ctx)
    client, formatter = get_helpers(ctx)

    deployments = client.list_deployments(project)

    if formatter.fmt in ("json", "yaml"):
        formatter.render(deployments)
        return

    rows = []
    for dep in deployments:
        rows.append(
            {
                "deployment": dep["deployment"],
                "components": str(len(dep["components"])),
                "status": dep.get("status", "Active"),
                "namespace": dep["namespace"],
            }
        )

    formatter.render(
        rows, columns=["deployment", "components", "status", "namespace"], title=f"Deployments in {project}"
    )


@app.command()
@handle_api_errors
def describe(
    ctx: typer.Context,
    deployment: str = typer.Argument(help="Deployment name", autocompletion=complete_deployment),
) -> None:
    """Show detailed info about a deployment.

    [bold]Example:[/bold]

        $ zad deployment describe regelrecht
    """
    project = require_project(ctx)
    client, formatter = get_helpers(ctx)

    result = client.describe_deployment(project, deployment)

    if formatter.fmt in ("json", "yaml"):
        formatter.render(result)
        return

    from rich.table import Table

    console = formatter.console

    console.print(f"\n[bold]Deployment:[/bold] {result['deployment']}")
    console.print(f"[bold]Project:[/bold] {result['project']}")
    console.print(f"[bold]Namespace:[/bold] {result['namespace']}")

    if result.get("urls"):
        console.print("\n[bold]URLs:[/bold]")
        for comp_name, url in result["urls"].items():
            console.print(f"  {comp_name}: {url}")

    console.print()

    has_images = any(comp.get("image") for comp in result["components"])

    table = Table(title="Components", show_header=True)
    table.add_column("Name", style="bold cyan")
    if has_images:
        table.add_column("Image")
    table.add_column("K8s Deployment")

    for comp in result["components"]:
        row = [comp["name"]]
        if has_images:
            row.append(comp.get("image", ""))
        row.append(comp.get("k8s_deployment", ""))
        table.add_row(*row)

    console.print(table)


@app.command()
@handle_api_errors
def create(
    ctx: typer.Context,
    deployment_name: str = typer.Argument(help="Deployment name"),
    component: str = typer.Option(None, "--component", help="Component reference"),
    image: str = typer.Option(None, "--image", help="Container image"),
    components_json: str = typer.Option(None, "--components", help="Components JSON array"),
    clone_from: str = typer.Option(None, "--clone-from", help="Clone config from existing deployment"),
    force_clone: bool = typer.Option(False, "--force-clone", help="Force clone"),
    domain_format: str = typer.Option(None, "--domain-format", help="Domain format template"),
    subdomain: str = typer.Option(None, "--subdomain", help="Custom subdomain"),
    base_domain: str = typer.Option(None, "--base-domain", help="Base domain"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be sent without making the API call"),
) -> None:
    """Create or update a deployment (upsert).

    This is an upsert operation: if the deployment already exists, it will be updated.
    Use --yes to skip confirmation.

    [bold]Examples:[/bold]

        $ zad deployment create staging --component web --image ghcr.io/org/app:v1.2

        $ zad deployment create staging --components '[{"name":"web","image":"ghcr.io/org/app:v1.2"}]'

        $ zad deployment create pr-42 --component web --image ghcr.io/org/app:pr-42 --clone-from production
    """
    project = require_project(ctx)
    client, formatter = get_helpers(ctx)

    if components_json:
        try:
            raw = json.loads(components_json)
            comp_list = [Component(name=c["name"], image=c["image"]) for c in raw]
        except (json.JSONDecodeError, KeyError) as e:
            formatter.render_error(f"Invalid --components JSON: {e}")
            raise typer.Exit(1) from e
    elif component and image:
        comp_list = [Component(name=component, image=image)]
    else:
        formatter.render_error("Provide --component + --image, or --components JSON")
        raise typer.Exit(1)

    request = UpsertDeploymentRequest(
        deployment_name=deployment_name,
        components=comp_list,
        clone_from=clone_from,
        force_clone=force_clone,
        domain_format=domain_format,
        subdomain=subdomain,
        base_domain=base_domain,
    )

    if dry_run:
        render_dry_run(formatter, "POST", f"/v2/projects/{project}/:upsert-deployment", request.to_api_payload())
        return

    confirm_action(f"Create/update deployment '{deployment_name}' in project '{project}'?", yes)

    result = client.upsert_deployment(project, request.to_api_payload())
    formatter.render(result)


@app.command("update-image")
@handle_api_errors
def update_image(
    ctx: typer.Context,
    deployment: str = typer.Argument(help="Deployment name", autocompletion=complete_deployment),
    component: str = typer.Option(..., "--component", help="Component reference"),
    image: str = typer.Option(..., "--image", help="New container image"),
    recreate_storage: bool = typer.Option(False, "--recreate-storage", help="Recreate persistent storage"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be sent without making the API call"),
) -> None:
    """Update a deployment's container image.

    [bold]Examples:[/bold]

        $ zad deployment update-image staging --component web --image ghcr.io/org/app:v1.3

        $ zad deployment update-image staging --component web --image ghcr.io/org/app:v1.3 --recreate-storage
    """
    project = require_project(ctx)
    client, formatter = get_helpers(ctx)

    payload: dict = {"componentName": component, "newImageUrl": image}
    if recreate_storage:
        payload["services"] = {"persistent-storage": {"reference": {"data": {"action": "recreate"}}}}

    if dry_run:
        render_dry_run(formatter, "PUT", f"/v2/projects/{project}/deployments/{deployment}/image", payload)
        return

    kwargs: dict = {}
    if recreate_storage:
        kwargs["services"] = {"persistent-storage": {"reference": {"data": {"action": "recreate"}}}}

    result = client.update_image(project, deployment, component, image, **kwargs)
    formatter.render(result)
    formatter.render_success(f"Image updated: {component} -> {image}")


@app.command()
@handle_api_errors
def refresh(
    ctx: typer.Context,
    deployment: str = typer.Argument(help="Deployment name", autocompletion=complete_deployment),
    force_clone: bool = typer.Option(False, "--force-clone", help="Force clone"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be sent without making the API call"),
) -> None:
    """Refresh a single deployment from git."""
    project = require_project(ctx)
    client, formatter = get_helpers(ctx)

    if dry_run:
        render_dry_run(
            formatter,
            "POST",
            f"/v2/projects/{project}/deployments/{deployment}/:refresh",
            {"force_clone": force_clone},
        )
        return

    result = client.refresh_deployment(project, deployment, force_clone=force_clone)
    formatter.render(result)


@app.command()
@handle_api_errors
def delete(
    ctx: typer.Context,
    deployment: str = typer.Argument(help="Deployment name", autocompletion=complete_deployment),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be sent without making the API call"),
) -> None:
    """Delete a single deployment."""
    project = require_project(ctx)
    client, formatter = get_helpers(ctx)

    if dry_run:
        render_dry_run(formatter, "DELETE", f"/v2/projects/{project}/{deployment}")
        return

    confirm_action(f"Delete deployment '{deployment}' in project '{project}'?", yes)

    result = client.delete_deployment(project, deployment)
    formatter.render(result)
    formatter.render_success(f"Deployment '{deployment}' deleted.")
