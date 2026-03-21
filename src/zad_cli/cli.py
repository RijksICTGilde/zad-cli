"""Main CLI entrypoint: Typer app with sub-command groups."""

from __future__ import annotations

import sys

import typer

from zad_cli import __version__
from zad_cli.commands import backup, clone, deployment, invite, logs, metrics, project, restore
from zad_cli.commands.config_cmd import app as config_app

app = typer.Typer(
    help="CLI for ZAD (Zelfservice Applicatie Deployment).",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

# Register sub-command groups
app.add_typer(config_app, name="config")
app.add_typer(project.app, name="project")
app.add_typer(deployment.app, name="deployment")
app.add_typer(backup.app, name="backup")
app.add_typer(restore.app, name="restore")
app.add_typer(clone.app, name="clone")
app.add_typer(logs.app, name="logs")
app.add_typer(metrics.app, name="metrics")
app.add_typer(invite.app, name="invite")


@app.callback()
def main_callback(
    ctx: typer.Context,
    output: str = typer.Option("table", "--output", "-o", help="Output format: table, json, yaml"),
    api_key: str = typer.Option(None, "--api-key", envvar="ZAD_API_KEY", help="API key"),
    api_url: str = typer.Option(None, "--api-url", envvar="ZAD_API_URL", help="API base URL"),
    context: str = typer.Option(None, "--context", "-c", help="Config context to use"),
) -> None:
    """Global options applied to all commands."""
    from zad_cli.config.settings import Settings
    from zad_cli.output.formatter import OutputFormatter

    ctx.ensure_object(dict)

    settings = Settings.resolve(api_url=api_url, api_key=api_key, output_format=output, context=context)
    ctx.obj["settings"] = settings
    ctx.obj["formatter"] = OutputFormatter(fmt=settings.output_format)


def _ensure_client(ctx: typer.Context) -> None:
    """Lazily create the API client when first needed."""
    if ctx.obj.get("client"):
        return

    from zad_cli.api.client import ZadClient

    settings = ctx.obj["settings"]
    if not settings.api_key:
        print(
            "Error: ZAD_API_KEY not set.\nSet it in your environment or .env file, or pass --api-key.",
            file=sys.stderr,
        )
        raise typer.Exit(1)

    ctx.obj["client"] = ZadClient(
        api_url=settings.api_url,
        api_key=settings.api_key,
        max_retries=settings.max_retries,
        retry_delay=settings.retry_delay,
        task_timeout=settings.task_timeout,
        task_poll_interval=settings.task_poll_interval,
    )


@app.command()
def version() -> None:
    """Show version information."""
    print(f"zad-cli {__version__}")


@app.command()
def completion(
    shell: str = typer.Argument("bash", help="Shell type: bash, zsh, fish"),
) -> None:
    """Generate shell completion script."""
    import subprocess

    try:
        result = subprocess.run(
            [sys.executable, "-m", "zad_cli"],
            input="",
            capture_output=True,
            text=True,
            env={"_ZAD_COMPLETE": f"complete_{shell}"},
        )
        print(result.stdout)
    except Exception as e:
        print(f"Error generating completions: {e}", file=sys.stderr)
        raise typer.Exit(1) from e


def main() -> None:
    """CLI entrypoint."""
    app()
