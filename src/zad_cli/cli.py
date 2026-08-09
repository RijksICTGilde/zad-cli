"""Main CLI entrypoint: Typer app with sub-command groups."""

from __future__ import annotations

import typer
from typer.core import TyperGroup

from zad_cli import __version__
from zad_cli.commands import (
    admin,
    attachment,
    backup,
    clone,
    component,
    db,
    deployment,
    login,
    logs,
    metrics,
    project,
    registry,
    resource,
    restore,
    service,
    task,
)
from zad_cli.commands.config_cmd import app as config_app
from zad_cli.commands.open_cmd import app as open_app
from zad_cli.commands.values import alias_app, env_app


def _one_output_format(output: str | None, *, json_out: bool, yaml_out: bool) -> str | None:
    """Fold `--json` / `--yaml` into `--output`, refusing a combination that contradicts itself.

    They are sugar, not a second channel: two ways of asking for a format that disagree is a
    typo worth reporting, not a precedence rule worth inventing.
    """
    shorthands = [fmt for fmt, given in (("json", json_out), ("yaml", yaml_out)) if given]
    if not shorthands:
        return output
    if len(shorthands) > 1:
        raise typer.BadParameter("--json and --yaml cannot be combined.")
    shorthand = shorthands[0]
    if output is not None and output.strip().lower() != shorthand:
        raise typer.BadParameter(f"--{shorthand} contradicts --output {output}; pass one of the two.")
    return shorthand


class _GlobalOptionsGroup(TyperGroup):
    """Hoist global options to before the subcommand so they work in any position."""

    _OPTS_WITH_VALUE = frozenset(
        {
            "--output",
            "-o",
            "--api-key",
            "--api-url",
            "--project",
            "-p",
            "--keycloak-url",
            "--keycloak-realm",
            "--keycloak-client-id",
        }
    )
    _FLAGS = frozenset(
        {
            "--no-wait",
            "--verbose",
            "-v",
            "--version",
            "-V",
            "--strict",
            "--rollout",
            "--no-rollout",
            "--refresh-catalog",
            "--json",
            "--yaml",
        }
    )

    def parse_args(self, ctx, args):  # noqa: ANN001
        global_args: list[str] = []
        remaining: list[str] = []
        i = 0
        while i < len(args):
            arg = args[i]
            if arg == "--":
                remaining.extend(args[i:])
                break
            elif "=" in arg and arg.split("=", 1)[0] in self._OPTS_WITH_VALUE:
                global_args.append(arg)
                i += 1
            elif arg in self._OPTS_WITH_VALUE:
                global_args.append(arg)
                if i + 1 < len(args):
                    global_args.append(args[i + 1])
                    i += 2
                else:
                    i += 1
            elif arg in self._FLAGS:
                global_args.append(arg)
                i += 1
            else:
                remaining.append(arg)
                i += 1
        return super().parse_args(ctx, global_args + remaining)


