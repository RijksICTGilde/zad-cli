"""Deployment commands: list, describe, update-image, refresh, delete, check-subdomain, domain-settings."""

from __future__ import annotations

import sys
import webbrowser

import typer

from zad_cli.helpers import confirm_action, get_helpers, handle_api_errors, require_project

app = typer.Typer(help="Manage deployments.", no_args_is_help=True)


@app.command("list")
@handle_api_errors
def list_deployments(ctx: typer.Context) -> None:
    """List all deployments in a project.

    Requires ZAD_API_KEY and ZAD_PROJECT_ID (or --api-key and -p).

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
        rows.append({
            "deployment": dep["deployment"],
            "components": ", ".join(dep["components"]),
            "namespace": dep["namespace"],
        })

    formatter.render(rows, columns=["deployment", "components", "namespace"], title=f"Deployments in {project}")


@app.command()
@handle_api_errors
def describe(
    ctx: typer.Context,
    deployment: str = typer.Argument(help="Deployment name"),
) -> None:
    """Show detailed info about a deployment.

    Requires ZAD_API_KEY and ZAD_PROJECT_ID (or --api-key and -p).

    [bold]Example:[/bold]

        $ zad deployment describe regelrecht
    """
    project = require_project(ctx)
    client, formatter = get_helpers(ctx)

    result = client.describe_deployment(project, deployment)

    if formatter.fmt in ("json", "yaml"):
        formatter.render(result)
        return

    from rich.console import Console
    from rich.table import Table

    console = Console()

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


@app.command("update-image")
@handle_api_errors
def update_image(
    ctx: typer.Context,
    deployment: str = typer.Argument(help="Deployment name"),
    component: str = typer.Option(..., "--component", help="Component reference"),
    image: str = typer.Option(..., "--image", help="New container image"),
    recreate_storage: bool = typer.Option(False, "--recreate-storage", help="Recreate persistent storage"),
) -> None:
    """Update a deployment's container image.

    Requires ZAD_API_KEY and ZAD_PROJECT_ID (or --api-key and -p).

    [bold]Examples:[/bold]

        $ zad deployment update-image staging --component web --image ghcr.io/org/app:v1.3

        $ zad deployment update-image staging --component web --image ghcr.io/org/app:v1.3 --recreate-storage
    """
    project = require_project(ctx)
    client, formatter = get_helpers(ctx)

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
    deployment: str = typer.Argument(help="Deployment name"),
    force_clone: bool = typer.Option(False, "--force-clone", help="Force clone"),
) -> None:
    """Refresh a single deployment from git.

    Requires ZAD_API_KEY and ZAD_PROJECT_ID (or --api-key and -p)
    """
    project = require_project(ctx)
    client, formatter = get_helpers(ctx)

    result = client.refresh_deployment(project, deployment, force_clone=force_clone)
    formatter.render(result)


@app.command()
@handle_api_errors
def delete(
    ctx: typer.Context,
    deployment: str = typer.Argument(help="Deployment name"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Delete a single deployment.

    Requires ZAD_API_KEY and ZAD_PROJECT_ID (or --api-key and -p)
    """
    project = require_project(ctx)
    client, formatter = get_helpers(ctx)

    confirm_action(f"Delete deployment '{deployment}' in project '{project}'?", yes)

    result = client.delete_deployment(project, deployment)
    formatter.render(result)
    formatter.render_success(f"Deployment '{deployment}' deleted.")


@app.command("check-subdomain")
@handle_api_errors
def check_subdomain(
    ctx: typer.Context,
    subdomain: str = typer.Argument(help="Subdomain to check"),
    base_domain: str = typer.Argument(help="Base domain (e.g. apps.example.nl)"),
) -> None:
    """Check if a subdomain is available.

    Requires ZAD_API_KEY.

    [bold]Example:[/bold]

        $ zad deployment check-subdomain my-app apps.example.nl
    """
    client, formatter = get_helpers(ctx)

    result = client.check_subdomain(subdomain, base_domain)
    formatter.render(result)


@app.command("domain-settings")
def domain_settings(
    ctx: typer.Context,
    deployment: str = typer.Argument(help="Deployment name"),
) -> None:
    """Open the domain settings page in the browser.

    Requires ZAD_PROJECT_ID (or -p)
    """
    project = require_project(ctx)
    client, _ = get_helpers(ctx)
    url = f"{client.web_url}/projects/{project}"

    print(f"Opening project page: {url}", file=sys.stderr)
    print(f"Navigate to deployment '{deployment}' to change domain settings.", file=sys.stderr)
    webbrowser.open(url)
