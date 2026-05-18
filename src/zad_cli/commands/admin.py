"""Admin commands: list, delete."""

from __future__ import annotations

import typer

from zad_cli.helpers import confirm_action, get_helpers, handle_api_errors, render_dry_run

app = typer.Typer(
    help="Admin operations for managing scheduled deletions.\n\nRequires an admin API key.",
    no_args_is_help=True,
)


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
    formatter.render(result)


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
