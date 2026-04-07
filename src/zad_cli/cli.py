"""Main CLI entrypoint: Typer app with sub-command groups."""

from __future__ import annotations

import typer
from typer.core import TyperGroup

from zad_cli import __version__
from zad_cli.commands import (
    backup,
    clone,
    component,
    deployment,
    logs,
    metrics,
    project,
    resource,
    restore,
    service,
    task,
)
from zad_cli.commands.config_cmd import app as config_app
from zad_cli.commands.open_cmd import app as open_app


class _GlobalOptionsGroup(TyperGroup):
    """Hoist global options to before the subcommand so they work in any position."""

    _OPTS_WITH_VALUE = frozenset({"--output", "-o", "--api-key", "--api-url", "--project", "-p"})
    _FLAGS = frozenset({"--no-wait", "--verbose", "-v", "--version", "-V"})

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

app.add_typer(config_app, name="config")
app.add_typer(project.app, name="project")
app.add_typer(deployment.app, name="deployment")
app.add_typer(component.app, name="component")
app.add_typer(service.app, name="service")
app.add_typer(resource.app, name="resource")
app.add_typer(task.app, name="task")
app.add_typer(backup.app, name="backup")
app.add_typer(restore.app, name="restore")
app.add_typer(clone.app, name="clone")
app.command(name="logs")(logs.logs_command)
app.add_typer(metrics.app, name="metrics")
app.add_typer(open_app, name="open")


def _version_callback(value: bool) -> None:
    if value:
        print(f"zad-cli {__version__}")
        raise typer.Exit()


@app.callback()
def main_callback(
    ctx: typer.Context,
    output: str = typer.Option("table", "--output", "-o", help="Output format: table, json, yaml"),
    api_key: str = typer.Option(None, "--api-key", envvar="ZAD_API_KEY", help="API key for the project"),
    api_url: str = typer.Option(None, "--api-url", envvar="ZAD_API_URL", help="Operations Manager API base URL"),
    project_id: str = typer.Option(None, "--project", "-p", envvar="ZAD_PROJECT_ID", help="Project ID"),
    no_wait: bool = typer.Option(False, "--no-wait", help="Don't wait for async operations, return task ID"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable verbose request logging"),
    version: bool = typer.Option(False, "--version", "-V", help="Show version and exit", callback=_version_callback, is_eager=True),
) -> None:
    """Global options applied to all commands."""
    from zad_cli.output.formatter import OutputFormatter
    from zad_cli.settings import Settings

    ctx.ensure_object(dict)
    settings = Settings.resolve(
        api_url=api_url, api_key=api_key, project_id=project_id, output_format=output, verbose=verbose
    )
    ctx.obj["settings"] = settings
    ctx.obj["formatter"] = OutputFormatter(fmt=settings.output_format)
    ctx.obj["no_wait"] = no_wait



def main() -> None:
    """CLI entrypoint."""
    from dotenv import load_dotenv

    load_dotenv(dotenv_path=".env")
    app()
