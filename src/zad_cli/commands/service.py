"""Service commands: add, list."""

from __future__ import annotations

from enum import StrEnum

import typer

from zad_cli.api.client import ZadApiError
from zad_cli.helpers import get_helpers, require_project


class ServiceName(StrEnum):
    """Available ZAD services."""

    publish_on_web = "publish-on-web"
    keycloak = "keycloak"
    authorization_wall = "authorization-wall"
    metrics_scraper = "metrics-scraper"
    persistent_storage = "persistent-storage"
    temp_storage = "temp-storage"
    postgresql_database = "postgresql-database"
    namespace_postgresql_database = "namespace-postgresql-database"
    minio_storage = "minio-storage"
    redis = "redis"
    namespace_redis = "namespace-redis"


app = typer.Typer(help="Manage services.", no_args_is_help=True)


@app.command()
def add(
    ctx: typer.Context,
    service_name: ServiceName = typer.Argument(help="Service to add"),  # noqa: B008
    components: str = typer.Option(
        None, "--components", help="Comma-separated component names to also add the service to"
    ),
) -> None:
    """Add a service to a project.

    Requires ZAD_API_KEY and ZAD_PROJECT_ID (or --api-key and -p)
    """
    project = require_project(ctx)
    client, formatter = get_helpers(ctx)

    component_list = [c.strip() for c in components.split(",") if c.strip()] if components else None

    payload: dict = {"service": service_name.value}
    if component_list:
        payload["components"] = component_list

    try:
        result = client.add_service(project, payload)
        formatter.render(result)
        formatter.render_success(f"Service '{service_name.value}' added.")
    except ZadApiError as e:
        formatter.render_error(str(e))
        raise typer.Exit(1) from e
