"""`zad db schema`: the extra PostgreSQL schemas a project's database carries.

A schema is named by a postfix; the full name becomes ``{project}_{deployment}_{postfix}``
and its connection details reach the pod as ``DATABASE_SCHEMA_{POSTFIX}``.
"""

from __future__ import annotations

import typer

from zad_cli.helpers import (
    confirm_action,
    get_helpers,
    handle_api_errors,
    render_dry_run,
    require_project,
    require_service,
    surface_warnings,
)

SERVICE = "postgresql-database"

app = typer.Typer(
    help="Database extras.\n\nRequires ZAD_API_KEY and ZAD_PROJECT_ID (or --api-key and -p).",
    no_args_is_help=True,
)
schema_app = typer.Typer(help="Manage extra schemas in the project's database.", no_args_is_help=True)
app.add_typer(schema_app, name="schema")


def _base(ctx: typer.Context) -> tuple[str, str]:
    """Project name and the schemas endpoint for it."""
    entry = require_service(ctx, SERVICE)
    project = require_project(ctx)
    return project, f"/v2/projects/{project}/services/{entry.name}/schemas"


@schema_app.command("list")
@handle_api_errors
def list_schemas(ctx: typer.Context) -> None:
    """List the extra schemas configured for this project.

    [bold]Example:[/bold]

        $ zad db schema list
    """
    project, path = _base(ctx)
    client, formatter = get_helpers(ctx)

    result = client.list_database_schemas(project)
    items = result.get("schemas", result) if isinstance(result, dict) else result
    if isinstance(items, list) and all(isinstance(i, dict) for i in items):
        formatter.render(items, columns=["postfix", "description"], title=f"Schemas in {project}")
    else:
        formatter.render_document(result)


@schema_app.command()
@handle_api_errors
def add(
    ctx: typer.Context,
    postfix: str = typer.Argument(help="Short schema name (lowercase letters, digits and underscores)"),
    description: str = typer.Option("", "--description", help="What this schema is for"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be sent without making the API call"),
) -> None:
    """Add an extra schema.

    [bold]Example:[/bold]

        $ zad db schema add reporting --description "Read models for the dashboard"
    """
    project, path = _base(ctx)
    client, formatter = get_helpers(ctx)
    payload = {"postfix": postfix, "description": description}

    if dry_run:
        render_dry_run(formatter, "POST", path, payload)
        return
    confirm_action(f"Add schema '{postfix}' to the database of project '{project}'?", yes, ctx)

    result = client.add_database_schema(project, payload)
    formatter.render(result)
    formatter.render_success(f"Schema '{postfix}' added.")
    surface_warnings(ctx, formatter, result)


@schema_app.command()
@handle_api_errors
def remove(
    ctx: typer.Context,
    postfix: str = typer.Argument(help="Schema to remove"),
    forget: bool = typer.Option(
        False, "--forget", help="Drop it from the project file without cleaning up the database schema"
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be sent without making the API call"),
) -> None:
    """Remove an extra schema.

    [bold]Example:[/bold]

        $ zad db schema remove reporting
    """
    project, path = _base(ctx)
    client, formatter = get_helpers(ctx)

    if dry_run:
        render_dry_run(formatter, "DELETE", f"{path}/{postfix}", {"forget": forget})
        return
    confirm_action(f"Remove schema '{postfix}' from the database of project '{project}'?", yes, ctx)

    result = client.remove_database_schema(project, postfix, forget=forget)
    formatter.render(result)
    formatter.render_success(f"Schema '{postfix}' removed.")
    surface_warnings(ctx, formatter, result)