app = typer.Typer(
    cls=_GlobalOptionsGroup,
    help="CLI for ZAD (Zelfservice Applicatie Deployment).",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

# Panels group 25 command groups into something a reader can scan. The order within a
# panel goes from what you reach for most to what you reach for least.
SETUP = "Getting set up"
WORKLOADS = "Projects and deployments"
SERVICES = "Services and configuration"
DATA = "Data and recovery"
INSIGHT = "Seeing what is happening"
PLATFORM = "Platform administration"

app.command(name="login", rich_help_panel=SETUP)(login.login_command)
app.command(name="logout", rich_help_panel=SETUP)(login.logout_command)
app.add_typer(config_app, name="config", rich_help_panel=SETUP)

app.add_typer(project.app, name="project", rich_help_panel=WORKLOADS)
app.add_typer(deployment.app, name="deployment", rich_help_panel=WORKLOADS)
app.add_typer(component.app, name="component", rich_help_panel=WORKLOADS)
app.add_typer(task.app, name="task", rich_help_panel=WORKLOADS)

app.add_typer(service.app, name="service", rich_help_panel=SERVICES)
app.add_typer(env_app, name="env", rich_help_panel=SERVICES)
app.add_typer(alias_app, name="alias", rich_help_panel=SERVICES)
app.add_typer(attachment.app, name="attachment", rich_help_panel=SERVICES)
app.add_typer(db.app, name="db", rich_help_panel=SERVICES)
app.add_typer(registry.app, name="registry", rich_help_panel=SERVICES)
app.add_typer(resource.app, name="resource", rich_help_panel=SERVICES)

app.add_typer(backup.app, name="backup", rich_help_panel=DATA)
app.add_typer(restore.app, name="restore", rich_help_panel=DATA)
app.add_typer(clone.app, name="clone", rich_help_panel=DATA)

app.command(name="logs", rich_help_panel=INSIGHT)(logs.logs_command)
app.add_typer(metrics.app, name="metrics", rich_help_panel=INSIGHT)
app.add_typer(open_app, name="open", rich_help_panel=INSIGHT)

app.add_typer(admin.app, name="admin", rich_help_panel=PLATFORM)


def _version_callback(value: bool) -> None:
    if value:
        print(f"zad-cli {__version__}")
        raise typer.Exit()


@app.callback()
def main_callback(
    ctx: typer.Context,
    output: str = typer.Option(
        None,
        "--output",
        "-o",
        help="Output format: table, json, yaml. Default: table, or ZAD_OUTPUT_FORMAT / `zad config set output json`.",
    ),
    json_out: bool = typer.Option(False, "--json", help="Shorthand for --output json"),
    yaml_out: bool = typer.Option(False, "--yaml", help="Shorthand for --output yaml"),
    # No envvar= here: the environment is read in settings.py, which is also where the
    # precedence lives. Letting Typer fill the flag from the environment would make the
    # two indistinguishable, and `zad config list` could no longer say which one won.
    api_key: str = typer.Option(None, "--api-key", help="API key for the project (env: ZAD_API_KEY)"),
    api_url: str = typer.Option(None, "--api-url", help="Operations Manager API base URL (env: ZAD_API_URL)"),
    project_id: str = typer.Option(None, "--project", "-p", help="Project ID (env: ZAD_PROJECT_ID)"),
    no_wait: bool = typer.Option(False, "--no-wait", help="Don't wait for async operations, return task ID"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable verbose request logging"),
    strict: bool = typer.Option(
        False, "--strict", help="Exit non-zero when an operation succeeds but reports warnings (for CI/CD)"
    ),
    rollout: bool | None = typer.Option(
        None,
        "--rollout/--no-rollout",
        help="Roll the change out to the cluster. --no-rollout saves it and leaves the cluster untouched "
        "until `zad project refresh`; see `zad project pending`. Default: true, or ZAD_ROLLOUT / "
        "`zad config set rollout false`.",
    ),
    refresh_catalog: bool = typer.Option(
        False, "--refresh-catalog", help="Re-fetch the service catalog instead of using the cached copy"
    ),
    keycloak_url: str = typer.Option(
        None, "--keycloak-url", help="Keycloak base URL for `zad login` (env: ZAD_KEYCLOAK_URL)"
    ),
    keycloak_realm: str = typer.Option(
        None, "--keycloak-realm", help="Keycloak realm for `zad login` (env: ZAD_KEYCLOAK_REALM)"
    ),
    keycloak_client_id: str = typer.Option(
        None, "--keycloak-client-id", help="OAuth client `zad login` uses (env: ZAD_KEYCLOAK_CLIENT_ID)"
    ),
    version: bool = typer.Option(
        False, "--version", "-V", help="Show version and exit", callback=_version_callback, is_eager=True
    ),
) -> None:
    """Global options applied to all commands."""
    from zad_cli.output.formatter import OutputFormatter
    from zad_cli.settings import Settings

    ctx.ensure_object(dict)
    output_format = _one_output_format(output, json_out=json_out, yaml_out=yaml_out)
    settings = Settings.resolve(
        api_url=api_url,
        api_key=api_key,
        project_id=project_id,
        output_format=output_format,
        verbose=verbose,
        rollout=rollout,
        keycloak_url=keycloak_url,
        keycloak_realm=keycloak_realm,
        keycloak_client_id=keycloak_client_id,
    )
    ctx.obj["settings"] = settings
    ctx.obj["formatter"] = OutputFormatter(fmt=settings.output_format)
    ctx.obj["no_wait"] = no_wait
    ctx.obj["strict"] = strict
    # Already resolved through flag > env > config > default; the flag is one of four voices.
    ctx.obj["rollout"] = settings.rollout
    ctx.obj["refresh_catalog"] = refresh_catalog


@app.command(rich_help_panel="Getting set up")
def version(
    ctx: typer.Context,
    client_only: bool = typer.Option(False, "--client-only", help="Skip the call to the server"),
) -> None:
    """Show the CLI version, and the version of the API it is pointed at.

    Two versions matter when something behaves unexpectedly: which CLI you are running,
    and which build of the platform is answering it.

    [bold]Example:[/bold]

        $ zad version
    """
    formatter = ctx.obj["formatter"]
    info: dict = {"zad_cli": __version__, "api_url": ctx.obj["settings"].api_url}

    if not client_only:
        from zad_cli.api.client import ZadClient

        client = ZadClient(api_url=ctx.obj["settings"].api_url, api_key=ctx.obj["settings"].api_key)
        try:
            server = client.server_version()
            info["server"] = {
                key: server.get(key) for key in ("name", "version", "commit", "branch", "build_date") if key in server
            }
        except Exception as e:  # noqa: BLE001 - an unreachable server must not hide the CLI version
            info["server"] = {"error": f"could not reach {ctx.obj['settings'].api_url}: {e}"}
        finally:
            client.close()

    formatter.render_document(info)


def main() -> None:
    """CLI entrypoint."""
    from dotenv import load_dotenv

    load_dotenv(dotenv_path=".env")
    app()
