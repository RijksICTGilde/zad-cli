"""Service commands: types, add, delete."""

from __future__ import annotations

from typing import Annotated

import typer

from zad_cli.helpers import confirm_action, get_helpers, handle_api_errors, render_dry_run, require_project
from zad_cli.services import VALID_SERVICES, validate_service

app = typer.Typer(
    help="Manage services.\n\nRequires ZAD_API_KEY and ZAD_PROJECT_ID (or --api-key and -p).",
    no_args_is_help=True,
)

_SERVICE_HELP = "One of: " + ", ".join(VALID_SERVICES)


@app.command("types")
def list_service_types(ctx: typer.Context) -> None:
    """List available service types that can be added to a project.

    [bold]Example:[/bold]

        $ zad service types
    """
    formatter = ctx.obj["formatter"]

    rows = [{"service": s} for s in VALID_SERVICES]

    if formatter.fmt in ("json", "yaml"):
        formatter.render(rows)
        return

    formatter.render(rows, columns=["service"], title="Available Services")


@app.command()
@handle_api_errors
def add(
    ctx: typer.Context,
    service_name: str = typer.Argument(help=_SERVICE_HELP),  # noqa: B008
    components: Annotated[
        list[str] | None,
        typer.Option("--component", "-c", help="Component to add the service to, repeatable"),
    ] = None,
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be sent without making the API call"),
) -> None:
    """Add a service to a project."""
    service_name = validate_service(service_name)
    project = require_project(ctx)
    client, formatter = get_helpers(ctx)

    payload: dict = {"service": service_name}
    if components:
        payload["components"] = components

    if dry_run:
        render_dry_run(formatter, "POST", f"/v2/projects/{project}/services", payload)
        return

    result = client.add_service(project, payload)
    formatter.render(result)
    formatter.render_success(f"Service '{service_name}' added.")


@app.command()
@handle_api_errors
def delete(
    ctx: typer.Context,
    service_name: str = typer.Argument(help=_SERVICE_HELP),  # noqa: B008
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be sent without making the API call"),
) -> None:
    """Delete a service from a project.

    [bold]Example:[/bold]

        $ zad service delete postgresql-database
    """
    service_name = validate_service(service_name)
    project = require_project(ctx)
    client, formatter = get_helpers(ctx)

    if dry_run:
        render_dry_run(formatter, "DELETE", f"/v2/projects/{project}/services/{service_name}")
        return

    confirm_action(f"Delete service '{service_name}' from project '{project}'?", yes)

    result = client.remove_service(project, service_name)
    formatter.render(result)
    formatter.render_success(f"Service '{service_name}' deleted.")
