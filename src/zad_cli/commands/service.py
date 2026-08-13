"""Service commands: browse the catalog and configure a service per layer.

Nothing in this file knows a service name. The catalog says which services exist and at
which layers each accepts config; the vendored spec says what the body for that layer
looks like. A service added upstream needs no change here.
"""

from __future__ import annotations

from typing import Annotated, Any

import typer

from zad_cli.helpers import (
    complete_component,
    complete_deployment,
    complete_service,
    confirm_action,
    get_catalog,
    get_helpers,
    handle_api_errors,
    render_dry_run,
    require_project,
    require_service,
    resolve_target,
    surface_warnings,
)
from zad_cli.manifest import apply_sets, load_payload_file, render_skeleton

app = typer.Typer(
    help=(
        "Browse and configure platform services.\n\n"
        "Which services exist depends on the API you are pointed at, so this help cannot list "
        "them: run [bold]zad service list[/bold] to see them, and "
        "[bold]zad service describe <name>[/bold] for what one does.\n\n"
        "`list` and `describe` read the public catalog and need no credentials. "
        "The `config` commands require ZAD_API_KEY and ZAD_PROJECT_ID (or --api-key and -p)."
    ),
    no_args_is_help=True,
)

config_app = typer.Typer(
    help=(
        "Read and write a service's configuration, per layer.\n\n"
        "Run [bold]zad service list[/bold] for the service names, and "
        "[bold]zad service config schema <name> --target <layer>[/bold] for the fields a layer takes."
    ),
    no_args_is_help=True,
)
app.add_typer(config_app, name="config")

# The three services that carry *values* instead of a config document need their own verbs:
# "add this attachment" is not expressible as "set this document". They live here, under the
# name `zad service list` shows, so that everything in that list is reachable the way it is
# named. The short top-level forms (`zad attachment`, `zad env`, `zad alias`) are the same
# apps registered twice: having to remember which services are the exception is worse than
# two spellings of the same thing.
from zad_cli.commands import attachment as _attachment  # noqa: E402
from zad_cli.commands.values import alias_app as _alias_app  # noqa: E402
from zad_cli.commands.values import env_app as _env_app  # noqa: E402

app.add_typer(_attachment.app, name="attachments")
app.add_typer(_env_app, name="user-env-vars")
app.add_typer(_alias_app, name="aliases")

# A few services are driven by their own command group rather than by `service config`:
# they carry *values* (a set of entries) instead of *config* (one document per layer), and
# a group with its own verbs says that better than a generic setter would. The registry
# cannot state this, because these are our command names, not its.
_OWN_COMMAND: dict[str, tuple[str, str]] = {
    "attachments": ("zad service attachments", "zad attachment"),
    "user-env-vars": ("zad service user-env-vars", "zad env"),
    "aliases": ("zad service aliases", "zad alias"),
}


def _use_short(entry: Any) -> str:
    """The command group, for a table cell. `describe` gives the whole invocation."""
    own = _OWN_COMMAND.get(entry.name)
    if own:
        return own[1]
    return "zad service config" if entry.targets else "-"


def _how_to_use(entry: Any) -> str:
    """The command that actually configures this service."""
    own = _OWN_COMMAND.get(entry.name)
    if own:
        full, short = own
        return f"{full} (or the shorter `{short}`)"
    if not entry.targets:
        return "nothing to set: the platform runs this by itself"
    if len(entry.targets) == 1:
        return f"zad service config set {entry.name}"
    return f"zad service config set {entry.name} --target <{'|'.join(entry.targets)}>"


_TARGET_HELP = "Config layer to act on: project, component or deployment. Optional when the service has only one."


def _first_sentence(text: str, limit: int = 90) -> str:
    """First sentence of a description, for the list table."""
    head = text.split(". ", 1)[0].strip()
    if len(head) > limit:
        head = head[: limit - 1].rstrip() + "…"
    return head


