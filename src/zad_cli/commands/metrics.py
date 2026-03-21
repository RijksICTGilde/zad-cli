"""Metrics commands: health, overview, cpu, memory, pods, network, query."""

from __future__ import annotations

import typer

app = typer.Typer(help="View cluster metrics.", no_args_is_help=True)


def _get_helpers(ctx: typer.Context):
    from zad_cli.cli import _ensure_client

    _ensure_client(ctx)
    return ctx.obj["client"], ctx.obj["formatter"]


@app.command()
def health(ctx: typer.Context) -> None:
    """Check cluster health."""
    client, formatter = _get_helpers(ctx)
    try:
        result = client.health()
        formatter.render(result)
    except Exception as e:
        formatter.render_error(str(e))
        raise typer.Exit(1) from e


@app.command()
def overview(ctx: typer.Context) -> None:
    """Show cluster overview (CPU, memory, pods)."""
    client, formatter = _get_helpers(ctx)
    try:
        result = client.metrics_overview()
        formatter.render(result)
    except Exception as e:
        formatter.render_error(str(e))
        raise typer.Exit(1) from e


@app.command()
def cpu(
    ctx: typer.Context,
    namespace: str = typer.Option(None, "--namespace", "-n", help="Filter by namespace"),
) -> None:
    """Show CPU usage metrics."""
    client, formatter = _get_helpers(ctx)
    try:
        result = client.metrics_cpu(namespace)
        formatter.render(result)
    except Exception as e:
        formatter.render_error(str(e))
        raise typer.Exit(1) from e


@app.command()
def memory(
    ctx: typer.Context,
    namespace: str = typer.Option(None, "--namespace", "-n", help="Filter by namespace"),
) -> None:
    """Show memory usage metrics."""
    client, formatter = _get_helpers(ctx)
    try:
        result = client.metrics_memory(namespace)
        formatter.render(result)
    except Exception as e:
        formatter.render_error(str(e))
        raise typer.Exit(1) from e


@app.command()
def pods(
    ctx: typer.Context,
    namespace: str = typer.Option(None, "--namespace", "-n", help="Filter by namespace"),
) -> None:
    """Show pod count and restart metrics."""
    client, formatter = _get_helpers(ctx)
    try:
        result = client.metrics_pods(namespace)
        formatter.render(result)
    except Exception as e:
        formatter.render_error(str(e))
        raise typer.Exit(1) from e


@app.command()
def network(
    ctx: typer.Context,
    namespace: str = typer.Option(None, "--namespace", "-n", help="Filter by namespace"),
) -> None:
    """Show network metrics."""
    client, formatter = _get_helpers(ctx)
    try:
        result = client.metrics_network(namespace)
        formatter.render(result)
    except Exception as e:
        formatter.render_error(str(e))
        raise typer.Exit(1) from e


@app.command()
def query(
    ctx: typer.Context,
    promql: str = typer.Argument(help="PromQL query expression"),
) -> None:
    """Execute a custom PromQL query."""
    client, formatter = _get_helpers(ctx)
    try:
        result = client.metrics_query(promql)
        formatter.render(result)
    except Exception as e:
        formatter.render_error(str(e))
        raise typer.Exit(1) from e
