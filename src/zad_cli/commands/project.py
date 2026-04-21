"""Project commands: list, status, refresh, delete, subdomains, check-subdomain."""

from __future__ import annotations

import typer

from zad_cli.helpers import confirm_action, get_helpers, handle_api_errors, render_dry_run, require_project

app = typer.Typer(
    help="Manage projects.\n\nMost commands require ZAD_API_KEY and ZAD_PROJECT_ID (or --api-key and -p).",
    no_args_is_help=True,
)


@app.command("list")
@handle_api_errors
def list_projects(ctx: typer.Context) -> None:
    """List all projects you have access to.

    Only requires ZAD_API_KEY (no project needed).

    [bold]Example:[/bold]

        $ zad project list
    """
    client, formatter = get_helpers(ctx)

    result = client.list_projects()
    if isinstance(result, dict) and "items" in result:
        items = result["items"]
    elif isinstance(result, list):
        items = result
    else:
        formatter.render(result)
        return

    formatter.render(items, title="Projects")


@app.command()
@handle_api_errors
def status(ctx: typer.Context) -> None:
    """Show project overview: deployments, components, and URLs.

    [bold]Example:[/bold]

        $ zad project status
    """
    project = require_project(ctx)
    client, formatter = get_helpers(ctx)

    result = client.project_status(project)

    if formatter.fmt in ("json", "yaml"):
        formatter.render(result)
        return

    from rich.table import Table

    console = formatter.console

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
@handle_api_errors
def refresh(
    ctx: typer.Context,
    force_clone: bool = typer.Option(False, "--force-clone", help="Force clone during refresh"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be sent without making the API call"),
) -> None:
    """Refresh all deployments from git."""
    project = require_project(ctx)
    client, formatter = get_helpers(ctx)

    if dry_run:
        render_dry_run(formatter, "POST", f"/v2/projects/{project}/:refresh", {"force_clone": force_clone})
        return

    result = client.refresh_project(project, force_clone=force_clone)
    formatter.render(result)
    formatter.render_success(f"Project '{project}' refreshed.")


@app.command()
@handle_api_errors
def delete(
    ctx: typer.Context,
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
    force: bool = typer.Option(False, "--force", help="Force deletion"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be sent without making the API call"),
) -> None:
    """Delete a project and all its resources."""
    project = require_project(ctx)
    client, formatter = get_helpers(ctx)

    if dry_run:
        render_dry_run(formatter, "DELETE", f"/projects/{project}", {"confirmDeletion": True, "force": force})
        return

    confirm_action(f"Delete project '{project}' and all its resources?", yes)

    result = client.delete_project(project, confirm=True, force=force)
    formatter.render(result)
    formatter.render_success(f"Project '{project}' deleted.")


@app.command()
@handle_api_errors
def subdomains(ctx: typer.Context) -> None:
    """List subdomains for a project."""
    project = require_project(ctx)
    client, formatter = get_helpers(ctx)

    result = client.list_subdomains(project)

    if formatter.fmt in ("json", "yaml"):
        formatter.render(result)
        return

    items = result.get("items", result) if isinstance(result, dict) else result
    if isinstance(items, list):
        formatter.render(
            items,
            columns=["subdomain", "base_domain", "project_name", "status"],
            title=f"Subdomains for {project}",
        )
    else:
        formatter.render(result)


@app.command("check-subdomain")
@handle_api_errors
def check_subdomain(
    ctx: typer.Context,
    subdomain: str = typer.Argument(help="Subdomain to check"),
    base_domain: str = typer.Argument(help="Base domain (e.g. apps.example.nl)"),
) -> None:
    """Check if a subdomain is available.

    Utility for checking availability before using --subdomain in deployment create.
    Only requires ZAD_API_KEY (no project needed).

    [bold]Example:[/bold]

        $ zad project check-subdomain my-app apps.example.nl
    """
    client, formatter = get_helpers(ctx)

    result = client.check_subdomain(subdomain, base_domain)
    formatter.render(result)
