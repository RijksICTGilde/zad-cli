"""Project commands: list, status, refresh, delete, subdomains, check-subdomain."""

from __future__ import annotations

import typer

from zad_cli.helpers import (
    confirm_action,
    get_helpers,
    handle_api_errors,
    issues_cell,
    render_dry_run,
    require_project,
    surface_warnings,
)

app = typer.Typer(
    help="Manage projects.\n\nMost commands require ZAD_API_KEY and ZAD_PROJECT_ID (or --api-key and -p).",
    no_args_is_help=True,
)


def _require_token(ctx: typer.Context) -> str:
    """The SSO token, or a message saying how to get one.

    Listing and creating projects are the only calls that use it: both need to work
    before the caller knows a project name, so a project API key cannot authenticate them.
    """
    from zad_cli import credentials

    token = credentials.get_token()
    if token:
        return token
    formatter = ctx.obj["formatter"]
    formatter.render_error(
        "Not signed in.",
        details={"fix": "Run `zad login`, or set ZAD_SSO_TOKEN to a token you already have."},
    )
    raise typer.Exit(1)


@app.command("list")
@handle_api_errors
def list_projects(
    ctx: typer.Context,
    show_keys: bool = typer.Option(False, "--show-keys", help="Print the API keys in full instead of masking them"),
    store: bool = typer.Option(True, "--store/--no-store", help="Remember the returned API keys for later commands"),
) -> None:
    """List the projects you are a member of.

    Signs in with your own account (`zad login`), not with a project API key: you need
    the project name before you can have its key.

    The response carries the API key of every project you administer. Keys are masked
    unless you ask for them and are never written to logs.

    [bold]Example:[/bold]

        $ zad project list
    """
    from zad_cli import credentials

    token = _require_token(ctx)
    client, formatter = get_helpers(ctx, require_api_key=False)

    result = client.list_projects_sso(token)
    items = result.get("projects", []) if isinstance(result, dict) else result
    if not isinstance(items, list):
        formatter.render(result)
        return

    if store:
        for item in items:
            if isinstance(item, dict) and item.get("api_key"):
                credentials.store_api_key(item["name"], item["api_key"])

    rows = [
        {
            "name": item.get("name", ""),
            "role": item.get("role", ""),
            "description": item.get("description", ""),
            "api_key": (item.get("api_key") or "") if show_keys else credentials.redact(item.get("api_key")),
        }
        for item in items
        if isinstance(item, dict)
    ]
    if formatter.fmt in ("json", "yaml"):
        formatter.render(rows)
        return
    formatter.render(rows, columns=["name", "role", "description", "api_key"], title="Projects")
    if store and any(item.get("api_key") for item in items if isinstance(item, dict)):
        formatter.render_success("API keys stored. Pick one with: zad project use <name>")


