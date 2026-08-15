"""`zadctl service sleep-mode`: what the platform does with a deployment that sleeps.

Configuring the service is `zadctl service config set sleep-mode`, like every other service
with a config document. These two are not configuration: they ask the platform what state a
deployment is in right now, and put it back on its feet. The API has had them all along,
under `/api/sleep-mode/{project}/{deployment}/`; the CLI deferred them as "a separate
feature" until a practice run turned sleep-mode on and could not show it worked.
"""

from __future__ import annotations

from typing import Annotated

import typer

from zad_cli.helpers import (
    complete_deployment,
    get_helpers,
    handle_api_errors,
    render_dry_run,
    require_project,
    surface_warnings,
)

# Measured against the sandbox rather than read off the spec, which documents neither: both
# endpoints answer 401 "X-Wake-Token header required" to a perfectly good project API key.
# They are the waker page's own endpoints, and the page holds the token. Until the platform
# says where an operator gets one -- or accepts the project key -- the caller brings it.
_TOKEN_HELP = (
    "Wake token for these two endpoints. The platform gates them on an X-Wake-Token header "
    "instead of the project API key, and answers 401 without it."
)


# The group's help carries what you can set on the service underneath it, because a service
# with its own verbs is still a service and it would be strange if the one with a `wake`
# command answered only "here are two verbs". That used to be a group class of its own here;
# it is `ServiceVerbsGroup`, applied where `zadctl service` registers this app, now that the
# other five verb-driven services need the same thing.
app = typer.Typer(
    help=(
        "Ask after a sleeping deployment, and wake it.\n\n"
        "Configure the service itself with [bold]zadctl service config set sleep-mode[/bold]."
    ),
    no_args_is_help=True,
)


@app.command()
@handle_api_errors
def status(
    ctx: typer.Context,
    deployment: Annotated[str, typer.Argument(help="Deployment name", autocompletion=complete_deployment)],
    wake_token: str = typer.Option(None, "--wake-token", help=_TOKEN_HELP, envvar="ZAD_WAKE_TOKEN"),
) -> None:
    """Show whether the app behind the waker is back yet: starting or ready.

    [bold]Example:[/bold]

        $ zadctl service sleep-mode status productie
    """
    project = require_project(ctx)
    client, formatter = get_helpers(ctx)

    formatter.render_detail(client.sleep_mode_status(project, deployment, wake_token))


@app.command()
@handle_api_errors
def wake(
    ctx: typer.Context,
    deployment: Annotated[str, typer.Argument(help="Deployment name", autocompletion=complete_deployment)],
    wake_token: str = typer.Option(None, "--wake-token", help=_TOKEN_HELP, envvar="ZAD_WAKE_TOKEN"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be sent without making the API call"),
) -> None:
    """Wake a sleeping deployment now, without waiting for a visitor.

    The deployment does a cold start, so this returns before it serves traffic; ask
    `status` again, or watch `zadctl deployment describe`.

    [bold]Example:[/bold]

        $ zadctl service sleep-mode wake productie
    """
    project = require_project(ctx)
    client, formatter = get_helpers(ctx)

    if dry_run:
        render_dry_run(formatter, "POST", f"/sleep-mode/{project}/{deployment}/wake", {})
        return

    result = client.wake_deployment(project, deployment, wake_token)
    formatter.render(result)
    formatter.render_success(f"Deployment '{deployment}' woken.")
    surface_warnings(ctx, formatter, result)
