"""Project commands: create, deploy, refresh, delete, subdomains."""

from __future__ import annotations

import json
import sys
import webbrowser

import typer

from zad_cli.api.client import ZadApiError
from zad_cli.api.models import Component, UpsertDeploymentRequest
from zad_cli.helpers import get_helpers, require_project

app = typer.Typer(help="Manage projects.", no_args_is_help=True)


@app.command()
def create(
    ctx: typer.Context,
    web: bool = typer.Option(True, "--web/--no-web", help="Open the self-service portal in the browser"),
) -> None:
    """Create a new project via the self-service portal."""
    settings = ctx.obj["settings"]
    base_url = settings.api_url.replace("/api", "").rstrip("/")
    portal_url = f"{base_url}/projects/new"

    if web:
        print(f"Opening self-service portal: {portal_url}", file=sys.stderr)
        webbrowser.open(portal_url)
    else:
        print(portal_url)


@app.command()
def deploy(
    ctx: typer.Context,
    deployment_name: str = typer.Option(..., "--deployment-name", "-d", help="Deployment name"),
    component: str = typer.Option(None, "--component", help="Component reference"),
    image: str = typer.Option(None, "--image", help="Container image"),
    components_json: str = typer.Option(None, "--components", help="Components JSON array"),
    clone_from: str = typer.Option(None, "--clone-from", help="Clone config from existing deployment"),
    force_clone: bool = typer.Option(False, "--force-clone", help="Force clone"),
    domain_format: str = typer.Option(None, "--domain-format", help="Domain format template"),
    subdomain: str = typer.Option(None, "--subdomain", help="Custom subdomain"),
    base_domain: str = typer.Option(None, "--base-domain", help="Base domain"),
) -> None:
    """Deploy or update a project (upsert deployment).

    Requires ZAD_API_KEY and ZAD_PROJECT_ID (or --api-key and -p)
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

    try:
        result = client.upsert_deployment(project, request.to_api_payload())
        formatter.render(result)
    except ZadApiError as e:
        formatter.render_error(str(e))
        raise typer.Exit(1) from e


@app.command()
def refresh(
    ctx: typer.Context,
    force_clone: bool = typer.Option(False, "--force-clone", help="Force clone during refresh"),
) -> None:
    """Refresh/retry a project from its YAML definition.

    Requires ZAD_API_KEY and ZAD_PROJECT_ID (or --api-key and -p)
    """
    project = require_project(ctx)
    client, formatter = get_helpers(ctx)

    try:
        result = client.refresh_project(project, force_clone=force_clone)
        formatter.render(result)
    except ZadApiError as e:
        formatter.render_error(str(e))
        raise typer.Exit(1) from e


@app.command()
def delete(
    ctx: typer.Context,
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
    force: bool = typer.Option(False, "--force", help="Force deletion"),
) -> None:
    """Delete a project and all its resources.

    Requires ZAD_API_KEY and ZAD_PROJECT_ID (or --api-key and -p)
    """
    project = require_project(ctx)
    client, formatter = get_helpers(ctx)

    if not yes:
        typer.confirm(f"Delete project '{project}' and all its resources?", abort=True)

    try:
        result = client.delete_project(project, confirm=True, force=force)
        formatter.render(result)
        formatter.render_success(f"Project '{project}' deleted.")
    except ZadApiError as e:
        formatter.render_error(str(e))
        raise typer.Exit(1) from e


@app.command()
def subdomains(ctx: typer.Context) -> None:
    """List subdomains for a project.

    Requires ZAD_API_KEY and ZAD_PROJECT_ID (or --api-key and -p)
    """
    project = require_project(ctx)
    client, formatter = get_helpers(ctx)

    try:
        result = client.list_subdomains(project)
        formatter.render(result)
    except ZadApiError as e:
        formatter.render_error(str(e))
        raise typer.Exit(1) from e
