"""Metrics commands: health, overview, cpu, memory, pods, network, query."""

from __future__ import annotations

import typer

from zad_cli.helpers import get_helpers, handle_api_errors

app = typer.Typer(help="View cluster metrics.", no_args_is_help=True)


@app.command()
@handle_api_errors
def health(ctx: typer.Context) -> None:
    """Check cluster health."""
    client, formatter = get_helpers(ctx)

    result = client.health()
    formatter.render(result)


@app.command()
@handle_api_errors
def overview(ctx: typer.Context) -> None:
    """Show cluster overview (CPU, memory, pods)."""
    client, formatter = get_helpers(ctx)

    result = client.metrics_overview()
    formatter.render(result)


@app.command()
@handle_api_errors
def cpu(
    ctx: typer.Context,
    namespace: str = typer.Option(None, "--namespace", help="Filter by Kubernetes namespace"),
) -> None:
    """Show CPU usage metrics."""
    client, formatter = get_helpers(ctx)

    result = client.metrics_cpu(namespace)
    formatter.render(result)


@app.command()
@handle_api_errors
def memory(
    ctx: typer.Context,
    namespace: str = typer.Option(None, "--namespace", help="Filter by Kubernetes namespace"),
) -> None:
    """Show memory usage metrics."""
    client, formatter = get_helpers(ctx)

    result = client.metrics_memory(namespace)
    formatter.render(result)


@app.command()
@handle_api_errors
def pods(
    ctx: typer.Context,
    namespace: str = typer.Option(None, "--namespace", help="Filter by Kubernetes namespace"),
) -> None:
    """Show pod count and restart metrics."""
    client, formatter = get_helpers(ctx)

    result = client.metrics_pods(namespace)
    formatter.render(result)


@app.command()
@handle_api_errors
def network(
    ctx: typer.Context,
    namespace: str = typer.Option(None, "--namespace", help="Filter by Kubernetes namespace"),
) -> None:
    """Show network metrics."""
    client, formatter = get_helpers(ctx)

    result = client.metrics_network(namespace)
    formatter.render(result)


@app.command()
@handle_api_errors
def query(
    ctx: typer.Context,
    promql: str = typer.Argument(help="PromQL query expression"),
) -> None:
    """Execute a custom PromQL query."""
    client, formatter = get_helpers(ctx)

    result = client.metrics_query(promql)
    formatter.render(result)
