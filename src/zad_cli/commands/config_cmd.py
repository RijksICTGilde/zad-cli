"""Config commands: set, get, list, use-context."""

from __future__ import annotations

import typer

from zad_cli.config import context

app = typer.Typer(help="Manage configuration.", no_args_is_help=True)


@app.command("set")
def set_value(
    key: str = typer.Argument(help="Config key"),
    value: str = typer.Argument(help="Config value"),
    ctx_name: str = typer.Option(None, "--context", "-c", help="Context to modify"),
) -> None:
    """Set a configuration value."""
    path = context.set_value(key, value, ctx_name)
    typer.echo(f"Set {key} = {value} (saved to {path})")


@app.command("get")
def get_value(
    key: str = typer.Argument(help="Config key"),
    ctx_name: str = typer.Option(None, "--context", "-c", help="Context to read from"),
) -> None:
    """Get a configuration value."""
    val = context.get_value(key, ctx_name)
    typer.echo(val)


@app.command("list")
def list_config(
    ctx_name: str = typer.Option(None, "--context", "-c", help="Context to show"),
) -> None:
    """Show all configuration for the current context."""
    current = context.get_current_context_name()
    target = ctx_name or current
    ctx = context.get_context(target)

    typer.echo(f"Context: {target}" + (" (active)" if target == current else ""))
    for k, v in sorted(ctx.items()):
        display_val = v
        typer.echo(f"  {k}: {display_val}")


@app.command("use-context")
def use_context(
    name: str = typer.Argument(help="Context name to activate"),
) -> None:
    """Switch to a different configuration context."""
    context.set_context(name)
    typer.echo(f"Switched to context '{name}'.")


@app.command("contexts")
def list_contexts() -> None:
    """List all available contexts."""
    current = context.get_current_context_name()
    for name in context.list_contexts():
        marker = " *" if name == current else ""
        typer.echo(f"  {name}{marker}")