def _binding_line(entry: Any) -> str:
    """What `binding` means, in the imperative, rather than as a bare word.

    "binding: component" said nothing to anyone who did not already know. It is the answer
    to "how does a component actually get this service's variables?", and the answer is a
    command they have to run: without it the service is configured and provisioned and the
    component still receives nothing, with no warning anywhere.
    """
    if entry.binding == "component":
        return "component - add it to each component that uses it: zad component add <name> --service " + entry.name
    if entry.binding == "deployment":
        return f"deployment - configured per deployment; no per-component binding for {entry.name}"
    return entry.binding or "-"


def _kind_of(entry: Any) -> str:
    """Label a service as system or user, falling back to what `configurable` implies."""
    return entry.kind or ("user" if entry.configurable else "system")


@app.command("list")
def list_services(
    ctx: typer.Context,
    all_services: bool = typer.Option(False, "--all", help="Include hidden services"),
) -> None:
    """List the services this platform offers.

    Hidden services are internal variants the portal does not offer directly; --all shows
    them. Needs no API key: the catalog is project-independent.

    [bold]Example:[/bold]

        $ zad service list
    """
    formatter = ctx.obj["formatter"]
    catalog = get_catalog(ctx)
    entries = catalog.visible(include_hidden=all_services)

    if formatter.fmt in ("json", "yaml"):
        formatter.render([{**e.to_dict(), "use": _how_to_use(e)} for e in entries])
        return

    rows = [
        {
            "service": e.name,
            "kind": _kind_of(e),
            "binding": e.binding,
            "targets": ", ".join(e.targets),
            "values": ", ".join(e.value_targets),
            # Targets and values say where a setting lands; neither says which command puts
            # it there, which is the question someone reading this list actually has.
            "use": _use_short(e),
            # The catalog descriptions are full paragraphs; the table is an index, and
            # `service describe` is where the whole text belongs.
            "description": _first_sentence(e.description),
        }
        for e in entries
    ]
    formatter.render(
        rows,
        columns=["service", "kind", "use", "targets", "values", "description"],
        title=f"Services ({catalog.source})",
    )


@app.command("types")
def list_service_types(
    ctx: typer.Context,
    all_services: bool = typer.Option(False, "--all", help="Include hidden services"),
) -> None:
    """Alias of `service list`, kept for scripts that already call it.

    [bold]Example:[/bold]

        $ zad service types
    """
    list_services(ctx, all_services=all_services)


@app.command()
def describe(
    ctx: typer.Context,
    service_name: Annotated[str, typer.Argument(help="Service name", autocompletion=complete_service)],
) -> None:
    """Explain one service: what it does, what you can set, which variables it offers.

    The explanation comes from the platform itself and is in Dutch.

    [bold]Example:[/bold]

        $ zad service describe postgresql-database
    """
    from zad_cli.api.registry import UnknownServiceError, load_service

    formatter = ctx.obj["formatter"]
    settings = ctx.obj["settings"]
    require_service(ctx, service_name)  # fail early, naming the valid services

    try:
        entry = load_service(settings.api_url, service_name, refresh=ctx.obj.get("refresh_catalog", False))
    except UnknownServiceError as e:
        raise typer.BadParameter(str(e)) from e

    if formatter.fmt in ("json", "yaml"):
        # `use` is added here too: an agent reading this is exactly the reader who cannot
        # guess that `attachments` is driven by `zad attachment` and not by `service config`.
        formatter.render({**entry.to_dict(), "use": _how_to_use(entry)})
        return

    formatter.render_detail(
        {
            "service": entry.name,
            "kind": _kind_of(entry),
            "binding": _binding_line(entry),
            "configurable": entry.configurable,
            "use": _how_to_use(entry),
            "config targets": ", ".join(entry.targets) or "-",
            "value targets": ", ".join(entry.value_targets) or "-",
            "schema version": entry.config_schema_version or "-",
            "requires": ", ".join(entry.requires) or "-",
        },
        title=entry.name,
    )
    if entry.description:
        formatter.console.print(f"\n{entry.description}\n")
    if entry.explanation:
        from rich.markdown import Markdown

        formatter.console.print(Markdown(entry.explanation))
    if entry.variables:
        rows = [
            {
                "variable": v.get("name", ""),
                "description": v.get("description", ""),
                "aliases": ", ".join(v.get("aliases") or []),
                "secret": "yes" if v.get("secret_key") else "",
            }
            for v in entry.variables
        ]
        formatter.render(rows, columns=["variable", "description", "aliases", "secret"], title="Variables")


