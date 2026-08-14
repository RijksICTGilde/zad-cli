"""Admin commands: list, delete, orphan-report, orphan-confirm."""

from __future__ import annotations

from typing import Annotated

import typer

from zad_cli.helpers import confirm_action, get_helpers, handle_api_errors, render_dry_run, surface_warnings

app = typer.Typer(
    help="Admin operations for managing scheduled deletions.\n\nRequires an admin API key.",
    no_args_is_help=True,
)

# Valid orphan item types. keycloak_client additionally requires a realm.
ORPHAN_TYPES = ("postgresql_database", "postgresql_user", "minio_bucket", "keycloak_client")
ORPHAN_TYPES_REQUIRING_REALM = ("keycloak_client",)


@app.command("list")
@handle_api_errors
def list_marked(
    ctx: typer.Context,
    project_name: str = typer.Option(None, "--project-name", help="Filter by project name"),
) -> None:
    """List resources marked for scheduled deletion.

    [bold]Example:[/bold]

        $ zadctl admin list
        $ zadctl admin list --project-name my-project
    """
    client, formatter = get_helpers(ctx)

    result = client.list_admin_marked(project_name=project_name)
    marks = result.get("marks", result) if isinstance(result, dict) else result
    formatter.render(marks)


@app.command()
@handle_api_errors
def delete(
    ctx: typer.Context,
    mark_id: str = typer.Argument(help="Mark ID to remove"),  # noqa: B008
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be sent without making the API call"),
) -> None:
    """Remove a deletion mark without purging the resource.

    Cancels the scheduled deletion of a resource. The resource itself
    is NOT deleted; only the mark is removed.

    [bold]Example:[/bold]

        $ zadctl admin delete some-uuid
    """
    client, formatter = get_helpers(ctx)

    if dry_run:
        render_dry_run(formatter, "DELETE", f"/v2/admin/marked-for-deletion/{mark_id}")
        return

    confirm_action(f"Remove deletion mark '{mark_id}'?", yes, ctx)

    result = client.delete_admin_mark(mark_id)
    formatter.render(result)
    formatter.render_success(f"Deletion mark '{mark_id}' removed.")
    surface_warnings(ctx, formatter, result)


@app.command("orphan-report")
@handle_api_errors
def orphan_report(ctx: typer.Context) -> None:
    """Show the orphan sweep report (read-only).

    Inventories PostgreSQL databases, Keycloak realms/clients and MinIO
    buckets, classified against live project files. Performs zero mutations.
    To mark orphans for deletion, use [bold]zadctl admin orphan-confirm[/bold].

    [bold]Example:[/bold]

        $ zadctl admin orphan-report
    """
    client, formatter = get_helpers(ctx)
    result = client.get_orphan_report()
    formatter.render(result)


@app.command("orphan-confirm")
@handle_api_errors
def orphan_confirm(
    ctx: typer.Context,
    items: Annotated[
        list[str] | None,
        typer.Option("--item", help="Item to confirm as TYPE:NAME or TYPE:NAME:REALM, repeatable"),
    ] = None,
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be sent without making the API call"),
) -> None:
    """Mark confirmed orphan candidates for grace-period deletion.

    Each item is specified as TYPE:NAME (or TYPE:NAME:REALM for keycloak_client).
    Valid types: postgresql_database, postgresql_user, minio_bucket, keycloak_client.

    Run [bold]zadctl admin orphan-report[/bold] first to see candidates.

    [bold]Example:[/bold]

        $ zadctl admin orphan-confirm --item postgresql_database:regel_k4c_pr104
        $ zadctl admin orphan-confirm --item minio_bucket:old-bucket --item postgresql_user:stale_user
    """
    client, formatter = get_helpers(ctx)

    if not items:
        formatter.render_error("At least one --item is required.")
        raise typer.Exit(1)

    parsed: list[dict] = []
    for raw in items:
        parts = raw.split(":", 2)
        if len(parts) < 2:
            formatter.render_error(f"Invalid item format '{raw}'. Expected TYPE:NAME or TYPE:NAME:REALM.")
            raise typer.Exit(1)
        item_type, name = parts[0], parts[1]
        if item_type not in ORPHAN_TYPES:
            formatter.render_error(f"Invalid item type '{item_type}'. Valid types: {', '.join(ORPHAN_TYPES)}.")
            raise typer.Exit(1)
        entry: dict = {"type": item_type, "name": name}
        if len(parts) == 3:
            entry["realm"] = parts[2]
        if item_type in ORPHAN_TYPES_REQUIRING_REALM and "realm" not in entry:
            formatter.render_error(f"Item type '{item_type}' requires a realm. Use TYPE:NAME:REALM.")
            raise typer.Exit(1)
        parsed.append(entry)

    payload = {"items": parsed}

    if dry_run:
        render_dry_run(formatter, "POST", "/v2/admin/orphans/confirm", payload)
        return

    confirm_action(f"Mark {len(parsed)} orphan(s) for grace-period deletion?", yes, ctx)

    result = client.confirm_orphans(payload)
    formatter.render(result)
    formatter.render_success(f"Confirmed {len(parsed)} orphan(s) for deletion.")


