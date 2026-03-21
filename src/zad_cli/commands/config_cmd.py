"""Config commands for ~/.config/zad/config.toml."""

from __future__ import annotations

import typer

from zad_cli import config

app = typer.Typer(help="Manage global configuration.", no_args_is_help=True)


@app.command("set")
def set_value(
    key: str = typer.Argument(help="Config key (e.g. api_url)"),
    value: str = typer.Argument(help="Config value"),
) -> None:
    """Set a configuration value."""
    path = config.set_value(key, value)
    typer.echo(f"Set {key} = {value} (saved to {path})")


@app.command("get")
def get_value(
    key: str = typer.Argument(help="Config key"),
) -> None:
    """Get a configuration value."""
    val = config.get(key)
    if val:
        typer.echo(val)
    else:
        typer.echo(f"{key} is not set")


@app.command("list")
def list_config() -> None:
    """Show all configuration."""
    data = config.load()
    if not data:
        typer.echo(f"No config file at {config.CONFIG_PATH}")
        return
    for k, v in sorted(data.items()):
        typer.echo(f"{k} = {v}")


@app.command("path")
def show_path() -> None:
    """Show the config file path."""
    typer.echo(config.CONFIG_PATH)