# --- service config ---


def _template_path(entry: Any, layer: str) -> str:
    """This service+layer as the spec spells it, for looking the request schema up.

    Raises the same usage error as the endpoint itself for a layer the CLI cannot reach.
    This runs first, so leaving it unguarded turned a layer the registry over-advertises
    into a Python traceback before the friendly message ever got a chance.
    """
    from zad_cli.api.registry import MissingLayerError

    try:
        path = entry.config_endpoint(layer, component="{component_name}", deployment="{deployment_name}")
    except MissingLayerError as e:
        raise typer.BadParameter(str(e)) from e
    return path.replace("{project}", "{project_name}")


def _resolve_layer(ctx: typer.Context, service_name: str, target: str | None) -> tuple[Any, str]:
    entry = require_service(ctx, service_name)
    return entry, resolve_target(entry, target)


def _endpoint(entry: Any, layer: str, project: str, component: str | None, deployment: str | None) -> str:
    from zad_cli.api.registry import MissingLayerError

    try:
        path = entry.config_endpoint(layer, component=component, deployment=deployment)
    except MissingLayerError as e:
        raise typer.BadParameter(str(e)) from e
    return path.replace("{project}", project)


@config_app.command("get")
@handle_api_errors
def config_get(
    ctx: typer.Context,
    service_name: Annotated[str, typer.Argument(help="Service name", autocompletion=complete_service)],
) -> None:
    """Show a service's current config, across every layer it is set on.

    [bold]Example:[/bold]

        $ zad service config get postgresql-database
    """
    entry = require_service(ctx, service_name)
    project = require_project(ctx)
    client, formatter = get_helpers(ctx)

    result = client.get_service_config(project, entry.name)
    formatter.render_document(result)


@config_app.command("schema")
def config_schema(
    ctx: typer.Context,
    service_name: Annotated[str, typer.Argument(help="Service name", autocompletion=complete_service)],
    target: str = typer.Option(None, "--target", help=_TARGET_HELP),
    skeleton: bool = typer.Option(False, "--generate-skeleton", help="Print an example body instead of the schema"),
    write: str = typer.Option(
        None, "--write", help="Write the schema to this file so an editor can validate your manifest against it"
    ),
) -> None:
    """Print the JSON Schema for a service's config at one layer.

    This is what a tool needs to build a valid body without trial and error. With --write
    the schema lands in a file and the CLI prints the `yaml-language-server` line to put at
    the top of your manifest, which gives editors completion and validation as you type.

    [bold]Examples:[/bold]

        $ zad service config schema postgresql-database --target project

        $ zad service config schema postgresql-database --write .zad/postgresql-database.json
    """
    import json
    from pathlib import Path

    from zad_cli.api import spec

    formatter = ctx.obj["formatter"]
    entry, layer = _resolve_layer(ctx, service_name, target)

    schema = spec.request_schema("PUT", _template_path(entry, layer))
    if schema is None:
        raise typer.BadParameter(f"The vendored API spec documents no request body for {entry.name} ({layer}).")

    if write:
        path = Path(write).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        # $schema and a title make the file usable on its own, not just as a fragment.
        document = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": f"{entry.name} config ({layer})",
            **schema,
        }
        path.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n")
        formatter.render_success(f"Schema written to {path}.")
        formatter.render_success(
            f"Add this line at the top of your manifest:\n  # yaml-language-server: $schema={path}"
        )
        return

    formatter.render_document(render_skeleton(schema) if skeleton else schema)


