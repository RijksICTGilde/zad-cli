"""Project commands: status, create, deploy, refresh, delete, subdomains."""

from __future__ import annotations

import json
import sys
import webbrowser

import typer

from zad_cli.api.models import Component, UpsertDeploymentRequest
from zad_cli.helpers import confirm_action, get_helpers, handle_api_errors, require_project

app = typer.Typer(help="Manage projects.", no_args_is_help=True)


@app.command()
@handle_api_errors
def status(ctx: typer.Context) -> None:
    """Show project overview: deployments, components, and URLs.

    Requires ZAD_API_KEY and ZAD_PROJECT_ID (or --api-key and -p).

    [bold]Example:[/bold]

        $ zad project status
    """
    project = require_project(ctx)
    client, formatter = get_helpers(ctx)

    result = client.project_status(project)

    if formatter.fmt in ("json", "yaml"):
        formatter.render(result)
        return

    from rich.console import Console
    from rich.table import Table

    console = Console()

    console.print(f"\n[bold]Project:[/bold] {result['project']}")
    console.print(f"[bold]Deployments:[/bold] {len(result['deployments'])}")

    if result["subdomains"]:
        sd = result["subdomains"][0]
        console.print(f"[bold]Custom domain:[/bold] {sd['subdomain']}.{sd['base_domain']}")

    console.print()

    table = Table(title="Deployments", show_header=True)
    table.add_column("Deployment", style="bold cyan")
    table.add_column("Components")
    table.add_column("URL")

    for dep in result["deployments"]:
        components = ", ".join(dep["components"])
        url = ""
        if dep.get("urls"):
            first_url = next(iter(dep["urls"].values()), "")
            url = first_url
        table.add_row(dep["deployment"], components, url)

    console.print(table)


@app.command()
def create(
    ctx: typer.Context,
    web: bool = typer.Option(True, "--web/--no-web", help="Open the self-service portal in the browser"),
) -> None:
    """Create a new project via the self-service portal."""
    client, _ = get_helpers(ctx)
    portal_url = f"{client.web_url}/projects/new"

    if web:
        print(f"Opening self-service portal: {portal_url}", file=sys.stderr)
        webbrowser.open(portal_url)
    else:
        print(portal_url)


@app.command()
@handle_api_errors
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

    Requires ZAD_API_KEY and ZAD_PROJECT_ID (or --api-key and -p).

    [bold]Examples:[/bold]

        $ zad project deploy -d staging --component web --image ghcr.io/org/app:v1.2

        $ zad project deploy -d staging --components '[{"name":"web","image":"ghcr.io/org/app:v1.2"}]'

        $ zad project deploy -d pr-42 --component web --image ghcr.io/org/app:pr-42 --clone-from production
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

    result = client.upsert_deployment(project, request.to_api_payload())
    formatter.render(result)


@app.command()
@handle_api_errors
def refresh(
    ctx: typer.Context,
    force_clone: bool = typer.Option(False, "--force-clone", help="Force clone during refresh"),
) -> None:
    """Refresh all deployments from git.

    Requires ZAD_API_KEY and ZAD_PROJECT_ID (or --api-key and -p)
    """
    project = require_project(ctx)
    client, formatter = get_helpers(ctx)

    result = client.refresh_project(project, force_clone=force_clone)
    formatter.render(result)


@app.command()
@handle_api_errors
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

    confirm_action(f"Delete project '{project}' and all its resources?", yes)

    result = client.delete_project(project, confirm=True, force=force)
    formatter.render(result)
    formatter.render_success(f"Project '{project}' deleted.")


@app.command()
@handle_api_errors
def subdomains(ctx: typer.Context) -> None:
    """List subdomains for a project.

    Requires ZAD_API_KEY and ZAD_PROJECT_ID (or --api-key and -p)
    """
    project = require_project(ctx)
    client, formatter = get_helpers(ctx)

    result = client.list_subdomains(project)
    formatter.render(result)
