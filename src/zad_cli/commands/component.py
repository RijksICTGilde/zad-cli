"""Component commands: add, assign."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from zad_cli.api.client import ZadApiError
from zad_cli.helpers import get_helpers, require_project
from zad_cli.services import VALID_SERVICES, validate_service

app = typer.Typer(help="Manage components.", no_args_is_help=True)


@app.command()
def add(
    ctx: typer.Context,
    name: str = typer.Argument(help="Component name"),
    image: str = typer.Option(..., "--image", help="Container image URL"),
    deployment: Annotated[list[str], typer.Option("--deployment", "-d", help="Target deployment, repeatable")] = ...,
    port: int = typer.Option(None, "--port", help="Inbound port"),
    component_type: str = typer.Option("single", "--type", help="Component type"),
    path: str = typer.Option("/", "--path", help="Ingress path"),
    services: Annotated[
        list[str] | None,
        typer.Option("--service", "-s", help="Service, repeatable. Values: " + ", ".join(VALID_SERVICES)),
    ] = None,
    cpu_limit: str = typer.Option(None, "--cpu-limit", help="CPU limit (e.g. 500m)"),
    memory_limit: str = typer.Option(None, "--memory-limit", help="Memory limit (e.g. 512Mi)"),
    env: Annotated[list[str] | None, typer.Option("--env", "-e", help="Env var, repeatable (-e K=V -e K2=V2)")] = None,
    env_file: Annotated[Path | None, typer.Option("--env-file", help="Read env vars from file")] = None,
    aliases: str = typer.Option(None, "--aliases", help="YAML alias definitions"),
    root: bool = typer.Option(False, "--root", help="Root component for nice-url mode"),
) -> None:
    """Add a new component to a project.

    Environment variables can be passed individually or from a file:

      zad component add api --image ... -d prod -e DB_HOST=localhost -e API_KEY=secret
      zad component add api --image ... -d prod --env-file .env.api

    Requires ZAD_API_KEY and ZAD_PROJECT_ID (or --api-key and -p)
    """
    project = require_project(ctx)
    client, formatter = get_helpers(ctx)

    deployment_names = deployment

    # Build env vars string (API expects newline-separated KEY=value)
    env_lines: list[str] = []
    if env_file and env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                env_lines.append(line)
    if env:
        env_lines.extend(env)
    env_vars_str = "\n".join(env_lines) if env_lines else None

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
    if services:
        payload["services"] = [validate_service(s) for s in services]
    if cpu_limit:
        payload["cpu_limit"] = cpu_limit
    if memory_limit:
        payload["memory_limit"] = memory_limit
    if env_vars_str:
        payload["env_vars"] = env_vars_str
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
