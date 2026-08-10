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


def _member_projects(ctx: typer.Context) -> list[dict]:
    """The projects you are a member of, and their keys remembered for later commands."""
    from zad_cli import credentials

    token = _require_token(ctx)
    client, _ = get_helpers(ctx, require_api_key=False)
    result = client.list_projects_sso(token)
    items = result.get("projects", []) if isinstance(result, dict) else result
    if not isinstance(items, list):
        return []
    projects = [item for item in items if isinstance(item, dict)]
    for item in projects:
        if item.get("api_key"):
            credentials.store_api_key(item["name"], item["api_key"])
    return projects


def _pick_project(ctx: typer.Context) -> str:
    """Choose a project from a list. Only in a terminal, and never printing a key.

    Without a terminal there is nothing to pick with, and guessing which project a
    pipeline meant is exactly the mistake this CLI must not make: it fails instead, and
    says which two ways forward there are.
    """
    from zad_cli import credentials
    from zad_cli.picker import Choice, is_interactive, pick

    formatter = ctx.obj["formatter"]

    if formatter.fmt != "table" or not is_interactive():
        formatter.render_error(
            "No project name given.",
            details={
                "fix": "Pass a name (`zad project use <name>`), or run this in a terminal to pick one from a list.",
                "see": "zad project list",
            },
        )
        raise typer.Exit(1)

    projects = _member_projects(ctx)
    if not projects:
        formatter.render_error(
            "You are not a member of any project.",
            details={"fix": "Create one with `zad project create <name> --description <what it is for>`."},
        )
        raise typer.Exit(1)

    active = credentials.get_active_project()
    choices = [
        # Deliberately no API key, not even shortened: this list is drawn on a screen
        # somebody may well be sharing.
        Choice(
            value=str(item.get("name", "")),
            label=str(item.get("name", "")),
            hint=" ".join(
                part
                for part in (
                    str(item.get("display_name") or item.get("description") or ""),
                    "(active)" if item.get("name") == active else "",
                )
                if part
            ),
        )
        for item in projects
        if item.get("name")
    ]
    initial = next((i for i, choice in enumerate(choices) if choice.value == active), 0)

    chosen = pick(choices, title="Pick a project", initial=initial)
    if not chosen:
        formatter.render_error("Nothing picked; the active project is unchanged.")
        raise typer.Exit(1)
    return chosen


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

    active = credentials.get_active_project()
    rows = [
        {
            "active": "*" if item.get("name") == active else "",
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
    formatter.render(rows, columns=["active", "name", "role", "description", "api_key"], title="Projects")
    if store and any(item.get("api_key") for item in items if isinstance(item, dict)):
        formatter.render_success("API keys stored. Pick one with: zad project use <name>")


def _one_display_name(positional: str | None, option: str | None) -> str:
    """The display name, however it was spelled, refusing two spellings that disagree.

    Both forms exist on purpose: the positional reads well by hand, and `--display-name`
    says what the value *is*, which is what a script or an agent wants. What may not
    happen is the two disagreeing and one silently winning.
    """
    if positional and option and positional != option:
        raise typer.BadParameter(f"'{positional}' and --display-name '{option}' disagree; pass one of the two.")
    name = positional or option
    if not name:
        raise typer.BadParameter("Missing display name: pass it as an argument or with --display-name.")
    return name


@app.command()
@handle_api_errors
def create(
    ctx: typer.Context,
    display_name: str = typer.Argument(None, help="Name shown in the portal; the technical name is derived from it"),
    display_name_opt: str = typer.Option(
        None, "--display-name", help="Same value as the positional, spelled out; pass one of the two"
    ),
    description: str = typer.Option(..., "--description", help="What this project is for"),
    use: bool = typer.Option(True, "--use/--no-use", help="Make this the active project afterwards"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be sent without making the API call"),
) -> None:
    """Create a project.

    Signs in with your own account, like `project list`. The response carries the new
    project's API key, which exists in plaintext nowhere else: it is stored right away in
    ~/.config/zad/credentials.toml.

    You give a display name; the platform derives the technical name from it and returns it
    as `project_name`. That derived name, not the one you typed, is what every later
    command uses, so it is what gets stored and shown here.

    What is created is the base of a project: no components, no deployments, nothing on
    the cluster yet.

    [bold]Example:[/bold]

        $ zad project create "Mijn Project" --description "Nog een test"
    """
    from zad_cli import credentials

    display_name = _one_display_name(display_name, display_name_opt)
    payload: dict = {"display_name": display_name, "description": description}

    client, formatter = get_helpers(ctx, require_api_key=False)

    if dry_run:
        render_dry_run(formatter, "POST", "/v2/projects", payload)
        return

    token = _require_token(ctx)
    confirm_action(f"Create project '{display_name}'?", yes)

    result = client.create_project_sso(token, payload)
    # The technical name is derived server-side and is what every later path and header
    # uses. Storing the key under the name that was typed would file it under a project
    # that does not exist.
    project_name = result.get("project_name") if isinstance(result, dict) else None
    if not project_name:
        formatter.render(result)
        formatter.render_error(
            "The API did not return a project_name, so the API key could not be stored under "
            "the right project. Run `zad project list` to find the project and its key."
        )
        raise typer.Exit(1)

    api_key = result.get("api_key")
    if api_key:
        path = credentials.store_api_key(project_name, api_key)
        # The key is returned exactly once; showing it masked and saying where it went is
        # more useful than printing a secret into a terminal scrollback.
        result = {**result, "api_key": credentials.redact(api_key)}
        formatter.render(result)
        formatter.render_success(f"Project '{project_name}' created. API key stored in {path}.")
    else:
        formatter.render(result)
        formatter.render_success(f"Project '{project_name}' created.")

    if use:
        credentials.set_active_project(project_name)
        formatter.render_success(f"Active project is now '{project_name}'.")


@handle_api_errors
def use(
    ctx: typer.Context,
    name: str = typer.Argument(None, help="Project to act on by default; omit to pick one from a list"),
    export: bool = typer.Option(False, "--export", help='Print shell exports for eval "$(zad project use x --export)"'),
    write_env: str = typer.Option(None, "--write-env", help="Write the settings to this .env file"),
) -> None:
    """Set the active project, from a name or from a list.

    Without a name this opens a list of the projects you are a member of and makes the
    one you pick active. That needs a terminal; in a pipeline or with --output json it
    fails instead of guessing.

    The active project is the fallback: -p and ZAD_PROJECT_ID still win over it, so a
    script that sets them keeps behaving the same. Nothing else has to be set: the API
    key that belongs to the project comes from the credentials store.

    [bold]Example:[/bold]

        $ zad project use mijn-project
        $ zad project use
    """
    from zad_cli import credentials
    from zad_cli.output.formatter import err_console

    formatter = ctx.obj["formatter"]
    if not name:
        name = _pick_project(ctx)

    credentials.set_active_project(name)
    api_key = credentials.get_api_key(name)

    if export:
        # To stdout: this is the data, meant to be eval'd. What was written is said on
        # stderr, so `eval "$(...)"` still only swallows the exports.
        print(f"export ZAD_PROJECT_ID={name}")
        if api_key:
            print(f"export ZAD_API_KEY={api_key}")
        err_console.print(
            f"[dim]Exported ZAD_PROJECT_ID{' and ZAD_API_KEY' if api_key else ''} for project '{name}'.[/dim]"
        )
        return

    if write_env:
        from pathlib import Path

        lines = [f"ZAD_PROJECT_ID={name}"]
        if api_key:
            lines.append(f"ZAD_API_KEY={api_key}")
        path = Path(write_env).expanduser()
        path.write_text("\n".join(lines) + "\n")
        path.chmod(0o600)
        written = ", ".join(line.split("=", 1)[0] for line in lines)
        formatter.render_success(f"Wrote {written} to {path} (mode 0600).")

    formatter.render_success(f"Active project is now '{name}'.")
    api_url = ctx.obj["settings"].api_url
    err_console.print(
        f"[dim]Commands now act on '{name}' at {api_url}{'; no environment variable needed.' if api_key else '.'}[/dim]"
    )
    if not api_key:
        formatter.render_success("No API key stored for it yet; run `zad project list` or set ZAD_API_KEY.")


# One behaviour, two words: `use` was there first, `select` is what people type when they
# expect to be shown a list.
app.command("use")(use)
app.command("select")(use)


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
