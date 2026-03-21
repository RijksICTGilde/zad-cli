"""Invite commands."""

from __future__ import annotations

import sys
import webbrowser

import typer

from zad_cli.helpers import resolve_project

app = typer.Typer(help="Manage invitations.", no_args_is_help=True)


@app.command()
def send(
    ctx: typer.Context,
    project: str = typer.Argument(None, help="Project ID [env: ZAD_PROJECT_ID]"),
) -> None:
    """Open the project page to manage invitations."""
    project = resolve_project(ctx, project)
    settings = ctx.obj["settings"]
    base_url = settings.api_url.replace("/api", "").rstrip("/")
    project_url = f"{base_url}/projects/{project}"

    print(f"Opening project page: {project_url}", file=sys.stderr)
    webbrowser.open(project_url)
