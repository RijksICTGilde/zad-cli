"""Clone commands: database, bucket (from external sources)."""

from __future__ import annotations

import typer

app = typer.Typer(help="Clone data from external sources.", no_args_is_help=True)


def _get_helpers(ctx: typer.Context):
    from zad_cli.cli import _ensure_client

    _ensure_client(ctx)
    return ctx.obj["client"], ctx.obj["formatter"]


@app.command()
def database(
    ctx: typer.Context,
    project: str = typer.Argument(help="Project name"),
    deployment: str = typer.Argument(help="Deployment name"),
    host: str = typer.Option(..., "--host", help="Source database host"),
    port: int = typer.Option(5432, "--port", help="Source database port"),
    dbname: str = typer.Option(..., "--dbname", help="Source database name"),
    username: str = typer.Option(..., "--username", help="Source database username"),
    password: str = typer.Option(..., "--password", help="Source database password"),
) -> None:
    """Clone a database from an external source."""
    client, formatter = _get_helpers(ctx)

    payload = {
        "host": host,
        "port": port,
        "dbname": dbname,
        "username": username,
        "password": password,
    }

    try:
        result = client.clone_database(project, deployment, payload)
        formatter.render(result)
        formatter.render_success("Database clone started.")
    except Exception as e:
        formatter.render_error(str(e))
        raise typer.Exit(1) from e


@app.command()
def bucket(
    ctx: typer.Context,
    project: str = typer.Argument(help="Project name"),
    deployment: str = typer.Argument(help="Deployment name"),
    endpoint: str = typer.Option(..., "--endpoint", help="Source S3 endpoint"),
    bucket_name: str = typer.Option(..., "--bucket-name", help="Source bucket name"),
    access_key: str = typer.Option(..., "--access-key", help="Source access key"),
    secret_key: str = typer.Option(..., "--secret-key", help="Source secret key"),
) -> None:
    """Clone a bucket from an external source."""
    client, formatter = _get_helpers(ctx)

    payload = {
        "endpoint": endpoint,
        "bucket": bucket_name,
        "access_key": access_key,
        "secret_key": secret_key,
    }

    try:
        result = client.clone_bucket(project, deployment, payload)
        formatter.render(result)
        formatter.render_success("Bucket clone started.")
    except Exception as e:
        formatter.render_error(str(e))
        raise typer.Exit(1) from e
