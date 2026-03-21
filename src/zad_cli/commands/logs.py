"""Log commands: show, stream."""

from __future__ import annotations

import sys

import typer

app = typer.Typer(help="View logs.", no_args_is_help=True)


def _get_helpers(ctx: typer.Context):
    from zad_cli.cli import _ensure_client

    _ensure_client(ctx)
    return ctx.obj["client"], ctx.obj["formatter"]


@app.command()
def show(
    ctx: typer.Context,
    project: str = typer.Argument(help="Project name"),
    deployment: str = typer.Option(None, "--deployment", "-d", help="Deployment name"),
    container: str = typer.Option(None, "--container", help="Container name"),
    tail: int = typer.Option(None, "--tail", "-n", help="Number of lines to show"),
) -> None:
    """Get logs for a project deployment."""
    client, formatter = _get_helpers(ctx)

    try:
        text = client.get_logs(project, deployment=deployment, container=container, limit=tail)
        formatter.render_text(text)
    except Exception as e:
        formatter.render_error(str(e))
        raise typer.Exit(1) from e


@app.command()
def stream(
    ctx: typer.Context,
    project: str = typer.Argument(help="Project name"),
    deployment: str = typer.Option(None, "--deployment", "-d", help="Deployment name"),
    container: str = typer.Option(None, "--container", help="Container name"),
) -> None:
    """Stream logs in real-time via WebSocket."""
    client, formatter = _get_helpers(ctx)

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
        api_key = client._client.headers.get("X-API-Key", "")
        with ws_client.connect(ws_url, additional_headers={"X-API-Key": api_key}) as ws:
            for message in ws:
                print(message)
    except KeyboardInterrupt:
        print("\nStopped.", file=sys.stderr)
    except ImportError as e:
        formatter.render_error("websockets package required. Install with: uv add websockets")
        raise typer.Exit(1) from e
    except Exception as e:
        formatter.render_error(str(e))
        raise typer.Exit(1) from e
