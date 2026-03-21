"""Main CLI entrypoint: Typer app with sub-command groups."""

from __future__ import annotations

import typer

from zad_cli import __version__
from zad_cli.commands import (
    backup,
    clone,
    component,
    deployment,
    invite,
    logs,
    metrics,
    project,
    resource,
    restore,
    service,
    task,
)
from zad_cli.commands.config_cmd import app as config_app

app = typer.Typer(
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
app.add_typer(invite.app, name="invite")


@app.callback()
def main_callback(
    ctx: typer.Context,
    output: str = typer.Option("table", "--output", "-o", help="Output format: table, json, yaml"),
    api_key: str = typer.Option(None, "--api-key", envvar="ZAD_API_KEY", help="API key for the project"),
    api_url: str = typer.Option(None, "--api-url", envvar="ZAD_API_URL", help="Operations Manager API base URL"),
    project_id: str = typer.Option(None, "--project", "-p", envvar="ZAD_PROJECT_ID", help="Project ID"),
    no_wait: bool = typer.Option(False, "--no-wait", help="Don't wait for async operations, return task ID"),
) -> None:
    """Global options applied to all commands."""
    from zad_cli.output.formatter import OutputFormatter
    from zad_cli.settings import Settings

    ctx.ensure_object(dict)
    settings = Settings.resolve(api_url=api_url, api_key=api_key, project_id=project_id, output_format=output)
    ctx.obj["settings"] = settings
    ctx.obj["formatter"] = OutputFormatter(fmt=settings.output_format)
    ctx.obj["no_wait"] = no_wait


@app.command()
def version() -> None:
    """Show version information."""
    print(f"zad-cli {__version__}")


def main() -> None:
    """CLI entrypoint."""
    from dotenv import load_dotenv

    load_dotenv()
    app()
