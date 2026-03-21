"""Deployment commands: update-image, delete, check-subdomain."""

from __future__ import annotations

import typer

app = typer.Typer(help="Manage deployments.", no_args_is_help=True)


def _get_helpers(ctx: typer.Context):
    from zad_cli.cli import _ensure_client

    _ensure_client(ctx)
    return ctx.obj["client"], ctx.obj["formatter"]


@app.command("update-image")
def update_image(
    ctx: typer.Context,
    project: str = typer.Argument(help="Project ID"),
    deployment: str = typer.Argument(help="Deployment name"),
    component: str = typer.Option(..., "--component", help="Component reference"),
    image: str = typer.Option(..., "--image", help="New container image"),
) -> None:
    """Update a deployment's container image."""
    client, formatter = _get_helpers(ctx)

    try:
        result = client.update_image(project, deployment, component, image)
        formatter.render(result)
        formatter.render_success(f"Image updated: {component} -> {image}")
    except Exception as e:
        formatter.render_error(str(e))
        raise typer.Exit(1) from e


@app.command()
def delete(
    ctx: typer.Context,
    project: str = typer.Argument(help="Project ID"),
    deployment: str = typer.Argument(help="Deployment name"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Delete a single deployment."""
    client, formatter = _get_helpers(ctx)

    if not yes:
        typer.confirm(f"Delete deployment '{deployment}' in project '{project}'?", abort=True)

    try:
        result = client.delete_deployment(project, deployment)
        formatter.render(result)
        formatter.render_success(f"Deployment '{deployment}' deleted.")
    except Exception as e:
        formatter.render_error(str(e))
        raise typer.Exit(1) from e


@app.command("check-subdomain")
def check_subdomain(
    ctx: typer.Context,
    project: str = typer.Argument(help="Project ID"),
    subdomain: str = typer.Option(..., "--subdomain", "-s", help="Subdomain to check"),
    base_domain: str = typer.Option(None, "--base-domain", help="Base domain"),
) -> None:
    """Check if a subdomain is available."""
    client, formatter = _get_helpers(ctx)

    try:
        result = client.check_subdomain(project, subdomain, base_domain)
        formatter.render(result)
    except Exception as e:
        formatter.render_error(str(e))
        raise typer.Exit(1) from e
