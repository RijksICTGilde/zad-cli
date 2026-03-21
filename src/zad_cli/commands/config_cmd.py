"""Config commands for ~/.config/zad/config.toml and .env."""

from __future__ import annotations

from pathlib import Path

import typer

from zad_cli import config
from zad_cli.settings import DEFAULT_API_URL

app = typer.Typer(help="Manage global configuration.", no_args_is_help=True)


def _get_formatter(ctx: typer.Context):
    """Get the output formatter from context."""
    return ctx.obj["formatter"]


def _mask_sensitive(key: str, value: str) -> str:
    """Mask values for keys that look sensitive."""
    sensitive = ("API_KEY", "SECRET", "PASSWORD", "TOKEN")
    if any(s in key.upper() for s in sensitive) and len(value) > 4:
        return value[:4] + "*" * (len(value) - 4)
    return value


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
    console.print(
        f"\n[dim]Global settings (like api_url) can also be set in {config.CONFIG_PATH} via 'zad config set'.[/dim]"
    )


@app.command("set")
def set_value(
    ctx: typer.Context,
    key: str = typer.Argument(help="Config key (e.g. api_url)"),
    value: str = typer.Argument(help="Config value"),
) -> None:
    """Set a configuration value."""
    path = config.set_value(key, value)
    formatter = _get_formatter(ctx)

    if formatter.fmt in ("json", "yaml"):
        formatter.render({"key": key, "value": value, "path": str(path)})
    else:
        formatter.render_success(f"Set {key} = {value} (saved to {path})")


@app.command("get")
def get_value(
    ctx: typer.Context,
    key: str = typer.Argument(help="Config key"),
) -> None:
    """Get a configuration value."""
    val = config.get(key)
    formatter = _get_formatter(ctx)

    if formatter.fmt in ("json", "yaml"):
        formatter.render({"key": key, "value": val or None})
    elif val:
        print(val)
    else:
        formatter.render_error(f"{key} is not set")


@app.command("list")
def list_config(ctx: typer.Context) -> None:
    """Show all configuration (global TOML and project .env)."""
    formatter = _get_formatter(ctx)
    env_path = Path(".env")

    # Collect all config into structured data
    global_config = config.load()
    env_config: dict[str, str] = {}
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env_config[k] = v

    if formatter.fmt in ("json", "yaml"):
        formatter.render(
            {
                "global_config": {"path": str(config.CONFIG_PATH), "values": global_config},
                "project_config": {"path": str(env_path.resolve()), "values": env_config},
            }
        )
        return

    # Table mode: human-friendly display with masking
    console = formatter.console

    console.print(f"\n[bold]Global config[/bold] ({config.CONFIG_PATH}):")
    if global_config:
        for k, v in sorted(global_config.items()):
            console.print(f"  {k} = {v}")
    else:
        console.print("  [dim]No config file found[/dim]")

    console.print(f"\n[bold]Project config[/bold] ({env_path.resolve()}):")
    if env_config:
        for k, v in sorted(env_config.items()):
            console.print(f"  {k} = {_mask_sensitive(k, v)}")
    else:
        console.print("  [dim]No .env file in current directory[/dim]")

    console.print()


@app.command("path")
def show_path(ctx: typer.Context) -> None:
    """Show the config file path."""
    formatter = _get_formatter(ctx)

    if formatter.fmt in ("json", "yaml"):
        formatter.render({"path": str(config.CONFIG_PATH)})
    else:
        print(str(config.CONFIG_PATH))
