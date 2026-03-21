"""Service commands: list, add."""

from __future__ import annotations

from typing import Annotated

import typer

from zad_cli.helpers import get_helpers, handle_api_errors, require_project
from zad_cli.services import VALID_SERVICES, validate_service

app = typer.Typer(help="Manage services.", no_args_is_help=True)

_SERVICE_HELP = "One of: " + ", ".join(VALID_SERVICES)


@app.command("list")
def list_services() -> None:
    """List available service types that can be added to a project.

    [bold]Example:[/bold]

        $ zad service list
    """
    from rich.console import Console
    from rich.table import Table

    console = Console()
    table = Table(title="Available Services", show_header=True)
    table.add_column("Service", style="bold cyan")

    for service in VALID_SERVICES:
        table.add_row(service)

    console.print(table)


@app.command()
@handle_api_errors
def add(
    ctx: typer.Context,
    service_name: str = typer.Argument(help=_SERVICE_HELP),  # noqa: B008
    components: Annotated[
        list[str] | None,
        typer.Option("--component", "-c", help="Component to add the service to, repeatable"),
    ] = None,
) -> None:
    """Add a service to a project.

    Requires ZAD_API_KEY and ZAD_PROJECT_ID (or --api-key and -p)
    """
    service_name = validate_service(service_name)
    project = require_project(ctx)
    client, formatter = get_helpers(ctx)

    payload: dict = {"service": service_name}
    if components:
        payload["components"] = components

    result = client.add_service(project, payload)
    formatter.render(result)
    formatter.render_success(f"Service '{service_name}' added.")
