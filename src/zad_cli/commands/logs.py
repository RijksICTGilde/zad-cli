"""Logs command: zad logs [-f] [-d deployment] [-n 100]."""

from __future__ import annotations

import sys

import typer

from zad_cli.api.client import ZadApiError
from zad_cli.helpers import get_helpers, require_project


def logs_command(
    ctx: typer.Context,
    follow: bool = typer.Option(False, "--follow", "-f", help="Stream logs in real-time"),
    deployment: str = typer.Option(None, "--deployment", "-d", help="Deployment name"),
    container: str = typer.Option(None, "--container", help="Container name"),
    tail: int = typer.Option(None, "--tail", "-n", help="Number of lines to show"),
) -> None:
    """View logs for a project deployment.

    Requires ZAD_API_KEY and ZAD_PROJECT_ID (or --api-key and -p)
    """
    project = require_project(ctx)
    client, formatter = get_helpers(ctx)

    if follow:
        _stream(client, formatter, project, deployment, container)
    else:
        _show(client, formatter, project, deployment, container, tail)


def _show(client, formatter, project, deployment, container, tail):
    try:
        text = client.get_logs(project, deployment=deployment, container=container, limit=tail)
        formatter.render_text(text)
    except ZadApiError as e:
        formatter.render_error(str(e))
        raise typer.Exit(1) from e


def _stream(client, formatter, project, deployment, container):
    ws_base = client.api_url.replace("https://", "wss://").replace("http://", "ws://")
    ws_base = ws_base.replace("/api", "")
    ws_url = f"{ws_base}/ws/logs/stream/{project}"
    params = []
    if deployment:
        params.append(f"deployment={deployment}")
    if container:
        params.append(f"container={container}")
    if params:
        ws_url += "?" + "&".join(params)

    try:
        import websockets.sync.client as ws_client

        print(f"Streaming logs for {project}... (Ctrl-C to stop)", file=sys.stderr)
        with ws_client.connect(ws_url, additional_headers=client.auth_headers) as ws:
            for message in ws:
                print(message)
    except KeyboardInterrupt:
        print("\nStopped.", file=sys.stderr)
    except ImportError as e:
        formatter.render_error("websockets package required. Install with: uv add websockets")
        raise typer.Exit(1) from e
