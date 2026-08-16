"""`zadctl login` and `zadctl logout`: obtain and forget the SSO access token.

The token is only used by the two endpoints that cannot present a project API key:
listing projects and creating one. Everything else keeps using ``X-API-Key``.
"""

from __future__ import annotations

import sys
import webbrowser
from collections.abc import Callable

import typer

from zad_cli import auth, credentials, envfile
from zad_cli.auth import REQUIRED_AUDIENCE
from zad_cli.output.formatter import err_console

app = typer.Typer(help="Log in and out of ZAD with your own account.", no_args_is_help=False)


def _identity(token: str) -> str:
    """Who the token says you are, or "" when it does not say.

    The claims are read, never trusted: nothing is authorised on them, they only make the
    closing line say a name instead of "signed in". A token that is not a JWT is fine.
    """
    from rich.markup import escape

    claims = auth.token_claims(token)
    for claim in ("preferred_username", "email", "name", "sub"):
        value = claims.get(claim)
        if isinstance(value, str) and value:
            # A claim is server-supplied text on its way into a Rich console; square
            # brackets in it are content, not markup.
            return escape(value)
    return ""


def _note_lifetime(token: str) -> None:
    """Say how long a fresh token lives, right after it arrived.

    The platform's access token lives about five minutes, which reads as a bug when
    `config list` shows "(under 5 min left)" seconds after logging in. It renews silently
    from the refresh token, so this is said once, here, including the part that keeps it
    from being alarming.
    """
    import time

    left = auth.expires_at(token) - int(time.time())
    if 0 < left < 300:
        err_console.print(
            f"[dim]This token lives about {max(1, left // 60)} minute(s) -- short is normal here; "
            f"later commands renew it silently from the refresh token while that lasts.[/dim]"
        )


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
        err_console.print(f"[dim]Active project: '{active}'. Next: zadctl project status[/dim]")
        return

    if formatter.fmt == "table" and is_interactive() and typer.confirm("Pick an active project now?", default=True):
        try:
            project_use(ctx=ctx, name=None, export=False, write_env=None)
            return
        except (typer.Exit, typer.Abort):
            # Picking is the offer, not the login. A login that worked stays a success.
            pass

    err_console.print("[dim]No active project yet. Next: zadctl project list, then zadctl project use <name>[/dim]")


def _make_prompt(open_browser: bool) -> Callable[[str, str], None]:
    """Show the sign-in URL, and open it unless asked not to.

    The URL is printed *before* the browser is launched, and stays on screen either way:
    a browser that opens the wrong profile is as common as one that does not open at all,
    and in both cases the answer is the same line to copy.
    """

    def prompt(url: str, user_code: str) -> None:
        err_console.print("\n[bold]Open this URL in a browser to sign in:[/bold]")
        # `soft_wrap`, because this is the one line here that has to survive being copied.
        # Rich folds to the terminal width by default, and an authorization URL is longer
        # than any terminal: it arrived in four pieces with newlines in the middle, which
        # pastes as a broken link. A line that scrolls sideways is worse-looking and works.
        err_console.print(f"  {url}\n", soft_wrap=True)
        if user_code:
            err_console.print(f"  Code: [bold]{user_code}[/bold]\n")
        if not open_browser:
            return
        if webbrowser.open(url):
            err_console.print("[dim]Opened your browser. Finish signing in there.[/dim]\n")
        else:
            err_console.print("[dim]No browser could be opened; use the URL above.[/dim]\n")

    return prompt


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
    open_browser: bool = typer.Option(
        None,
        "--open/--no-open",
        help="Open the sign-in URL in your browser. Default: open when running in a terminal. "
        "--no-open only prints the URL (headless, SSH, scripts).",
    ),
) -> None:
    """Sign in and store an SSO access token.

    Needed only for `project list` and `project create`; every other command uses the
    project's API key.

    The device flow is tried first because it needs no local listener, so it works over
    SSH and in a container. Both flows require the platform's OAuth client to allow them:
    if neither is enabled, obtain a token another way and pass it with --token.

    [bold]Example:[/bold]

        $ zadctl login
    """
    formatter = ctx.obj["formatter"]
    settings = ctx.obj["settings"]

    if token:
        # A token handed in by hand is taken as given (it may come from a realm this CLI
        # knows nothing about), but if it is a readable JWT without the audience the API
        # wants, saying so now beats a bare 401 on the next command.
        missing = auth.token_claims(token) and REQUIRED_AUDIENCE not in auth.token_audiences(token)
        credentials.store_token(token)
        formatter.render_success("Token stored.")
        if missing:
            err_console.print(
                f"[yellow]Warning:[/yellow] this token has no '{REQUIRED_AUDIENCE}' audience; "
                "the API will reject it with a 401."
            )
        _next_step(ctx, token)
        return

    issuer = settings.sso_issuer
    client = settings.keycloak_client_id
    err_console.print(f"[dim]Signing in at {issuer} as client {client}[/dim]")

    try:
        endpoints = auth.Endpoints.discover(issuer)
    except auth.LoginError as e:
        formatter.render_error(str(e))
        raise typer.Exit(2) from e

    scope = auth.audience_scope(endpoints)
    # Unset means "open when there is someone watching": a browser launched from a script
    # or a CI job is a surprise, not a convenience.
    prompt = _make_prompt(sys.stderr.isatty() if open_browser is None else open_browser)
    attempts = []
    if device is not False and endpoints.device:
        attempts.append(("device", lambda: auth.device_login(endpoints, client, on_prompt=prompt, scope=scope)))
    if device is not True:
        attempts.append(("browser", lambda: auth.loopback_login(endpoints, client, on_prompt=prompt, scope=scope)))

    problems: list[str] = []
    for name, attempt in attempts:
        try:
            access_token, refresh_token = attempt()
            # A token without the right audience is worse than no token: it stores
            # cleanly and then fails on every call. Refuse it here, and say whose side
            # the fix is on.
            auth.check_audience(access_token, client_id=client, issuer=endpoints.issuer or issuer)
        except auth.AudienceError as e:
            formatter.render_error(str(e))
            raise typer.Exit(2) from e
        except auth.LoginError as e:
            problems.append(f"{name}: {e}")
            continue
        credentials.store_token(access_token, refresh_token)
        formatter.render_success(f"Token stored in {envfile.env_path()}.")
        _note_lifetime(access_token)
        _next_step(ctx, access_token)
        return

    formatter.render_error(
        "Could not sign in.",
        details={
            "attempts": "; ".join(problems),
            "client": f"'{client}' in realm '{settings.keycloak_realm}' at {settings.keycloak_url}",
            "hint": (
                f"The OAuth client '{client}' must exist as a public client with the device grant "
                "enabled or a http://127.0.0.1:<port>/callback redirect URI registered, and an audience "
                f"mapper for '{REQUIRED_AUDIENCE}'. Point at another Keycloak with "
                "`zadctl config set keycloak_url <url>`. Until then, pass a token with --token or set "
                "ZAD_SSO_TOKEN."
            ),
        },
    )
    raise typer.Exit(2)


def logout_command(ctx: typer.Context) -> None:
    """Forget the stored token, active project and API keys.

    [bold]Example:[/bold]

        $ zadctl logout
    """
    formatter = ctx.obj["formatter"]
    path = credentials.clear()
    formatter.render_success(f"Credentials cleared ({path}).")