@app.command()
@handle_api_errors
def create(
    ctx: typer.Context,
    name: str = typer.Argument(help="Technical project name (lowercase letters, digits and hyphens)"),
    description: str = typer.Option(..., "--description", help="What this project is for"),
    display_name: str = typer.Option(None, "--display-name", help="Name shown in the portal"),
    use: bool = typer.Option(True, "--use/--no-use", help="Make this the active project afterwards"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be sent without making the API call"),
) -> None:
    """Create a project.

    Signs in with your own account, like `project list`. The response carries the new
    project's API key, which exists in plaintext nowhere else: it is stored right away in
    ~/.config/zad/credentials.toml.

    What is created is the base of a project — no components, no deployments, nothing on
    the cluster yet.

    [bold]Example:[/bold]

        $ zad project create mijn-project --description "Nog een test"
    """
    from zad_cli import credentials

    payload: dict = {"name": name, "description": description}
    if display_name:
        payload["display_name"] = display_name

    client, formatter = get_helpers(ctx, require_api_key=False)

    if dry_run:
        render_dry_run(formatter, "POST", "/v2/projects", payload)
        return

    token = _require_token(ctx)
    confirm_action(f"Create project '{name}'?", yes)

    result = client.create_project_sso(token, payload)
    api_key = result.get("api_key") if isinstance(result, dict) else None
    if api_key:
        path = credentials.store_api_key(name, api_key)
        # The key is returned exactly once; showing it masked and saying where it went is
        # more useful than printing a secret into a terminal scrollback.
        result = {**result, "api_key": credentials.redact(api_key)}
        formatter.render(result)
        formatter.render_success(f"Project '{name}' created. API key stored in {path}.")
    else:
        formatter.render(result)
        formatter.render_success(f"Project '{name}' created.")

    if use:
        credentials.set_active_project(name)
        formatter.render_success(f"Active project is now '{name}'.")


@app.command()
def use(
    ctx: typer.Context,
    name: str = typer.Argument(help="Project to act on by default"),
    export: bool = typer.Option(False, "--export", help='Print shell exports for eval "$(zad project use x --export)"'),
    write_env: str = typer.Option(None, "--write-env", help="Write the settings to this .env file"),
) -> None:
    """Set the active project.

    The active project is the fallback: -p and ZAD_PROJECT_ID still win over it, so a
    script that sets them keeps behaving the same.

    [bold]Example:[/bold]

        $ zad project use mijn-project
    """
    from zad_cli import credentials

    formatter = ctx.obj["formatter"]
    credentials.set_active_project(name)
    api_key = credentials.get_api_key(name)

    if export:
        # To stdout: this is the data, meant to be eval'd.
        print(f"export ZAD_PROJECT_ID={name}")
        if api_key:
            print(f"export ZAD_API_KEY={api_key}")
        return

    if write_env:
        from pathlib import Path

        lines = [f"ZAD_PROJECT_ID={name}"]
        if api_key:
            lines.append(f"ZAD_API_KEY={api_key}")
        path = Path(write_env).expanduser()
        path.write_text("\n".join(lines) + "\n")
        path.chmod(0o600)
        formatter.render_success(f"Wrote {path} (mode 0600).")

    formatter.render_success(f"Active project is now '{name}'.")
    if not api_key:
        formatter.render_success("No API key stored for it yet; run `zad project list` or set ZAD_API_KEY.")


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
    table.add_column("Issues")
    table.add_column("URL")

    for dep in result["deployments"]:
        components = ", ".join(dep["components"])
        url = ""
        if dep.get("urls"):
            first_url = next(iter(dep["urls"].values()), "")
            url = first_url
        table.add_row(dep["deployment"], components, issues_cell(dep.get("errors")), url)

    console.print(table)


@app.command()
@handle_api_errors
def refresh(
    ctx: typer.Context,
    force_clone: bool = typer.Option(False, "--force-clone", help="Force clone during refresh"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be sent without making the API call"),
) -> None:
    """Refresh all deployments from git, rolling out everything that is waiting.

    This reconciles the whole project file at once, so it is also how changes saved with
    --no-rollout reach the cluster. `zad project pending` shows what is waiting.

    [bold]Example:[/bold]

        $ zad project refresh
    """
    project = require_project(ctx)
    client, formatter = get_helpers(ctx)

    if dry_run:
        render_dry_run(formatter, "POST", f"/v2/projects/{project}/:refresh", {"force_clone": force_clone})
        return

    result = client.refresh_project(project, force_clone=force_clone)
    formatter.render(result)
    formatter.render_success(f"Project '{project}' refreshed.")
    surface_warnings(ctx, formatter, result)


@app.command()
@handle_api_errors
def pending(ctx: typer.Context) -> None:
    """Show changes that are saved but not rolled out yet.

    Everything saved with --no-rollout counts here until `zad project refresh` reconciles
    the project. A count above zero means the cluster is behind the project file.

    [bold]Example:[/bold]

        $ zad project pending
    """
    project = require_project(ctx)
    client, formatter = get_helpers(ctx)

    result = client.pending_rollout(project)

    if formatter.fmt in ("json", "yaml"):
        formatter.render(result)
        return

    formatter.render_detail(
        {
            "project": result.get("project", project),
            "pending changes": result.get("count", 0),
            "oldest change": result.get("since") or "-",
            "kinds": ", ".join(result.get("task_types") or []) or "-",
        },
        title="Pending rollout",
    )
    if result.get("count"):
        formatter.render_success("Roll them out with: zad project refresh")


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
