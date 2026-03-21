"""Service commands: add."""

from __future__ import annotations

from typing import Annotated

import typer

from zad_cli.api.client import ZadApiError
from zad_cli.helpers import get_helpers, require_project
from zad_cli.services import validate_service

app = typer.Typer(help="Manage services.", no_args_is_help=True)


@app.command()
def add(
    ctx: typer.Context,
    service_name: str = typer.Argument(help="Service name (e.g. postgresql-database, keycloak, redis)"),
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

    try:
        result = client.add_service(project, payload)
        formatter.render(result)
        formatter.render_success(f"Service '{service_name}' added.")
    except ZadApiError as e:
        formatter.render_error(str(e))
        raise typer.Exit(1) from e
