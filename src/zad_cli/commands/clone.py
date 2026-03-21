"""Clone commands: database, bucket, validate."""

from __future__ import annotations

import typer

from zad_cli.helpers import get_helpers, handle_api_errors, require_project

app = typer.Typer(help="Clone data from external sources.", no_args_is_help=True)


@app.command()
@handle_api_errors
def database(
    ctx: typer.Context,
    deployment: str = typer.Argument(help="Deployment name"),
    host: str = typer.Option(..., "--host", help="Source database host"),
    port: int = typer.Option(5432, "--port", help="Source database port"),
    dbname: str = typer.Option(..., "--dbname", help="Source database name"),
    schema: str = typer.Option("public", "--schema", help="Source database schema"),
    username: str = typer.Option(..., "--username", help="Source database username"),
    password: str = typer.Option(..., "--password", envvar="SOURCE_DB_PASSWORD", help="Source database password"),
    tunnel: str = typer.Option(None, "--tunnel", help="Chisel tunnel address for private networks"),
    force: bool = typer.Option(False, "--force", help="Force clone even if target has data"),
) -> None:
    """Clone a database from an external source.

    Requires ZAD_API_KEY and ZAD_PROJECT_ID (or --api-key and -p)
    """
    project = require_project(ctx)
    client, formatter = get_helpers(ctx)

    payload: dict = {
        "sourceHost": host,
        "sourcePort": port,
        "sourceDatabase": dbname,
        "sourceSchema": schema,
        "sourceUsername": username,
        "sourcePassword": password,
        "forceClone": force,
    }
    if tunnel:
        payload["tunnel"] = tunnel

    result = client.clone_database(project, deployment, payload)
    formatter.render(result)
    formatter.render_success("Database clone started.")


@app.command()
@handle_api_errors
def bucket(
    ctx: typer.Context,
    deployment: str = typer.Argument(help="Deployment name"),
    host: str = typer.Option(..., "--host", help="Source S3/MinIO host"),
    port: int = typer.Option(9000, "--port", help="Source S3/MinIO port"),
    bucket_name: str = typer.Option(..., "--bucket-name", help="Source bucket name"),
    access_key: str = typer.Option(..., "--access-key", envvar="SOURCE_S3_ACCESS_KEY", help="Source access key"),
    secret_key: str = typer.Option(..., "--secret-key", envvar="SOURCE_S3_SECRET_KEY", help="Source secret key"),
    secure: bool = typer.Option(True, "--secure/--no-secure", help="Use HTTPS for source connection"),
    tunnel: str = typer.Option(None, "--tunnel", help="Chisel tunnel address for private networks"),
    force: bool = typer.Option(False, "--force", help="Force clone even if target has data"),
) -> None:
    """Clone a bucket from an external source.

    Requires ZAD_API_KEY and ZAD_PROJECT_ID (or --api-key and -p)
    """
    project = require_project(ctx)
    client, formatter = get_helpers(ctx)

    payload: dict = {
        "sourceHost": host,
        "sourcePort": port,
        "sourceBucket": bucket_name,
        "sourceAccessKey": access_key,
        "sourceSecretKey": secret_key,
        "sourceSecure": secure,
        "forceClone": force,
    }
    if tunnel:
        payload["tunnel"] = tunnel

    result = client.clone_bucket(project, deployment, payload)
    formatter.render(result)
    formatter.render_success("Bucket clone started.")


@app.command()
@handle_api_errors
def validate(
    ctx: typer.Context,
    deployment: str = typer.Argument(help="Deployment name"),
) -> None:
    """Validate clone configuration without executing.

    Checks connectivity, credentials, and resource existence.

    Requires ZAD_API_KEY and ZAD_PROJECT_ID (or --api-key and -p)
    """
    project = require_project(ctx)
    client, formatter = get_helpers(ctx)

    result = client.validate_clone(project, deployment)
    formatter.render(result)
