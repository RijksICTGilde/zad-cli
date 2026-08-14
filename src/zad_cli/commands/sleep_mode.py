"""`zadctl service sleep-mode`: what the platform does with a deployment that sleeps.

Configuring the service is `zadctl service config set sleep-mode`, like every other service
with a config document. These two are not configuration: they ask the platform what state a
deployment is in right now, and put it back on its feet. The API has had them all along,
under `/api/sleep-mode/{project}/{deployment}/`; the CLI deferred them as "a separate
feature" until a practice run turned sleep-mode on and could not show it worked.
"""

from __future__ import annotations

from typing import Annotated, Any

import typer
from typer.core import TyperGroup

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


class _SleepModeGroup(TyperGroup):
    """The group's help, with what you can set on the service underneath it.

    A service with its own verbs is still a service. `zadctl service sleep-mode --help`
    answers "what is this and what can I set" for every other service in the catalog, and
    it would be a strange exception if the one with a `wake` command answered only "here
    are two verbs".
    """

    def format_help(self, ctx: Any, formatter: Any) -> None:
        from zad_cli.commands.service import service_options_help

        extra = service_options_help("sleep-mode", ctx)
        if extra:
            self.help = f"{(self.help or '').rstrip()}\n\n{extra}"
        super().format_help(ctx, formatter)


app = typer.Typer(
    cls=_SleepModeGroup,
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
