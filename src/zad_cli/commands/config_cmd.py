"""Config commands for the `.env` in the working directory, the only file this CLI writes."""

from __future__ import annotations

import typer

from zad_cli import config, envfile
from zad_cli.settings import DEFAULT_API_URL

app = typer.Typer(help="Manage the settings in this directory's .env.", no_args_is_help=True)


def _get_formatter(ctx: typer.Context):
    """Get the output formatter from context."""
    return ctx.obj["formatter"]


def _mask_sensitive(key: str, value: str) -> str:
    """Mask values for keys that look sensitive.

    A fixed-width mask, not one star per character: an access token is a couple of
    thousand characters, so masking it one-for-one fills the screen and still tells the
    reader how long the secret is.
    """
    from zad_cli.credentials import redact

    sensitive = ("API_KEY", "SECRET", "PASSWORD", "TOKEN")
    if any(s in key.upper() for s in sensitive) and value:
        return redact(value)
    return value


@app.command()
def init() -> None:
    """Interactive setup wizard for zad-cli.

    Creates or updates a .env file in the current directory with your API key
    and project ID. Existing non-ZAD variables, comments, and blank lines are
    preserved.

    [bold]Example:[/bold]

        $ zad config init
    """
    from rich.console import Console

    console = Console()
    path = envfile.env_path()

    console.print("\n[bold]zad-cli setup[/bold]\n")

    existing = envfile.read()
    if path.exists() and not typer.confirm("Update ZAD settings in existing .env?"):
        raise typer.Abort()

    current_url = existing.get("ZAD_API_URL") or DEFAULT_API_URL
    current_key = existing.get("ZAD_API_KEY") or ""
    current_project = existing.get("ZAD_PROJECT_ID") or ""

    # Masked, so the prompt does not put the key back on screen. Accepting the default
    # keeps the original rather than storing the mask.
    key_display = _mask_sensitive("API_KEY", current_key) if current_key else None

    api_url = typer.prompt("API URL", default=current_url)
    api_key_input = typer.prompt("API key (ZAD_API_KEY)", default=key_display)
    if api_key_input == key_display:
        api_key_input = current_key
    project_id = typer.prompt("Project ID (ZAD_PROJECT_ID, '-' to clear)", default=current_project or "-")
    if project_id == "-":
        project_id = ""

    envfile.write(
        {
            "ZAD_API_KEY": api_key_input,
            # The default needs no line: leaving it out is what makes it follow the
            # default if that ever moves.
            "ZAD_API_URL": api_url if api_url != DEFAULT_API_URL else None,
            "ZAD_PROJECT_ID": project_id or None,
        }
    )

    console.print(f"\n[green]Saved to {path}[/green]")
    console.print("Run [bold]zad project status[/bold] to verify your setup.")
    console.print("\n[dim]Other settings go in the same file via 'zad config set'.[/dim]")


@app.command("set")
def set_value(
    ctx: typer.Context,
    key: str = typer.Argument(help=f"Config key: {', '.join(sorted(config.KNOWN_KEYS))}"),
    value: str = typer.Argument(help="Config value"),
) -> None:
    """Set a configuration value.

    Only the keys the CLI reads are accepted, so a typo fails here instead of sitting in
    the file changing nothing.

    [bold]Example:[/bold]

        $ zad config set rollout false
    """
    from zad_cli.settings import InvalidSettingError

    formatter = _get_formatter(ctx)
    try:
        path = config.set_value(key, value)
    except config.UnknownConfigKeyError as e:
        formatter.render_error(
            str(e),
            details={k: v for k, v in sorted(config.KNOWN_KEYS.items())},
        )
        raise typer.Exit(1) from e
    except InvalidSettingError as e:
        formatter.render_error(str(e))
        raise typer.Exit(1) from e

    stored = config.as_text(config.get(key))
    if formatter.fmt in ("json", "yaml"):
        formatter.render({"key": key, "value": stored, "path": str(path)})
    else:
        formatter.render_success(f"Set {key} = {stored} (saved to {path})")


