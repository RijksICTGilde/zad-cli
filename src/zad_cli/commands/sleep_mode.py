"""`zadctl service sleep-mode`: what the platform does with a deployment that sleeps.

Configuring the service is `zadctl service config set sleep-mode`, like every other service
with a config document. These two are not configuration: they ask the platform what state a
deployment is in right now, and put it back on its feet. The API has had them all along,
under `/api/sleep-mode/{project}/{deployment}/`; the CLI deferred them as "a separate
feature" until a practice run turned sleep-mode on and could not show it worked.

They took a wake token when they landed here, because that was the only credential the
platform accepted and nobody could say where to get one. It accepts the project key now, so
these are ordinary commands.
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

# Both endpoints used to answer 401 "X-Wake-Token header required" to a perfectly good
# project key, and the spec documented neither header -- so these commands shipped with a
# `--wake-token` nobody knew how to obtain. The platform now documents both and accepts the
# project key: "so a project owner can wake his own deployment". The flag stays for whoever
# holds a waker page's own token, which wakes that one deployment and nothing else.
_TOKEN_HELP = (
    "A waker page's own token, which wakes only that deployment. Not needed as a project "
    "owner: your project API key is accepted here."
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
    """Show whether a deployment is awake, asleep, waking, or never sleeps.

    Two fields come back and they answer different questions. `sleep_state` is the
    deployment's real state. `state` is the waker's poll contract and has only `starting`
    and `ready`: it reads `starting` whenever the app has no ready pod *and* whenever there
    is no waker at all, so a healthy deployment with sleep-mode switched off reports
    `starting` there forever. A practice run read that as a stuck deployment.

    [bold]Example:[/bold]

        $ zadctl service sleep-mode status productie
    """
    project = require_project(ctx)
    client, formatter = get_helpers(ctx)

    result = client.sleep_mode_status(project, deployment, wake_token)

    # `sleep_state` first, because it is the answer to the question that was asked. The dict
    # is rendered in insertion order, and the platform happens to send the waker's field
    # first -- which is the one that misleads.
    if isinstance(result, dict) and "sleep_state" in result:
        result = {"sleep_state": result["sleep_state"], **{k: v for k, v in result.items() if k != "sleep_state"}}

    formatter.render_detail(result)


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
