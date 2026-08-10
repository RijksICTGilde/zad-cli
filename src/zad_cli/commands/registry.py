"""`zad registry add`: register a private image registry the project may pull from.

Two shapes, one endpoint each: credentials the platform encrypts for you, or a reference
to a ``dockerconfigjson`` secret that already exists in the cluster.

These are still the v1 endpoints; the API has no v2 equivalent yet. When one appears,
only the client methods move.
"""

from __future__ import annotations

import typer

from zad_cli.helpers import (
    confirm_action,
    get_helpers,
    handle_api_errors,
    render_dry_run,
    require_project,
    surface_warnings,
)

app = typer.Typer(
    help="Manage image registries.\n\nRequires ZAD_API_KEY and ZAD_PROJECT_ID (or --api-key and -p).",
    no_args_is_help=True,
)


@app.command()
@handle_api_errors
def add(
    ctx: typer.Context,
    name: str = typer.Argument(help="Unique name for this registry within the project"),
    url: str = typer.Option(..., "--url", help="Registry URL without protocol, e.g. ghcr.io/org"),
    username: str = typer.Option(None, "--username", help="Registry username or token name"),
    password: str = typer.Option(
        None, "--password", help="Registry password or token; prefer @file to keep it out of your shell history"
    ),
    secret_name: str = typer.Option(
        None, "--secret-name", help="Name of an existing Kubernetes dockerconfigjson secret to use instead"
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be sent without making the API call"),
) -> None:
    """Register a private registry, by credentials or by existing secret.

    Give --username and --password, or --secret-name; the two are different endpoints and
    mixing them asks for two things at once.

    [bold]Example:[/bold]

        $ zad registry add ghcr --url ghcr.io/org --username bot --password @./token.txt
    """
    from zad_cli.manifest import resolve_value_reference

    project = require_project(ctx)
    client, formatter = get_helpers(ctx)

    by_secret = bool(secret_name)
    by_credentials = bool(username or password)
    if by_secret and by_credentials:
        raise typer.BadParameter("Use --secret-name, or --username with --password, not both.")
    if not by_secret and not (username and password):
        raise typer.BadParameter("Give --username and --password, or --secret-name.")

    if by_secret:
        payload = {"name": name, "url": url, "secretName": secret_name}
        path = f"/projects/{project}/registries/by-secret"
    else:
        payload = {"name": name, "url": url, "username": username, "password": resolve_value_reference(password)}
        path = f"/projects/{project}/registries/by-credentials"

    if dry_run:
        # The password is a secret; a dry run shows the shape, not the value.
        shown = {**payload, "password": "********"} if not by_secret else payload
        render_dry_run(formatter, "POST", path, shown)
        return

    confirm_action(f"Add registry '{name}' to project '{project}'?", yes, ctx)

    result = (
        client.add_registry_by_secret(project, payload)
        if by_secret
        else client.add_registry_by_credentials(project, payload)
    )
    formatter.render(result)
    formatter.render_success(f"Registry '{name}' added.")
    surface_warnings(ctx, formatter, result)
