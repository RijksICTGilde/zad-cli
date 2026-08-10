"""Component commands: list, add, assign, delete."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from zad_cli.helpers import (
    complete_component,
    confirm_action,
    get_helpers,
    handle_api_errors,
    render_dry_run,
    require_project,
    require_service,
    surface_warnings,
)

app = typer.Typer(
    help="Manage components.\n\nRequires ZAD_API_KEY and ZAD_PROJECT_ID (or --api-key and -p).",
    no_args_is_help=True,
)


@app.command("list")
@handle_api_errors
def list_components(
    ctx: typer.Context,
    deployment: str = typer.Option(None, "--deployment", "-d", help="Filter by deployment"),
) -> None:
    """List all components in a project.

    [bold]Examples:[/bold]

        $ zad component list

        $ zad component list -d regelrecht
    """
    project = require_project(ctx)
    client, formatter = get_helpers(ctx)

    deployments = client.list_deployments(project)

    rows = []
    for dep in deployments:
        if deployment and dep["deployment"] != deployment:
            continue
        for comp in dep["components"]:
            rows.append(
                {
                    "component": comp,
                    "deployment": dep["deployment"],
                    "namespace": dep["namespace"],
                }
            )

    formatter.render(rows, columns=["component", "deployment", "namespace"], title="Components")


@app.command()
@handle_api_errors
def add(
    ctx: typer.Context,
    name: str = typer.Argument(help="Component name"),
    image: str = typer.Option(None, "--image", help="Container image URL. Required as soon as --deployment is given"),
    deployment: Annotated[
        list[str] | None,
        typer.Option("--deployment", help="Deployment to attach to, repeatable. Omit to only define the component"),
    ] = None,
    port: int = typer.Option(None, "--port", help="Single inbound port (use --ports for multiple)"),
    ports: Annotated[
        list[int] | None,
        typer.Option("--ports", help="Inbound ports, repeatable (takes precedence over --port)"),
    ] = None,
    component_type: str = typer.Option("single", "--type", help="Component type"),
    path: str = typer.Option("/", "--path", help="Ingress path"),
    services: Annotated[
        list[str] | None,
        typer.Option("--service", help="Service, repeatable. See `zad service list` for the valid names."),
    ] = None,
    cpu_limit: str = typer.Option(None, "--cpu-limit", help="CPU limit (e.g. 500m)"),
    memory_limit: str = typer.Option(None, "--memory-limit", help="Memory limit (e.g. 512Mi)"),
    env: Annotated[list[str] | None, typer.Option("--env", "-e", help="Env var, repeatable (-e K=V -e K2=V2)")] = None,
    env_file: Annotated[Path | None, typer.Option("--env-file", help="Read env vars from file")] = None,
    aliases: str = typer.Option(None, "--aliases", help="YAML alias definitions"),
    root: bool = typer.Option(False, "--root", help="Root component for nice-url mode"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be sent without making the API call"),
) -> None:
    """Add a new component to a project.

    Without --deployment this only defines the component; nothing runs it yet, which is a
    valid state. Attach it later with `zad component assign`. The image lives on the
    attachment, not on the definition, so it is only needed once you attach.

    [bold]Examples:[/bold]

        $ zad component add web --image ghcr.io/org/app:latest --deployment production

        $ zad component add worker

        $ zad component add api --image ghcr.io/org/api:v2 --deployment prod -e DB_HOST=db -e API_KEY=secret

        $ zad component add api --image ghcr.io/org/api:v2 --deployment prod --env-file .env.api

        $ zad component add web --image ghcr.io/org/app:latest --deployment staging --service postgresql-database
    """
    project = require_project(ctx)
    client, formatter = get_helpers(ctx)

    # The API accepts 'port' or 'ports', not both. Sending both leaves it to the
    # server which one wins, so reject it here where the message can be clear.
    if port is not None and ports:
        raise typer.BadParameter("Use either --port or --ports, not both.")

    deployment_names = deployment or []
    # The image is stored on the attachment, so it is required exactly when there is one.
    # The API answers 422 here; saying it locally names the flag instead of the field.
    if deployment_names and not image:
        raise typer.BadParameter("--image is required when --deployment is given: the image lives on the attachment.")
    if image and not deployment_names:
        raise typer.BadParameter(
            "--image without --deployment has nowhere to go: a component definition carries no image. "
            "Attach it with --deployment, or leave --image out."
        )

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
        "path": path,
        "root": root,
    }
    # Left out rather than sent empty: an absent image means "this definition has none",
    # which is not the same statement as image: null.
    if image:
        payload["image"] = image
    if deployment_names:
        payload["deployment_names"] = deployment_names
    if port is not None:
        payload["port"] = port
    if ports is not None:
        payload["ports"] = ports
    if services:
        payload["services"] = [require_service(ctx, s).name for s in services]
    if cpu_limit:
        payload["cpu_limit"] = cpu_limit
    if memory_limit:
        payload["memory_limit"] = memory_limit
    if env_vars_str:
        payload["env_vars"] = env_vars_str
    if aliases:
        payload["aliases"] = aliases

    if dry_run:
        render_dry_run(formatter, "POST", f"/v2/projects/{project}/components", payload)
        return

    result = client.add_component(project, payload)
    formatter.render(result)
    formatter.render_success(f"Component '{name}' added.")


@app.command()
@handle_api_errors
def assign(
    ctx: typer.Context,
    component_name: str = typer.Argument(help="Existing component name"),
    deployment: str = typer.Argument(help="Deployment to add it to"),
    image: str = typer.Option(..., "--image", help="Container image URL for this deployment"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be sent without making the API call"),
) -> None:
    """Assign an existing component to a deployment."""
    project = require_project(ctx)
    client, formatter = get_helpers(ctx)

    payload = {"component_name": component_name, "image": image}

    if dry_run:
        render_dry_run(formatter, "POST", f"/v2/projects/{project}/deployments/{deployment}/components", payload)
        return

    result = client.add_component_to_deployment(project, deployment, payload)
    formatter.render(result)
    formatter.render_success(f"Component '{component_name}' assigned to deployment '{deployment}'.")


@app.command()
@handle_api_errors
def update(
    ctx: typer.Context,
    name: str = typer.Argument(help="Component name", autocompletion=complete_component),
    image: str = typer.Option(None, "--image", help="New container image URL"),
    port: int = typer.Option(None, "--port", help="Single inbound port"),
    ports: Annotated[
        list[int] | None,
        typer.Option("--ports", help="Inbound ports, repeatable (replaces existing ports)"),
    ] = None,
    clear_ports: bool = typer.Option(False, "--clear-ports", help="Remove all inbound ports"),
    path: str = typer.Option(None, "--path", help="Ingress path"),
    services: Annotated[
        list[str] | None,
        typer.Option(
            "--service",
            help="Service, repeatable (replaces existing list). See `zad service list` for the valid names.",
        ),
    ] = None,
    cpu_limit: str = typer.Option(None, "--cpu-limit", help="CPU limit (e.g. 500m)"),
    memory_limit: str = typer.Option(None, "--memory-limit", help="Memory limit (e.g. 512Mi)"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be sent without making the API call"),
) -> None:
    """Update fields of an existing component (partial update).

    Only the fields you specify change; all others remain as-is.

    [bold]Examples:[/bold]

        $ zad component update web --image ghcr.io/org/app:v2

        $ zad component update api --port 8080 --cpu-limit 500m

        $ zad component update web --clear-ports
    """
    project = require_project(ctx)
    client, formatter = get_helpers(ctx)

    # The API clears ports with an empty array; every listed port must be >= 1,
    # so there is no in-band sentinel value to express "none" via --ports.
    if clear_ports and (port is not None or ports):
        raise typer.BadParameter("--clear-ports cannot be combined with --port or --ports.")
    if port is not None and ports:
        raise typer.BadParameter("Use either --port or --ports, not both.")

    payload: dict = {}
    if image is not None:
        payload["image"] = image
    if port is not None:
        payload["port"] = port
    if clear_ports:
        payload["ports"] = []
    elif ports:
        payload["ports"] = ports
    if path is not None:
        payload["path"] = path
    if services is not None:
        payload["services"] = [require_service(ctx, s).name for s in services]
    if cpu_limit is not None:
        payload["cpu_limit"] = cpu_limit
    if memory_limit is not None:
        payload["memory_limit"] = memory_limit

    if not payload:
        raise typer.BadParameter("Provide at least one field to update.")

    if dry_run:
        render_dry_run(formatter, "PATCH", f"/v2/projects/{project}/components/{name}", payload)
        return

    confirm_action(f"Update component '{name}' in project '{project}'?", yes)

    result = client.update_component(project, name, payload)
    formatter.render(result)
    formatter.render_success(f"Component '{name}' updated.")
    surface_warnings(ctx, formatter, result)


@app.command()
@handle_api_errors
def delete(
    ctx: typer.Context,
    name: str = typer.Argument(help="Component name", autocompletion=complete_component),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be sent without making the API call"),
) -> None:
    """Delete a component from a project.

    [bold]Example:[/bold]

        $ zad component delete web
    """
    project = require_project(ctx)
    client, formatter = get_helpers(ctx)

    if dry_run:
        render_dry_run(formatter, "DELETE", f"/v2/projects/{project}/components/{name}")
        return

    confirm_action(f"Delete component '{name}' from project '{project}'?", yes)

    result = client.delete_component(project, name)
    formatter.render(result)
    formatter.render_success(f"Component '{name}' deleted.")
