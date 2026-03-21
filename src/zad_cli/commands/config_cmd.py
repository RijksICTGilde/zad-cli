"""Config commands for ~/.config/zad/config.toml."""

from __future__ import annotations

from pathlib import Path

import typer

from zad_cli import config
from zad_cli.settings import DEFAULT_API_URL

app = typer.Typer(help="Manage global configuration.", no_args_is_help=True)


@app.command()
def init() -> None:
    """Interactive setup wizard for zad-cli.

    Creates a .env file in the current directory with your API key and project ID.

    [bold]Example:[/bold]

        $ zad config init
    """
    from rich.console import Console

    console = Console()
    env_path = Path(".env")

    console.print("\n[bold]zad-cli setup[/bold]\n")

    if env_path.exists() and not typer.confirm(f"{env_path} already exists. Overwrite?"):
        raise typer.Abort()

    api_url = typer.prompt("API URL", default=DEFAULT_API_URL)
    api_key = typer.prompt("API key (ZAD_API_KEY)")
    project_id = typer.prompt("Project ID (ZAD_PROJECT_ID)", default="")

    lines = []
    if api_url != DEFAULT_API_URL:
        lines.append(f"ZAD_API_URL={api_url}")
    lines.append(f"ZAD_API_KEY={api_key}")
    if project_id:
        lines.append(f"ZAD_PROJECT_ID={project_id}")

    env_path.write_text("\n".join(lines) + "\n")
    console.print(f"\n[green]Saved to {env_path}[/green]")
    console.print("Run [bold]zad project status[/bold] to verify your setup.")


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
