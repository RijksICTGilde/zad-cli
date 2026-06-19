"""Admin commands: list, delete, orphan-report, orphan-confirm."""

from __future__ import annotations

from typing import Annotated

import typer

from zad_cli.helpers import confirm_action, get_helpers, handle_api_errors, render_dry_run

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

        $ zad admin list
        $ zad admin list --project-name my-project
    """
    client, formatter = get_helpers(ctx)

    result = client.list_admin_marked(project_name=project_name)
    marks = result.get("marks", result) if isinstance(result, dict) else result
    formatter.render(marks, title="Marked for deletion")


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
    is NOT deleted — only the mark is removed.

    [bold]Example:[/bold]

        $ zad admin delete some-uuid
    """
    client, formatter = get_helpers(ctx)

    if dry_run:
        render_dry_run(formatter, "DELETE", f"/v2/admin/marked-for-deletion/{mark_id}")
        return

    confirm_action(f"Remove deletion mark '{mark_id}'?", yes)

    result = client.delete_admin_mark(mark_id)
    formatter.render(result)
    formatter.render_success(f"Deletion mark '{mark_id}' removed.")


@app.command("orphan-report")
@handle_api_errors
def orphan_report(ctx: typer.Context) -> None:
    """Show the orphan sweep report (read-only).

    Inventories PostgreSQL databases, Keycloak realms/clients and MinIO
    buckets, classified against live project files. Performs zero mutations.
    To mark orphans for deletion, use [bold]zad admin orphan-confirm[/bold].

    [bold]Example:[/bold]

        $ zad admin orphan-report
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

    Run [bold]zad admin orphan-report[/bold] first to see candidates.

    [bold]Example:[/bold]

        $ zad admin orphan-confirm --item postgresql_database:regel_k4c_pr104
        $ zad admin orphan-confirm --item minio_bucket:old-bucket --item postgresql_user:stale_user
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

    confirm_action(f"Mark {len(parsed)} orphan(s) for grace-period deletion?", yes)

    result = client.confirm_orphans(payload)
    formatter.render(result)
    formatter.render_success(f"Confirmed {len(parsed)} orphan(s) for deletion.")
