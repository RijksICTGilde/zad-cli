"""Clone commands: database, bucket (from external sources)."""

from __future__ import annotations

import typer

from zad_cli.api.client import ZadApiError
from zad_cli.helpers import get_helpers, require_project

app = typer.Typer(help="Clone data from external sources.", no_args_is_help=True)


@app.command()
def database(
    ctx: typer.Context,
    deployment: str = typer.Argument(help="Deployment name"),
    host: str = typer.Option(..., "--host", help="Source database host"),
    port: int = typer.Option(5432, "--port", help="Source database port"),
    dbname: str = typer.Option(..., "--dbname", help="Source database name"),
    username: str = typer.Option(..., "--username", help="Source database username"),
    password: str = typer.Option(..., "--password", envvar="SOURCE_DB_PASSWORD", help="Source database password"),
) -> None:
    """Clone a database from an external source.

    Requires ZAD_API_KEY and ZAD_PROJECT_ID (or --api-key and -p)
    """
    project = require_project(ctx)
    client, formatter = get_helpers(ctx)

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
    except ZadApiError as e:
        formatter.render_error(str(e))
        raise typer.Exit(1) from e


@app.command()
def bucket(
    ctx: typer.Context,
    deployment: str = typer.Argument(help="Deployment name"),
    endpoint: str = typer.Option(..., "--endpoint", help="Source S3 endpoint"),
    bucket_name: str = typer.Option(..., "--bucket-name", help="Source bucket name"),
    access_key: str = typer.Option(..., "--access-key", envvar="SOURCE_S3_ACCESS_KEY", help="Source access key"),
    secret_key: str = typer.Option(..., "--secret-key", envvar="SOURCE_S3_SECRET_KEY", help="Source secret key"),
) -> None:
    """Clone a bucket from an external source.

    Requires ZAD_API_KEY and ZAD_PROJECT_ID (or --api-key and -p)
    """
    project = require_project(ctx)
    client, formatter = get_helpers(ctx)

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
    except ZadApiError as e:
        formatter.render_error(str(e))
        raise typer.Exit(1) from e
