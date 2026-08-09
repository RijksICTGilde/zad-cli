"""`zad login` and `zad logout`: obtain and forget the SSO access token.

The token is only used by the two endpoints that cannot present a project API key —
listing projects and creating one. Everything else keeps using ``X-API-Key``.
"""

from __future__ import annotations

import typer

from zad_cli import auth, credentials
from zad_cli.output.formatter import err_console

app = typer.Typer(help="Log in and out of ZAD with your own account.", no_args_is_help=False)


def _identity(token: str) -> str:
    """Who the token says you are, or "" when it does not say.

    The claims are read, never trusted: nothing is authorised on them, they only make the
    closing line say a name instead of "signed in". A token that is not a JWT is fine.
    """
    import base64
    import json

    parts = token.split(".")
    if len(parts) != 3:
        return ""
    try:
        padded = parts[1] + "=" * (-len(parts[1]) % 4)
        claims = json.loads(base64.urlsafe_b64decode(padded))
    except Exception:  # noqa: BLE001 - an unreadable token is still a usable token
        return ""
    for claim in ("preferred_username", "email", "name", "sub"):
        value = claims.get(claim)
        if isinstance(value, str) and value:
            return value
    return ""


def _next_step(ctx: typer.Context, token: str) -> None:
    """Close the login with who you are and what to do next.

    Ending on "token stored" leaves the reader one undiscoverable step short of a working
    CLI, so this either offers the project picker (in a terminal) or names the command.
    """
    from zad_cli.commands.project import use as project_use
    from zad_cli.picker import is_interactive

    formatter = ctx.obj["formatter"]
    who = _identity(token)
    formatter.render_success(f"Signed in as {who}." if who else "Signed in.")

    active = credentials.get_active_project()
    if active:
        err_console.print(f"[dim]Active project: '{active}'. Next: zad project status[/dim]")
        return

    if formatter.fmt == "table" and is_interactive() and typer.confirm("Pick an active project now?", default=True):
        try:
            project_use(ctx=ctx, name=None, export=False, write_env=None)
            return
        except (typer.Exit, typer.Abort):
            # Picking is the offer, not the login. A login that worked stays a success.
            pass

    err_console.print("[dim]No active project yet. Next: zad project list, then zad project use <name>[/dim]")


def _prompt(url: str, user_code: str) -> None:
    """Show the user what to open, and the code to type when there is one."""
    err_console.print("\n[bold]Open this URL in a browser to sign in:[/bold]")
    err_console.print(f"  {url}\n")
    if user_code:
        err_console.print(f"  Code: [bold]{user_code}[/bold]\n")


def login_command(
    ctx: typer.Context,
    token: str = typer.Option(
        None,
        "--token",
        help="Store a token you already have instead of running a browser flow (also: ZAD_SSO_TOKEN)",
    ),
    device: bool = typer.Option(
        None,
        "--device/--browser",
        help="Force the device flow or the loopback browser flow instead of trying device first",
    ),
) -> None:
    """Sign in and store an SSO access token.

    Needed only for `project list` and `project create`; every other command uses the
    project's API key.

    The device flow is tried first because it needs no local listener, so it works over
    SSH and in a container. Both flows require the platform's OAuth client to allow them:
    if neither is enabled, obtain a token another way and pass it with --token.

    [bold]Example:[/bold]

        $ zad login
    """
    formatter = ctx.obj["formatter"]
    settings = ctx.obj["settings"]

    if token:
        credentials.store_token(token)
        formatter.render_success("Token stored.")
        _next_step(ctx, token)
        return

    issuer = auth.issuer_for(settings.api_url)
    client = auth.client_id()
    err_console.print(f"[dim]Signing in at {issuer} as client {client}[/dim]")

    try:
        endpoints = auth.Endpoints.discover(issuer)
    except auth.LoginError as e:
        formatter.render_error(str(e))
        raise typer.Exit(2) from e

    attempts = []
    if device is not False and endpoints.device:
        attempts.append(("device", lambda: auth.device_login(endpoints, client, on_prompt=_prompt)))
    if device is not True:
        attempts.append(("browser", lambda: auth.loopback_login(endpoints, client, on_prompt=_prompt)))

    problems: list[str] = []
    for name, attempt in attempts:
        try:
            access_token = attempt()
        except auth.LoginError as e:
            problems.append(f"{name}: {e}")
            continue
        credentials.store_token(access_token)
        formatter.render_success("Token stored in ~/.config/zad/credentials.toml.")
        _next_step(ctx, access_token)
        return

    formatter.render_error(
        "Could not sign in.",
        details={
            "attempts": "; ".join(problems),
            "hint": (
                "The OAuth client must have the device grant enabled or a "
                "http://127.0.0.1:<port>/callback redirect URI registered. Until then, pass a "
                "token with --token or set ZAD_SSO_TOKEN."
            ),
        },
    )
    raise typer.Exit(2)


def logout_command(ctx: typer.Context) -> None:
    """Forget the stored token, active project and API keys.

    [bold]Example:[/bold]

        $ zad logout
    """
    formatter = ctx.obj["formatter"]
    path = credentials.clear()
    formatter.render_success(f"Credentials cleared ({path}).")
