"""Resource commands: tune, sanitize."""

from __future__ import annotations

import typer

from zad_cli.helpers import get_helpers, handle_api_errors, render_dry_run, require_project

app = typer.Typer(
    help="Manage resource limits.\n\nRequires ZAD_API_KEY and ZAD_PROJECT_ID (or --api-key and -p).",
    no_args_is_help=True,
)


@app.command()
@handle_api_errors
def tune(
    ctx: typer.Context,
    deployment: str = typer.Argument(None, help="Specific deployment to tune (all if omitted)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be sent without making the API call"),
) -> None:
    """Auto-tune CPU and memory limits from actual usage.

    Queries Prometheus for peak memory usage, detects OOM kills,
    and adjusts resource limits with headroom.

    """
    project = require_project(ctx)
    client, formatter = get_helpers(ctx)

    if dry_run:
        params = {"deployment": deployment} if deployment else {}
        render_dry_run(formatter, "POST", f"/resources/{project}/tune", params)
        return

    result = client.tune_resources(project, deployment)
    formatter.render(result)


@app.command()
@handle_api_errors
def sanitize(
    ctx: typer.Context,
    deployment: str = typer.Argument(None, help="Specific deployment to sanitize (all if omitted)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be sent without making the API call"),
) -> None:
    """Detect and disable broken deployments.

    Checks for crash loops, missing images, and OOM kills.
    Sets broken components to replicas=0.

    """
    project = require_project(ctx)
    client, formatter = get_helpers(ctx)

    if dry_run:
        params = {"deployment": deployment} if deployment else {}
        render_dry_run(formatter, "POST", f"/resources/{project}/sanitize", params)
        return

    result = client.sanitize(project, deployment)
    formatter.render(result)
