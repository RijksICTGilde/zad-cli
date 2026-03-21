"""Open commands: open project pages in the browser."""

from __future__ import annotations

import sys
import webbrowser

import typer

from zad_cli.helpers import get_helpers, require_project

app = typer.Typer(help="Open web pages in the browser.", no_args_is_help=True)


@app.command()
def project(ctx: typer.Context) -> None:
    """Open the project dashboard in the browser.

    Requires ZAD_API_KEY and ZAD_PROJECT_ID (or --api-key and -p).

    [bold]Example:[/bold]

        $ zad open project
    """
    project_id = require_project(ctx)
    client, _ = get_helpers(ctx)
    url = f"{client.web_url}/projects/{project_id}"

    print(f"Opening: {url}", file=sys.stderr)
    webbrowser.open(url)


@app.command()
def portal(ctx: typer.Context) -> None:
    """Open the self-service portal to create a new project.

    [bold]Example:[/bold]

        $ zad open portal
    """
    client, _ = get_helpers(ctx)
    portal_url = f"{client.web_url}/projects/new"

    print(f"Opening self-service portal: {portal_url}", file=sys.stderr)
    webbrowser.open(portal_url)


@app.command()
def domains(ctx: typer.Context) -> None:
    """Open the project page to manage domain settings.

    Navigate to the deployment you want to configure once the page opens.

    [bold]Example:[/bold]

        $ zad open domains
    """
    project_id = require_project(ctx)
    client, _ = get_helpers(ctx)
    url = f"{client.web_url}/projects/{project_id}"

    print(f"Opening project page: {url}", file=sys.stderr)
    print("Navigate to the deployment you want to change domain settings for.", file=sys.stderr)
    webbrowser.open(url)
