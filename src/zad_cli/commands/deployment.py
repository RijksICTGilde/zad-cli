"""Deployment commands: update-image, delete, check-subdomain, domain-settings."""

from __future__ import annotations

import sys
import webbrowser

import typer

from zad_cli.api.client import ZadApiError
from zad_cli.helpers import get_helpers, require_project

app = typer.Typer(help="Manage deployments.", no_args_is_help=True)


@app.command("update-image")
def update_image(
    ctx: typer.Context,
    deployment: str = typer.Argument(help="Deployment name"),
    component: str = typer.Option(..., "--component", help="Component reference"),
    image: str = typer.Option(..., "--image", help="New container image"),
    recreate_storage: bool = typer.Option(False, "--recreate-storage", help="Recreate persistent storage"),
) -> None:
    """Update a deployment's container image.

    Requires ZAD_API_KEY and ZAD_PROJECT_ID (or --api-key and -p)
    """
    project = require_project(ctx)
    client, formatter = get_helpers(ctx)

    services = None
    if recreate_storage:
        services = {"persistent-storage": {"reference": {"data": {"action": "recreate"}}}}

    try:
        result = client.update_image(project, deployment, component, image, services=services)
        formatter.render(result)
        formatter.render_success(f"Image updated: {component} -> {image}")
    except ZadApiError as e:
        formatter.render_error(str(e))
        raise typer.Exit(1) from e


@app.command()
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

    if not yes:
        typer.confirm(f"Delete deployment '{deployment}' in project '{project}'?", abort=True)

    try:
        result = client.delete_deployment(project, deployment)
        formatter.render(result)
        formatter.render_success(f"Deployment '{deployment}' deleted.")
    except ZadApiError as e:
        formatter.render_error(str(e))
        raise typer.Exit(1) from e


@app.command("check-subdomain")
def check_subdomain(
    ctx: typer.Context,
    subdomain: str = typer.Option(..., "--subdomain", "-s", help="Subdomain to check"),
    base_domain: str = typer.Option(None, "--base-domain", help="Base domain"),
) -> None:
    """Check if a subdomain is available.

    Requires ZAD_API_KEY and ZAD_PROJECT_ID (or --api-key and -p)
    """
    project = require_project(ctx)
    client, formatter = get_helpers(ctx)

    try:
        result = client.check_subdomain(project, subdomain, base_domain)
        formatter.render(result)
    except ZadApiError as e:
        formatter.render_error(str(e))
        raise typer.Exit(1) from e


@app.command("domain-settings")
def domain_settings(
    ctx: typer.Context,
    deployment: str = typer.Argument(help="Deployment name"),
) -> None:
    """Open the domain settings page for a deployment in the browser.

    Domain mode, subdomain, and base domain can be changed via the web UI.

    Requires ZAD_PROJECT_ID (or -p)
    """
    project = require_project(ctx)
    settings = ctx.obj["settings"]
    base_url = settings.api_url.replace("/api", "").rstrip("/")
    url = f"{base_url}/projects/{project}"

    print(f"Opening project page: {url}", file=sys.stderr)
    print(f"Navigate to deployment '{deployment}' to change domain settings.", file=sys.stderr)
    webbrowser.open(url)
