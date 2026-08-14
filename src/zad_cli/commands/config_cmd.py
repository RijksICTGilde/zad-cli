"""Config commands for the `.env.zadctl` in the working directory, the only file this CLI writes."""

from __future__ import annotations

import typer

from zad_cli import config, envfile
from zad_cli.settings import DEFAULT_API_URL

app = typer.Typer(help="Manage the settings in this directory's .env.zadctl.", no_args_is_help=True)


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

    Creates or updates a .env.zadctl in the current directory with your API key
    and project ID. Existing non-ZAD variables, comments, and blank lines are
    preserved.

    [bold]Example:[/bold]

        $ zadctl config init
    """
    from rich.console import Console

    console = Console()
    path = envfile.env_path()

    console.print("\n[bold]zad-cli setup[/bold]\n")

    existing = envfile.read()
    if path.exists() and not typer.confirm(f"Update ZAD settings in existing {path.name}?"):
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
    console.print("Run [bold]zadctl project status[/bold] to verify your setup.")
    console.print("\n[dim]Other settings go in the same file via 'zadctl config set'.[/dim]")


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

        $ zadctl config set rollout false
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

    Overwriting is not the same as removing: `zadctl config set rollout true` pins the
    default in place, which then stops following it if the default ever moves. This takes
    the line out of the file instead.

    [bold]Example:[/bold]

        $ zadctl config unset rollout
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
        formatter.render_success(f"{key} now comes from: {source_label(source)}")


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
    "composed": "composed from keycloak_url + keycloak_realm",
    "default": "built-in default",
}


def source_label(source: str) -> str:
    """What decided a setting, in words.

    The file layer names the file this directory actually uses: `.env.zadctl`, or the `.env`
    that was already carrying ZAD_ variables. "this directory's env file" would be true and
    useless -- the reader is about to go edit it.
    """
    if source == "envfile":
        return f"this directory's {envfile.env_path().name}"
    return SOURCE_LABEL.get(source, source)


def _token_state() -> str:
    """Whether the stored SSO token is still usable, and until when.

    `config list` is where you check that you are set up right, and the one credential that
    decides whether `project list` and `project create` work at all was the one it did not
    mention. Two independent practice runs lost their first minutes to a token that had
    expired overnight: every setting looked fine and the first real call answered 401.

    The `exp` claim is in the token itself, so this costs no call and no network.
    """
    import time

    from zad_cli import auth, credentials

    token = credentials.get_token()
    if not token:
        return "(none) - run `zadctl login`"
    exp = auth.expires_at(token)
    if not exp:
        return "(set) - no expiry in the token"
    left = exp - int(time.time())
    when = time.strftime("%H:%M", time.localtime(exp))
    if left <= 0:
        return f"EXPIRED at {when} - run `zadctl login`"
    if left < 300:
        return f"valid until {when} (under 5 min left)"
    return f"valid until {when} ({left // 60} min left)"


def _effective(ctx: typer.Context) -> list[dict[str, str]]:
    """What each setting is right now, and which layer decided it.

    A remembered value that is being overruled by an exported variable looks like a bug in the
    CLI unless the table says which one won.
    """
    from zad_cli import credentials

    settings = ctx.obj["settings"]
    sources = settings.sources
    values = {
        "api_url": settings.api_url,
        "project": settings.project_id or "(none)",
        "api_key": credentials.redact(settings.api_key) or "(none)",
        "sso_token": _token_state(),
        "rollout": "true" if settings.rollout else "false",
        "yes": "true" if settings.assume_yes else "false",
        "output": settings.output_format,
        "table_style": settings.table_style,
        "keycloak_url": settings.keycloak_url,
        "keycloak_realm": settings.keycloak_realm,
        "keycloak_client_id": settings.keycloak_client_id,
        "sso_issuer": settings.sso_issuer,
    }
    # The token is read here rather than by Settings, so its layer is worked out the same
    # way: exported variable first, then the file. Reporting it as "built-in default" would
    # send someone looking for a setting that does not exist.
    sources = {**sources, "sso_token": _token_source()}
    return [
        {"setting": name, "value": value, "source": source_label(sources.get(name, "default"))}
        for name, value in values.items()
    ]


def _token_source() -> str:
    import os

    if os.environ.get("ZAD_SSO_TOKEN"):
        return "env"
    if envfile.get("ZAD_SSO_TOKEN"):
        return "envfile"
    return "default"


@app.command("list")
def list_config(ctx: typer.Context) -> None:
    """Show all configuration: what is in effect, and the files it comes from.

    [bold]Example:[/bold]

        $ zadctl config list
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
        console.print(f"  [dim]No {path.name} in this directory yet[/dim]")

    legacy = envfile.legacy_files()
    if legacy:
        console.print(
            "\n[yellow]Note:[/yellow] settings used to live under ~/.config/zad; these files are no longer read:"
        )
        for old in legacy:
            console.print(f"  {old}")
        console.print(f"  [dim]Move what you still need into {path.name}, then delete them.[/dim]")

    ignored = envfile.is_git_ignored()
    if values and ignored is False:
        # It holds an API key and an access token, and it sits in a working tree.
        console.print(f"\n[yellow]Warning:[/yellow] {path.name} is not git-ignored, and it holds secrets.")

    console.print()


@app.command("path")
def show_path(ctx: typer.Context) -> None:
    """Show the file settings are written to: the env file in this directory."""
    formatter = _get_formatter(ctx)

    if formatter.fmt in ("json", "yaml"):
        formatter.render({"path": str(config.path())})
    else:
        print(str(config.path()))