@config_app.command("set")
@handle_api_errors
def config_set(
    ctx: typer.Context,
    service_name: Annotated[str, typer.Argument(help="Service name", autocompletion=complete_service)],
    target: str = typer.Option(None, "--target", help=_TARGET_HELP),
    component: Annotated[
        str | None,
        typer.Option("--component", "-c", help="Component, for a component layer", autocompletion=complete_component),
    ] = None,
    deployment: Annotated[
        str | None,
        typer.Option("--deployment", help="Deployment, for a deployment layer", autocompletion=complete_deployment),
    ] = None,
    file: str = typer.Option(None, "--file", "-f", help="YAML/JSON manifest with the config body ('-' for stdin)"),
    sets: Annotated[
        list[str] | None,
        typer.Option("--set", help="Set a field: dotted.path=value, repeatable. Wins over --file."),
    ] = None,
    generate_skeleton: bool = typer.Option(
        False, "--generate-skeleton", help="Print an example body for this layer and exit"
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be sent without making the API call"),
) -> None:
    """Write a service's configuration at one layer.

    Values come from a manifest, from --set flags, or both; --set wins, the way Helm
    treats them.

    [bold]Example:[/bold]

        $ zad service config set postgresql-database --set scope=project
    """
    from zad_cli.api import spec
    from zad_cli.manifest import validate_against_schema

    formatter = ctx.obj["formatter"]
    entry, layer = _resolve_layer(ctx, service_name, target)
    schema = spec.request_schema("PUT", _template_path(entry, layer))

    if generate_skeleton:
        if schema is None:
            raise typer.BadParameter(f"The vendored API spec documents no request body for {entry.name} ({layer}).")
        formatter.render_document(render_skeleton(schema))
        return

    payload: Any = load_payload_file(file) if file else None
    if sets:
        payload = apply_sets(payload if payload is not None else {}, sets)
    if payload is None:
        # An empty body means "use this service, with nothing set", which the API accepts
        # and which several services need: publish-on-web or persistent-storage are mostly
        # switched on rather than configured. Refusing it here made selecting a service
        # possible only through `echo {} | ... -f -`. A service that does need fields is
        # still caught, by the schema check below, which names the fields.
        payload = {}

    # Resolve the endpoint first: a missing --component is a more basic mistake than a
    # field being wrong, and reporting the body error first hides it.
    project = require_project(ctx)
    path = _endpoint(entry, layer, project, component, deployment)

    if schema is not None:
        validate_against_schema(payload, schema, what=f"{entry.name} ({layer}) config")

    client, formatter = get_helpers(ctx)

    if dry_run:
        render_dry_run(formatter, "PUT", path, payload if isinstance(payload, dict) else {"body": payload})
        return

    confirm_action(f"Set {entry.name} config at layer '{layer}' in project '{project}'?", yes, ctx)

    result = client.put_service_config(path, payload)
    formatter.render(result)
    formatter.render_success(f"Service '{entry.name}' configured at layer '{layer}'.")
    surface_warnings(ctx, formatter, result)


@config_app.command("clear")
@handle_api_errors
def config_clear(
    ctx: typer.Context,
    service_name: Annotated[str, typer.Argument(help="Service name", autocompletion=complete_service)],
    target: str = typer.Option(None, "--target", help=_TARGET_HELP),
    component: Annotated[
        str | None,
        typer.Option("--component", "-c", help="Component, for a component layer", autocompletion=complete_component),
    ] = None,
    deployment: Annotated[
        str | None,
        typer.Option("--deployment", help="Deployment, for a deployment layer", autocompletion=complete_deployment),
    ] = None,
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be sent without making the API call"),
) -> None:
    """Remove a service's configuration at one layer.

    [bold]Example:[/bold]

        $ zad service config clear publish-on-web --component web
    """
    entry, layer = _resolve_layer(ctx, service_name, target)
    project = require_project(ctx)
    path = _endpoint(entry, layer, project, component, deployment)
    client, formatter = get_helpers(ctx)

    if dry_run:
        render_dry_run(formatter, "DELETE", path)
        return

    confirm_action(f"Clear {entry.name} config at layer '{layer}' in project '{project}'?", yes, ctx)

    result = client.delete_service_config(path)
    formatter.render(result)
    formatter.render_success(f"Service '{entry.name}' config cleared at layer '{layer}'.")
    surface_warnings(ctx, formatter, result)