@app.command("unset")
def unset_value(
    ctx: typer.Context,
    key: str = typer.Argument(help=f"Config key: {', '.join(sorted(config.KNOWN_KEYS))}"),
) -> None:
    """Remove a setting, so the layer below it decides again.

    Overwriting is not the same as removing: `zad config set rollout true` pins the
    default in place, which then stops following it if the default ever moves. This takes
    the line out of the .env instead.

    [bold]Example:[/bold]

        $ zad config unset rollout
    """
    formatter = _get_formatter(ctx)
    try:
        path = config.unset(key)
    except config.UnknownConfigKeyError as e:
        formatter.render_error(str(e), details=dict(sorted(config.KNOWN_KEYS.items())))
        raise typer.Exit(1) from e

    if formatter.fmt in ("json", "yaml"):
        formatter.render({"key": key, "value": None, "path": str(path)})
        return
    formatter.render_success(f"Unset {key} (removed from {path})")
    # What it falls back to is the question you have right after removing it.
    from zad_cli.settings import Settings

    source = Settings.resolve().sources.get(key)
    if source:
        formatter.render_success(f"{key} now comes from: {SOURCE_LABEL.get(source, source)}")


@app.command("get")
def get_value(
    ctx: typer.Context,
    key: str = typer.Argument(help="Config key"),
) -> None:
    """Get a configuration value."""
    # A hand-written `rollout = false` comes back as a TOML boolean; spell it the way
    # `config set` takes it, not the way Python prints it.
    val = config.as_text(config.get(key))
    formatter = _get_formatter(ctx)

    if formatter.fmt in ("json", "yaml"):
        formatter.render({"key": key, "value": val or None})
    elif val:
        print(val)
    else:
        formatter.render_error(f"{key} is not set")


SOURCE_LABEL = {
    "flag": "command-line flag",
    "env": "exported variable",
    "envfile": "this directory's .env",
    "composed": "composed from keycloak_url + keycloak_realm",
    "default": "built-in default",
}


def _effective(ctx: typer.Context) -> list[dict[str, str]]:
    """What each setting is right now, and which layer decided it.

    A `.env` value that is being overruled by an exported variable looks like a bug in the
    CLI unless the table says which one won.
    """
    from zad_cli import credentials

    settings = ctx.obj["settings"]
    sources = settings.sources
    values = {
        "api_url": settings.api_url,
        "project": settings.project_id or "(none)",
        "api_key": credentials.redact(settings.api_key) or "(none)",
        "rollout": "true" if settings.rollout else "false",
        "yes": "true" if settings.assume_yes else "false",
        "output": settings.output_format,
        "table_style": settings.table_style,
        "keycloak_url": settings.keycloak_url,
        "keycloak_realm": settings.keycloak_realm,
        "keycloak_client_id": settings.keycloak_client_id,
        "sso_issuer": settings.sso_issuer,
    }
    return [
        {"setting": name, "value": value, "source": SOURCE_LABEL.get(sources.get(name, "default"), "unknown")}
        for name, value in values.items()
    ]


@app.command("list")
def list_config(ctx: typer.Context) -> None:
    """Show all configuration: what is in effect, and the files it comes from.

    [bold]Example:[/bold]

        $ zad config list
    """
    formatter = _get_formatter(ctx)
    effective = _effective(ctx)
    path = config.path()
    values = envfile.read()

    if formatter.fmt in ("json", "yaml"):
        formatter.render(
            {
                "effective": effective,
                "env_file": {
                    "path": str(path),
                    "values": {k: _mask_sensitive(k, v) for k, v in sorted(values.items())},
                },
            }
        )
        return

    console = formatter.console
    formatter.render(effective, columns=["setting", "value", "source"], title="In effect")

    console.print(f"\n[bold]Settings file[/bold] ({path}):")
    if values:
        for k, v in sorted(values.items()):
            console.print(f"  {k}={_mask_sensitive(k, v)}")
    else:
        console.print("  [dim]No .env in this directory yet[/dim]")

    legacy = envfile.legacy_files()
    if legacy:
        console.print(
            "\n[yellow]Note:[/yellow] settings used to live under ~/.config/zad; these files are no longer read:"
        )
        for old in legacy:
            console.print(f"  {old}")
        console.print("  [dim]Move what you still need into this .env, then delete them.[/dim]")

    ignored = envfile.is_git_ignored()
    if values and ignored is False:
        # It holds an API key and an access token, and it sits in a working tree.
        console.print("\n[yellow]Warning:[/yellow] this .env is not git-ignored, and it holds secrets.")

    console.print()


@app.command("path")
def show_path(ctx: typer.Context) -> None:
    """Show the file settings are written to: the .env in this directory."""
    formatter = _get_formatter(ctx)

    if formatter.fmt in ("json", "yaml"):
        formatter.render({"path": str(config.path())})
    else:
        print(str(config.path()))