@app.command()
@handle_api_errors
def cleanup(
    ctx: typer.Context,
    project_name: str = typer.Option(None, "--project-name", help="Only clean up this project's marks"),
    apply: bool = typer.Option(
        False, "--apply", help="Actually purge. Without it the run is a dry run and changes nothing."
    ),
    grace_period_days: int = typer.Option(None, "--grace-period-days", help="Override the grace period"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be sent without making the API call"),
) -> None:
    """Purge resources that are marked for deletion and past their grace period.

    The API defaults to a dry run, and so does this command: nothing is purged until
    --apply is given.

    [bold]Example:[/bold]

        $ zadctl admin cleanup --project-name mijn-project --apply
    """
    client, formatter = get_helpers(ctx)
    params: dict = {"dry_run": not apply}
    if project_name:
        params["project_name"] = project_name
    if grace_period_days is not None:
        params["grace_period_days"] = grace_period_days

    if dry_run:
        render_dry_run(formatter, "POST", "/v2/admin/cleanup/trigger", params)
        return
    if apply:
        confirm_action(f"Purge expired marked resources{f' in {project_name}' if project_name else ''}?", yes, ctx)

    result = client.trigger_cleanup(project_name, dry_run=not apply, grace_period_days=grace_period_days)
    formatter.render_document(result)
    formatter.render_success("Cleanup run finished." if apply else "Dry run finished; nothing was purged.")


@app.command()
@handle_api_errors
def reconcile(
    ctx: typer.Context,
    projects: bool = typer.Option(
        False, "--projects", help="Only pull the projects repo into the store, instead of a full reconciliation"
    ),
    apply: bool = typer.Option(
        False, "--apply", help="Actually reconcile. Without it the run is a dry run and changes nothing."
    ),
    grace_period_days: int = typer.Option(None, "--grace-period-days", help="Override the grace period"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be sent without making the API call"),
) -> None:
    """Reconcile marks against the project files, or re-read the projects repo.

    A full reconciliation unmarks resources that reappeared in a project file, purges what
    is marked and expired, and marks what disappeared. --projects does only the cheap
    part: pull the projects repo now instead of waiting for the poll.

    [bold]Example:[/bold]

        $ zadctl admin reconcile --apply
    """
    client, formatter = get_helpers(ctx)

    if projects:
        if dry_run:
            render_dry_run(formatter, "POST", "/v2/admin/projects/:reconcile")
            return
        result = client.reconcile_projects()
        formatter.render_document(result)
        formatter.render_success("Projects repo re-read.")
        return

    params: dict = {"dry_run": not apply}
    if grace_period_days is not None:
        params["grace_period_days"] = grace_period_days

    if dry_run:
        render_dry_run(formatter, "POST", "/v2/admin/reconciliation/trigger", params)
        return
    result = client.trigger_reconciliation(dry_run=not apply, grace_period_days=grace_period_days)
    formatter.render_document(result)
    formatter.render_success("Reconciliation finished." if apply else "Dry run finished; nothing was changed.")
