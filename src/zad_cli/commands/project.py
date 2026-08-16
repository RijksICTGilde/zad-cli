"""Project commands: list, status, refresh, delete, subdomains, check-subdomain."""

from __future__ import annotations

from typing import Any

import typer

from zad_cli.helpers import (
    age,
    confirm_action,
    get_helpers,
    handle_api_errors,
    issues_cell,
    one_name,
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

    settings = ctx.obj["settings"]
    # The issuer and client are what a renewal needs; without them an expired token is
    # simply expired, which is the five-minute problem this exists to avoid.
    token = credentials.get_token(issuer=settings.sso_issuer, client_id=settings.keycloak_client_id)
    if token:
        return token
    formatter = ctx.obj["formatter"]
    formatter.render_error(
        "Not signed in.",
        details={"fix": "Run `zadctl login`, or set ZAD_SSO_TOKEN to a token you already have."},
    )
    raise typer.Exit(1)


def _member_projects(ctx: typer.Context) -> list[dict]:
    """The projects you are a member of, as the API reports them.

    Nothing is stored here. One directory holds one project, so writing a key per project
    would mean the last one listed decides what this directory talks to.
    """
    token = _require_token(ctx)
    client, _ = get_helpers(ctx, require_api_key=False)
    result = client.list_projects_sso(token)
    items = result.get("projects", []) if isinstance(result, dict) else result
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


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
                "fix": "Pass a name (`zadctl project use <name>`), or run this in a terminal to pick one from a list.",
                "see": "zadctl project list",
            },
        )
        raise typer.Exit(1)

    projects = _member_projects(ctx)
    if not projects:
        formatter.render_error(
            "You are not a member of any project.",
            details={"fix": "Create one with `zadctl project create <name> --description <what it is for>`."},
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


def _key_for(ctx: typer.Context, name: str) -> str | None:
    """The API key the platform reports for one project, or None when it cannot say.

    Needs the SSO token, because that is what listing projects takes. Without one there is
    nothing to look up, which is a reason to warn rather than to fail: setting the project
    is still useful when the key comes from the environment.
    """
    from zad_cli import credentials

    if not credentials.get_token():
        return None
    try:
        for item in _member_projects(ctx):
            if item.get("name") == name:
                return item.get("api_key") or None
    except Exception:  # noqa: BLE001 - a lookup that fails must not stop the switch
        return None
    return None


@app.command("list")
@handle_api_errors
def list_projects(ctx: typer.Context) -> None:
    """List the projects you are a member of.

    Signs in with your own account (`zadctl login`), not with a project API key: you need
    the project name before you can have its key.

    [bold]Keys are not part of this answer at all.[/bold] The response carries the API key
    of every project you administer; the rows are built from name, role and description
    only, in every output format. Not masked, not "yes/no", absent: one command that could
    put every key you have into a screen or a transcript is one command too many, and the
    caller is as often a script or an agent as a person. `zadctl project use <name>` stores
    the key where the CLI needs it.

    [bold]Example:[/bold]

        $ zadctl project list
    """
    from zad_cli import credentials

    token = _require_token(ctx)
    client, formatter = get_helpers(ctx, require_api_key=False)

    result = client.list_projects_sso(token)
    items = result.get("projects", []) if isinstance(result, dict) else result
    if not isinstance(items, list):
        formatter.render(result)
        return

    active = credentials.get_active_project()
    rows = [
        {
            "active": "*" if item.get("name") == active else "",
            "name": item.get("name", ""),
            "role": item.get("role", ""),
            "description": item.get("description", ""),
        }
        for item in items
        if isinstance(item, dict)
    ]
    if formatter.fmt in ("json", "yaml"):
        formatter.render(rows)
        return
    formatter.render(rows, columns=["active", "name", "role", "description"])
    formatter.render_success("Work on one of these here with: zadctl project use <name>")


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
    project's API key, which exists in plaintext nowhere else: it is written to the .env.zadctl in
    this directory right away.

    You give a display name; the platform derives the technical name from it and returns it
    as `project_name`. That derived name, not the one you typed, is what every later
    command uses, so it is what gets stored and shown here.

    What is created is the base of a project: no components, no deployments, nothing on
    the cluster yet.

    [bold]Example:[/bold]

        $ zadctl project create "Mijn Project" --description "Nog een test"
    """
    from zad_cli import credentials

    display_name = one_name(display_name, display_name_opt, what="display name", flag="--display-name")
    payload: dict = {"display_name": display_name, "description": description}

    client, formatter = get_helpers(ctx, require_api_key=False)

    if dry_run:
        render_dry_run(formatter, "POST", "/v2/projects", payload)
        return

    token = _require_token(ctx)
    result = client.create_project_sso(token, payload)
    # The technical name is derived server-side and is what every later path and header
    # uses. Storing the key under the name that was typed would file it under a project
    # that does not exist.
    project_name = result.get("project_name") if isinstance(result, dict) else None
    if not project_name:
        formatter.render(result)
        formatter.render_error(
            "The API did not return a project_name, so the API key could not be stored under "
            "the right project. Run `zadctl project list` to find the project and its key."
        )
        raise typer.Exit(1)

    api_key = result.get("api_key")
    if api_key:
        # Stored before waiting, on purpose. The key comes back exactly once, so a failure
        # while the project is being built must not be the reason you no longer have it.
        path = credentials.store_api_key(project_name, api_key, ctx.obj["settings"].api_url)
        # Dropped from the answer, not masked: saying where it went is the useful part,
        # and the key itself has no business in a terminal scrollback or a task log.
        result = {key: value for key, value in result.items() if key != "api_key"}
    else:
        path = None

    poll_url = result.get("poll_url")
    if poll_url and client.wait:
        # Without this the command returns a key that answers 401 for the first few
        # seconds, and the next command in a script fails for a reason that has nothing to
        # do with the next command.
        from zad_cli.api.client import TaskFailedError, TaskTimeoutError, ZadApiError

        try:
            client.wait_for_project(token, poll_url)
        except (TaskFailedError, TaskTimeoutError, ZadApiError):
            # The name and the key are the two things that exist only here. Saying them
            # before the error goes up is the difference between a failure you can look
            # into and a project you cannot find.
            formatter.render(result)
            formatter.render_error(
                f"Project '{project_name}' was accepted but its setup did not finish."
                + (f" Its API key is in {path}." if path else "")
                + " Check `zadctl project status` once the error below is dealt with."
            )
            raise

    formatter.render(result)
    if path:
        formatter.render_success(f"Project '{project_name}' created. API key stored in {path}.")
    else:
        formatter.render_success(f"Project '{project_name}' created.")

    if use:
        credentials.set_active_project(project_name)
        formatter.render_success(f"Active project is now '{project_name}'.")

    # The API records the creation itself as a saved change, so `project pending` shows
    # one right after this -- even with rollout on. Said here, once, because that is the
    # moment it looks like the rollout setting was ignored.
    formatter.render_warning_text(
        "Note: the project's own creation counts as a saved change and shows up in "
        "`zadctl project pending` until the first `zadctl project refresh` takes it along."
    )


@handle_api_errors
def use(
    ctx: typer.Context,
    name: str = typer.Argument(None, help="Project to act on by default; omit to pick one from a list"),
    export: bool = typer.Option(
        False, "--export", help='Print shell exports for eval "$(zadctl project use x --export)"'
    ),
    write_env: str = typer.Option(None, "--write-env", help="Write the settings to this .env.zadctl file"),
) -> None:
    """Set the active project, from a name or from a list.

    Without a name this opens a list of the projects you are a member of and makes the
    one you pick active. That needs a terminal; in a pipeline or with --output json it
    fails instead of guessing.

    The project and its API key are written to the .env.zadctl in this directory, so two
    checkouts can work on two projects without getting in each other's way. An exported
    -p or ZAD_PROJECT_ID still wins over the file.

    [bold]Example:[/bold]

        $ zadctl project use mijn-project
        $ zadctl project use
    """
    from zad_cli import credentials
    from zad_cli.output.formatter import err_console

    formatter = ctx.obj["formatter"]
    if not name:
        name = _pick_project(ctx)

    # The key has to follow the project. Leaving the previous one in place is how you end
    # up authenticating against the new project with the old project's key, and the API
    # answers that with a bare 401. Switching away without a replacement therefore clears
    # it; staying on the same project changes nothing, so the key there is left alone.
    switching = credentials.get_active_project() != name
    api_key = _key_for(ctx, name) or (None if switching else credentials.get_api_key())
    credentials.store_api_key(name, api_key or "", ctx.obj["settings"].api_url)

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
    err_console.print(f"[dim]Commands here now act on '{name}' at {api_url}.[/dim]")
    if not api_key:
        # One message, and it says why: the key comes from the project listing, which
        # needs a sign-in. Being told twice that something is missing, without being told
        # what would produce it, is what makes this look broken rather than incomplete.
        cleared = " The previous project's key was cleared, so it cannot be used by mistake." if switching else ""
        formatter.render_error(
            f"No API key for '{name}'.{cleared}",
            details={
                "why": "The key comes from `project list`, which signs in with your own account.",
                "fix": "Run `zadctl login`, then this command again. Or set ZAD_API_KEY yourself.",
            },
        )


# One behaviour, two words: `use` was there first, `select` is what people type when they
# expect to be shown a list.
app.command("use")(use)
app.command("select")(use)


@app.command()
@handle_api_errors
def status(ctx: typer.Context) -> None:
    """Show project overview: deployments, components, and URLs.

    [bold]Example:[/bold]

        $ zadctl project status
    """
    project = require_project(ctx)
    client, formatter = get_helpers(ctx)

    result = client.project_status(project)

    if formatter.fmt in ("json", "yaml"):
        formatter.render(result)
        return

    from zad_cli.commands.deployment import status_cell

    console = formatter.console

    console.print(f"\n[bold]Project:[/bold] {result['project']}")
    console.print(f"[bold]Deployments:[/bold] {len(result['deployments'])}")

    if result["subdomains"]:
        sd = result["subdomains"][0]
        console.print(f"[bold]Custom domain:[/bold] {sd['subdomain']}.{sd['base_domain']}")

    # Status, revision and last sync were in the response all along and were not shown.
    # "Which deployments exist" is not the question someone asks a status command; "is it
    # healthy, and is what is running what I last pushed" is.
    rows = [
        {
            "deployment": dep["deployment"],
            "status": status_cell(dep.get("status")),
            "revision": (dep.get("sync_revision") or "-")[:12],
            "last sync": age(dep.get("last_synced_at")) or "-",
            "components": str(len(dep.get("components") or [])),
            "issues": issues_cell(dep.get("errors")),
        }
        for dep in result["deployments"]
    ]
    console.print()
    formatter.render(
        rows,
        columns=["deployment", "status", "revision", "last sync", "components", "issues"],
        title="Deployments",
    )

    # Under the table rather than in it: a URL is the longest thing here and squeezes every
    # other column, and it is what you copy rather than scan.
    urls = [
        (dep["deployment"], name, url) for dep in result["deployments"] for name, url in (dep.get("urls") or {}).items()
    ]
    if urls:
        console.print("\n[bold]URLs:[/bold]")
        for deployment, component, url in urls:
            console.print(f"  {deployment}/{component}: {url}")


@app.command()
@handle_api_errors
def refresh(
    ctx: typer.Context,
    force_clone: bool = typer.Option(False, "--force-clone", help="Force clone during refresh"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be sent without making the API call"),
) -> None:
    """Refresh all deployments from git, rolling out everything that is waiting.

    This reconciles the whole project file at once, so it is also how changes saved with
    --no-rollout reach the cluster. `zadctl project pending` shows what is waiting.

    [bold]Example:[/bold]

        $ zadctl project refresh
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


# A secret the API deliberately withheld. Rendering it as a value would say the setting is
# literally three asterisks; saying it is set without saying what it is, is the truth.
_WITHHELD = "***"


def _secret_aware(value: object) -> str:
    """One config value for a table, with a withheld secret named as such."""
    # The same words as `zadctl env list`, imported rather than retyped: two spellings of
    # one idea is what `tests/test_uniformity.py` exists to stop.
    from zad_cli.commands.values import WITHHELD_LABEL

    if value == _WITHHELD:
        return WITHHELD_LABEL
    if isinstance(value, dict):
        return ", ".join(f"{k}={_secret_aware(v)}" for k, v in value.items()) or "-"
    if value is None:
        return "-"
    return str(value)


def _env_names(names: object) -> str:
    """Env var names, keeping apart "none" from "could not be read".

    The API is explicit that ``null`` means it could not decrypt them; an empty list would
    claim we looked and found nothing, and those are different answers.
    """
    if names is None:
        return "(unreadable)"
    if not names:
        return "-"
    return ", ".join(str(n) for n in names)


def _with_age(since: object) -> str:
    """A timestamp with how long ago it was, because the raw ISO string is hard to read."""
    from zad_cli.helpers import age

    if not since:
        return "-"
    ago = age(since)
    return f"{since} ({ago})" if ago else str(since)


@app.command()
@handle_api_errors
def describe(
    ctx: typer.Context,
    part: str = typer.Option(None, "--part", help="Only one part: services, components or deployments"),
) -> None:
    """Show a project as it stands: its services, components and deployments.

    One call that answers "what is in this project": which platform services it uses and
    on which layer, the component definitions, and what each deployment runs. `--part`
    asks the API for just that piece instead of the whole.

    What this describes is the *project file*. When changes are saved but not rolled out
    the cluster is behind it, so the pending count is shown first.

    Secrets are never in the answer: environment variables come back as names, and a
    stored secret in a service config reads as withheld rather than as its value.

    [bold]Example:[/bold]

        $ zadctl project describe

        $ zadctl project describe --part services
    """
    project = require_project(ctx)
    client, formatter = get_helpers(ctx)

    parts = {"services": client.project_services, "components": client.project_components}
    if part is not None and part not in (*parts, "deployments"):
        raise typer.BadParameter(f"Unknown part '{part}'. Choose from: services, components, deployments.")

    if part in parts:
        result = parts[part](project)
    elif part == "deployments":
        result = {"project": project, "deployments": client.list_deployments(project)}
    else:
        result = client.project_detail(project)

    if formatter.fmt in ("json", "yaml"):
        formatter.render(result)
        return

    _render_description(formatter, project, result)


def _render_description(formatter: Any, project: str, result: dict) -> None:
    """The project as a table, in the order someone reads it: what, then what it uses."""
    console = formatter.console
    header = result.get("project")
    if isinstance(header, dict):
        console.print(f"\n[bold]Project:[/bold] {header.get('name', project)}")
        if header.get("display_name"):
            console.print(f"[bold]Display name:[/bold] {header['display_name']}")
        if header.get("description"):
            console.print(f"[bold]Description:[/bold] {header['description']}")
        if header.get("clusters"):
            console.print(f"[bold]Clusters:[/bold] {', '.join(header['clusters'])}")
    else:
        console.print(f"\n[bold]Project:[/bold] {header or project}")

    waiting = result.get("pending_rollout") or {}
    if waiting.get("count"):
        # First, not last: everything below describes the project file, and this says how
        # far the cluster is behind it.
        console.print(
            f"\n[yellow]{waiting['count']} change(s) saved but not rolled out"
            + (f", the oldest since {age(waiting.get('since'))}" if age(waiting.get("since")) else "")
            + ".[/yellow] Roll them out with: zadctl project refresh"
        )

    services = result.get("services")
    if services is not None:
        rows = [
            {
                "service": entry.get("name", ""),
                "layer": usage.get("target", ""),
                "where": usage.get("component") or usage.get("deployment") or "-",
                "config": _secret_aware(usage.get("config")),
            }
            for entry in services
            for usage in entry.get("usages") or [{}]
        ]
        console.print()
        formatter.render(rows, columns=["service", "layer", "where", "config"], title="Services in use")

    components = result.get("components")
    if components is not None:
        rows = [
            {
                "component": c.get("name", ""),
                "ports": ", ".join(str(p) for p in (c.get("ports") or {}).get("inbound") or []) or "-",
                "services": ", ".join(c.get("services") or []) or "-",
                "env vars": _env_names(c.get("env_var_names")),
                "attachments": ", ".join(a.get("reference", "") for a in c.get("attachments") or []) or "-",
            }
            for c in components
        ]
        console.print()
        formatter.render(
            rows,
            columns=["component", "ports", "services", "env vars", "attachments"],
            title="Components",
        )

    deployments = result.get("deployments")
    if deployments is not None:
        rows = [
            {
                "deployment": d.get("name") or d.get("deployment", ""),
                "components": ", ".join(c.get("reference") or c.get("name", "") for c in d.get("components") or [])
                or "-",
                "status": d.get("status", "-"),
                "issues": issues_cell(d.get("errors")),
            }
            for d in deployments
        ]
        console.print()
        formatter.render(rows, columns=["deployment", "components", "status", "issues"], title="Deployments")

        # The addresses, per deployment and per component. The API computes them and hands
        # them over on every deployment; leaving them out meant the one question a reader
        # most often has here ("where is it, then?") needed a second command.
        urls = [
            {"deployment": d.get("name") or d.get("deployment", ""), "component": component, "url": url}
            for d in deployments
            for component, url in sorted((d.get("urls") or {}).items())
        ]
        if urls:
            console.print()
            formatter.render(urls, columns=["deployment", "component", "url"], title="URLs")


@app.command()
@handle_api_errors
def pending(ctx: typer.Context) -> None:
    """Show changes that are saved but not rolled out yet.

    Everything saved with --no-rollout counts here until `zadctl project refresh` reconciles
    the project. A count above zero means the cluster is behind the project file.

    [bold]Example:[/bold]

        $ zadctl project pending
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
            "oldest change": _with_age(result.get("since")),
            "kinds": ", ".join(result.get("task_types") or []) or "-",
        },
        title="Pending rollout",
    )
    if result.get("count"):
        formatter.render_success("Roll them out with: zadctl project refresh")


@app.command()
@handle_api_errors
def delete(
    ctx: typer.Context,
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
    force: bool = typer.Option(False, "--force", help="Force deletion"),
    ignore_not_found: bool = typer.Option(False, "--ignore-not-found", help="Exit 0 if the project doesn't exist"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be sent without making the API call"),
) -> None:
    """Delete a project and all its resources.

    If it was the active project, its name and key are removed from the .env.zadctl
    afterwards: they refer to something that no longer exists, and leaving them
    turns every later command into an authentication error about a project that
    is simply gone. You stay signed in.

    [bold]--ignore-not-found[/bold] spells the same idea as on `deployment delete`: a
    teardown step runs precisely when something went wrong earlier, so "it is already
    gone" is the outcome it wanted, not a failure.

    [bold]Example:[/bold]

        $ zadctl project delete
    """
    from zad_cli import credentials
    from zad_cli.api.client import ZadApiError

    # Deleting the active project also clears it from the .env.zadctl, so a second run has no
    # project and no key at all. That is the same "already gone" this flag is for, and it
    # happens before any call: reading it here is what makes a teardown step idempotent.
    # The formatter comes straight off the context rather than through get_helpers: that
    # builds a client, which needs an API key, which was cleared along with the project.
    if ignore_not_found and not ctx.obj["settings"].project_id:
        formatter = ctx.obj["formatter"]
        formatter.render({"deleted": False, "reason": "no_active_project"})
        formatter.render_success("No active project (already deleted).")
        return

    project = require_project(ctx)
    client, formatter = get_helpers(ctx)

    if dry_run:
        render_dry_run(formatter, "DELETE", f"/projects/{project}", {"confirmDeletion": True, "force": force})
        return

    confirm_action(f"Delete project '{project}' and all its resources?", yes, ctx)

    try:
        result = client.delete_project(project, confirm=True, force=force)
    except ZadApiError as e:
        if e.status_code == 404 and ignore_not_found:
            formatter.render({"deleted": False, "reason": "not_found"})
            formatter.render_success(f"Project '{project}' not found (already deleted).")
            if credentials.get_active_project() == project:
                credentials.forget_project()
            return
        raise
    formatter.render(result)
    formatter.render_success(f"Project '{project}' deleted.")

    if credentials.get_active_project() == project:
        credentials.forget_project()
        formatter.render_success("Removed it from the .env.zadctl; you are still signed in.")


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

    [bold]The platform's answer is not usable right now[/bold], and this command says so
    rather than passing it on: two practice runs got a refusal for every name they tried,
    including names that certainly exist. Go ahead and claim the subdomain on `deployment
    create`; that path validates it for real.

    [bold]Example:[/bold]

        $ zadctl project check-subdomain my-app apps.example.nl
    """
    from zad_cli.api.client import ZadApiError
    from zad_cli.api.errors import Diagnosis, Fault

    client, formatter = get_helpers(ctx)

    try:
        result = client.check_subdomain(subdomain, base_domain)
    except ZadApiError as e:
        # 404 for every name, 401 "Missing project_name parameter" for every name before
        # that: whichever way it fails today, the one thing it does not mean is "this
        # subdomain is taken". Passing that on as a verdict is worse than having no command,
        # because a script reads the non-zero exit as "unavailable" and picks another name.
        if e.status_code not in (401, 404):
            raise
        raise ZadApiError(
            e.status_code,
            "The platform's subdomain check is unavailable.",
            diagnosis=Diagnosis(
                fault=Fault.PLATFORM,
                headline="The platform's subdomain check is unavailable.",
                summary=(
                    f"It answered HTTP {e.status_code} for '{subdomain}.{base_domain}'. It answers the same "
                    "for names that certainly exist, so this is not a verdict on the name."
                ),
                next_steps=[
                    "Claim it on `zadctl deployment create --subdomain`, which validates it for real.",
                    "See what this project's cluster offers with `zadctl service describe publish-on-web`.",
                ],
                status_code=e.status_code,
            ),
        ) from e
    formatter.render(result)
