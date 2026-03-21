"""Component commands: add, assign."""

from __future__ import annotations

import typer

from zad_cli.api.client import ZadApiError
from zad_cli.helpers import get_helpers, require_project

app = typer.Typer(help="Manage components.", no_args_is_help=True)


@app.command()
def add(
    ctx: typer.Context,
    name: str = typer.Argument(help="Component name"),
    image: str = typer.Option(..., "--image", help="Container image URL"),
    deployment: str = typer.Option(..., "--deployment", "-d", help="Comma-separated deployment names"),
    port: int = typer.Option(None, "--port", help="Inbound port"),
    component_type: str = typer.Option("single", "--type", help="Component type"),
    path: str = typer.Option("/", "--path", help="Ingress path"),
    services: str = typer.Option(
        None, "--services", help="Comma-separated services (e.g. postgresql-database,keycloak)"
    ),
    cpu_limit: str = typer.Option(None, "--cpu-limit", help="CPU limit (e.g. 500m)"),
    memory_limit: str = typer.Option(None, "--memory-limit", help="Memory limit (e.g. 512Mi)"),
    env_vars: str = typer.Option(
        None, "--env-vars", envvar="SOURCE_ENV_VARS", help="KEY=value pairs, newline-separated"
    ),
    aliases: str = typer.Option(None, "--aliases", help="YAML alias definitions"),
    root: bool = typer.Option(False, "--root", help="Root component for nice-url mode"),
) -> None:
    """Add a new component to a project.

    Requires ZAD_API_KEY and ZAD_PROJECT_ID (or --api-key and -p)
    """
    project = require_project(ctx)
    client, formatter = get_helpers(ctx)

    deployment_names = [d.strip() for d in deployment.split(",") if d.strip()]
    service_list = [s.strip() for s in services.split(",") if s.strip()] if services else None

    payload: dict = {
        "name": name,
        "type": component_type,
        "image": image,
        "deployment_names": deployment_names,
        "path": path,
        "root": root,
    }
    if port is not None:
        payload["port"] = port
    if service_list:
        payload["services"] = service_list
    if cpu_limit:
        payload["cpu_limit"] = cpu_limit
    if memory_limit:
        payload["memory_limit"] = memory_limit
    if env_vars:
        payload["env_vars"] = env_vars
    if aliases:
        payload["aliases"] = aliases

    try:
        result = client.add_component(project, payload)
        formatter.render(result)
        formatter.render_success(f"Component '{name}' added.")
    except ZadApiError as e:
        formatter.render_error(str(e))
        raise typer.Exit(1) from e


@app.command()
def assign(
    ctx: typer.Context,
    component_name: str = typer.Argument(help="Existing component name"),
    deployment: str = typer.Argument(help="Deployment to add it to"),
    image: str = typer.Option(..., "--image", help="Container image URL for this deployment"),
) -> None:
    """Assign an existing component to a deployment.

    Requires ZAD_API_KEY and ZAD_PROJECT_ID (or --api-key and -p)
    """
    project = require_project(ctx)
    client, formatter = get_helpers(ctx)

    payload = {"component_name": component_name, "image": image}

    try:
        result = client.add_component_to_deployment(project, deployment, payload)
        formatter.render(result)
        formatter.render_success(f"Component '{component_name}' assigned to deployment '{deployment}'.")
    except ZadApiError as e:
        formatter.render_error(str(e))
        raise typer.Exit(1) from e
