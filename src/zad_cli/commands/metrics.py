"""Metrics commands: health, overview, cpu, memory, pods, network, query."""

from __future__ import annotations

import typer

from zad_cli.api.client import ZadApiError
from zad_cli.helpers import get_helpers

app = typer.Typer(help="View cluster metrics.", no_args_is_help=True)


@app.command()
def health(ctx: typer.Context) -> None:
    """Check cluster health."""
    client, formatter = get_helpers(ctx)
    try:
        result = client.health()
        formatter.render(result)
    except ZadApiError as e:
        formatter.render_error(str(e))
        raise typer.Exit(1) from e


@app.command()
def overview(ctx: typer.Context) -> None:
    """Show cluster overview (CPU, memory, pods)."""
    client, formatter = get_helpers(ctx)
    try:
        result = client.metrics_overview()
        formatter.render(result)
    except ZadApiError as e:
        formatter.render_error(str(e))
        raise typer.Exit(1) from e


@app.command()
def cpu(
    ctx: typer.Context,
    namespace: str = typer.Option(None, "--namespace", "-n", help="Filter by namespace"),
) -> None:
    """Show CPU usage metrics."""
    client, formatter = get_helpers(ctx)
    try:
        result = client.metrics_cpu(namespace)
        formatter.render(result)
    except ZadApiError as e:
        formatter.render_error(str(e))
        raise typer.Exit(1) from e


@app.command()
def memory(
    ctx: typer.Context,
    namespace: str = typer.Option(None, "--namespace", "-n", help="Filter by namespace"),
) -> None:
    """Show memory usage metrics."""
    client, formatter = get_helpers(ctx)
    try:
        result = client.metrics_memory(namespace)
        formatter.render(result)
    except ZadApiError as e:
        formatter.render_error(str(e))
        raise typer.Exit(1) from e


@app.command()
def pods(
    ctx: typer.Context,
    namespace: str = typer.Option(None, "--namespace", "-n", help="Filter by namespace"),
) -> None:
    """Show pod count and restart metrics."""
    client, formatter = get_helpers(ctx)
    try:
        result = client.metrics_pods(namespace)
        formatter.render(result)
    except ZadApiError as e:
        formatter.render_error(str(e))
        raise typer.Exit(1) from e


@app.command()
def network(
    ctx: typer.Context,
    namespace: str = typer.Option(None, "--namespace", "-n", help="Filter by namespace"),
) -> None:
    """Show network metrics."""
    client, formatter = get_helpers(ctx)
    try:
        result = client.metrics_network(namespace)
        formatter.render(result)
    except ZadApiError as e:
        formatter.render_error(str(e))
        raise typer.Exit(1) from e


@app.command()
def query(
    ctx: typer.Context,
    promql: str = typer.Argument(help="PromQL query expression"),
) -> None:
    """Execute a custom PromQL query."""
    client, formatter = get_helpers(ctx)
    try:
        result = client.metrics_query(promql)
        formatter.render(result)
    except ZadApiError as e:
        formatter.render_error(str(e))
        raise typer.Exit(1) from e
