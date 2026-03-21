"""Deployment commands: update-image, delete, check-subdomain."""

from __future__ import annotations

import typer

from zad_cli.api.client import ZadApiError
from zad_cli.helpers import get_helpers, resolve_project

app = typer.Typer(help="Manage deployments.", no_args_is_help=True)


@app.command("update-image")
def update_image(
    ctx: typer.Context,
    project: str = typer.Argument(None, help="Project ID [env: ZAD_PROJECT_ID]"),
    deployment: str = typer.Argument(None, help="Deployment name"),
    component: str = typer.Option(..., "--component", help="Component reference"),
    image: str = typer.Option(..., "--image", help="New container image"),
) -> None:
    """Update a deployment's container image."""
    project = resolve_project(ctx, project)
    client, formatter = get_helpers(ctx)

    try:
        result = client.update_image(project, deployment, component, image)
        formatter.render(result)
        formatter.render_success(f"Image updated: {component} -> {image}")
    except ZadApiError as e:
        formatter.render_error(str(e))
        raise typer.Exit(1) from e


@app.command()
def delete(
    ctx: typer.Context,
    project: str = typer.Argument(None, help="Project ID [env: ZAD_PROJECT_ID]"),
    deployment: str = typer.Argument(None, help="Deployment name"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Delete a single deployment."""
    project = resolve_project(ctx, project)
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
    project: str = typer.Argument(None, help="Project ID [env: ZAD_PROJECT_ID]"),
    subdomain: str = typer.Option(..., "--subdomain", "-s", help="Subdomain to check"),
    base_domain: str = typer.Option(None, "--base-domain", help="Base domain"),
) -> None:
    """Check if a subdomain is available."""
    project = resolve_project(ctx, project)
    client, formatter = get_helpers(ctx)

    try:
        result = client.check_subdomain(project, subdomain, base_domain)
        formatter.render(result)
    except ZadApiError as e:
        formatter.render_error(str(e))
        raise typer.Exit(1) from e
