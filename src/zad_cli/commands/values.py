"""Key/value services: `zad env` (user-env-vars) and `zad alias` (aliases).

These two services own *values*, not config: the catalog lists them under
``value_targets`` rather than ``targets``, and the API gives each layer four endpoints
with four different meanings. None of them is a synonym for another, so each gets its own
verb here:

===========  ==============================  ==========================================
Verb         Endpoint                        Meaning
===========  ==============================  ==========================================
``list``     ``GET .../values/...``          read this layer; secrets come back as ``***``
``add``      ``POST .../values/...``         add entries; an existing key is a conflict
``set``      ``PATCH .../values/...``        change entries that already exist
``unset``    ``DELETE .../values/.../{key}`` remove one, or ``POST .../:delete`` for several
``clear``    ``DELETE .../values/...``       remove every entry at this layer
===========  ==============================  ==========================================

The two command groups are the same code with a different service bound to it; a third
key/value service upstream costs one line.
"""

from __future__ import annotations

from typing import Annotated, Any

import typer

from zad_cli.api.errors import Diagnosis, Fault
from zad_cli.helpers import (
    complete_component,
    complete_deployment,
    confirm_action,
    get_helpers,
    handle_api_errors,
    render_dry_run,
    require_project,
    require_service,
    surface_warnings,
)
from zad_cli.manifest import ManifestError, load_payload_file, resolve_value_reference

# Values live on a component, or on a component within one deployment. The deployment
# variant is the more specific of the two and overrides the component-wide value.
COMPONENT_LAYER = "component"
DEPLOYMENT_LAYER = "deployment-component"


def parse_pairs(pairs: list[str]) -> dict[str, str]:
    """Turn ``KEY=VALUE`` arguments into a map, expanding ``@file`` values."""
    values: dict[str, str] = {}
    for pair in pairs:
        if "=" not in pair:
            raise ManifestError(f"Expected KEY=VALUE, got '{pair}'.")
        key, raw = pair.split("=", 1)
        key = key.strip()
        if not key:
            raise ManifestError(f"Empty key in '{pair}'.")
        values[key] = resolve_value_reference(raw)
    return values


def read_env_file(path: str) -> dict[str, str]:
    """Read a dotenv-style file: ``KEY=VALUE`` per line, ``#`` comments, blanks ignored."""
    from pathlib import Path

    file_path = Path(path).expanduser()
    if not file_path.exists():
        raise ManifestError(f"File not found: {file_path}")
    values: dict[str, str] = {}
    for number, line in enumerate(file_path.read_text().splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            raise ManifestError(f"{file_path}:{number}: expected KEY=VALUE, got '{stripped}'.")
        key, raw = stripped.split("=", 1)
        value = raw.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def collect_values(pairs: list[str] | None, env_file: str | None, from_file: str | None) -> dict[str, str]:
    """Merge every source of values, most specific last."""
    values: dict[str, str] = {}
    if env_file:
        values.update(read_env_file(env_file))
    if from_file:
        loaded = load_payload_file(from_file)
        if not isinstance(loaded, dict):
            raise ManifestError(f"{from_file} must contain a mapping of keys to values.")
        values.update({str(k): str(v) for k, v in loaded.items()})
    if pairs:
        values.update(parse_pairs(pairs))
    if not values:
        raise ManifestError("Nothing to send: pass KEY=VALUE, --env-file, or --from-file.")
    return values


# What a value looks like when the API withheld it, and what to say instead. Rendering
# "***" as the value would claim the value is literally three asterisks.
WITHHELD = "***"
WITHHELD_LABEL = "(set, not shown)"
# A name the API will name but whose value it has no endpoint to return.
UNREADABLE_LABEL = "(set, no read endpoint)"


def values_from_components(document: Any, *, component: str, field: str) -> dict[str, str] | None:
    """One component's values as the *components* endpoint carries them.

    Only for an API whose values endpoints have no ``GET`` yet — they gained one on
    2026-08-11. Until then the component definition was the only place that named what is
    set, so it stays the read path of last resort. It carries either a list of names
    (values withheld) or a name-to-value map, so both shapes map onto the same answer.

    Returns ``None`` when the component is not in the document at all, which is a
    different answer from "this component has nothing set".
    """
    components = document.get("components") if isinstance(document, dict) else None
    if isinstance(components, dict):
        found = components.get(component)
    elif isinstance(components, list):
        found = next((c for c in components if isinstance(c, dict) and c.get("name") == component), None)
    else:
        return None
    if not isinstance(found, dict) or field not in found:
        return None

    entries = found.get(field)
    if entries is None:
        # The API is explicit that null means it could not read them, not that there are none.
        return None
    if isinstance(entries, dict):
        return {str(k): (WITHHELD_LABEL if v == WITHHELD else str(v)) for k, v in entries.items()}
    if isinstance(entries, list):
        return {str(name): UNREADABLE_LABEL for name in entries}
    return None


def build_app(service_name: str, *, noun: str, help_text: str, names_field: str) -> typer.Typer:
    """Build the command group for one key/value service.

    ``names_field`` is the field of a component definition that carries this service's
    values, used as the read path against an API whose values endpoint has no ``GET``.
    """
    app = typer.Typer(
        help=f"{help_text}\n\nRequires ZAD_API_KEY and ZAD_PROJECT_ID (or --api-key and -p).",
        no_args_is_help=True,
    )

    def component_option() -> Any:
        """A fresh OptionInfo per command: Typer must not share one between commands."""
        return typer.Option(
            ..., "--component", "-c", help="Component the values belong to", autocompletion=complete_component
        )

    def deployment_option() -> Any:
        return typer.Option(
            None,
            "--deployment",
            help="Deployment, for a value that applies only there (overrides the component-wide value)",
            autocompletion=complete_deployment,
        )

    def _path(ctx: typer.Context, component: str, deployment: str | None) -> str:
        """Concrete values endpoint for this service and layer."""
        from zad_cli.api.registry import MissingLayerError

        entry = require_service(ctx, service_name)
        layer = DEPLOYMENT_LAYER if deployment else COMPONENT_LAYER
        project = require_project(ctx)
        try:
            path = entry.values_endpoint(layer, component=component, deployment=deployment)
        except MissingLayerError as e:
            raise typer.BadParameter(str(e)) from e
        return path.replace("{project}", project)

    def _read_values(ctx: typer.Context, component: str, deployment: str | None) -> tuple[dict[str, str] | None, str]:
        """This layer's values, and where they were read from.

        The values endpoint itself is the answer: it reads the project file and returns
        this exact layer, so it is right for ``deployment-component`` too. An API that
        does not offer that GET yet answers 405, and then the component definition is the
        only thing that still names what is set — a name without its value beats an empty
        list, which would claim nothing is set.

        The second element says *which* of those happened, because they need different
        explanations: ``api`` and ``components`` carry values, and ``no-values-field``,
        ``no-read-path-deployment`` and ``no-read-path`` are the three distinct ways of
        having none to show.
        """
        from zad_cli.api.client import ZadApiError

        project = require_project(ctx)
        client, _ = get_helpers(ctx)
        path = _path(ctx, component, deployment)

        try:
            document = client.read_service_values(path)
        except ZadApiError as e:
            if e.status_code != 405:
                raise
        else:
            values = document.get("values") if isinstance(document, dict) else None
            if isinstance(values, dict):
                return {str(k): (WITHHELD_LABEL if v == WITHHELD else str(v)) for k, v in values.items()}, "api"
            # The GET exists and answered, but not with a values map. That is an answer we
            # cannot read, not a missing endpoint.
            return None, "no-values-field"

        if deployment:
            # The component definition is component-wide. Showing it here would answer a
            # question about one deployment with values that apply to all of them.
            return None, "no-read-path-deployment"
        components = client.project_components(project)
        fallback = values_from_components(components, component=component, field=names_field)
        if fallback is None:
            return None, "no-read-path"
        return fallback, "components"

    def _unreadable(component: str, deployment: str | None, reason: str, *, key: str | None = None) -> Diagnosis:
        """Why this layer could not be read, in the words of what actually happened."""
        unknown = f" Whether '{key}' is set is therefore unknown." if key else ""
        where = f"component '{component}'" + (f" in deployment '{deployment}'" if deployment else "")
        endpoint = f"GET {_endpoint_shape(deployment)}"
        if reason == "no-values-field":
            return Diagnosis(
                fault=Fault.PLATFORM,
                headline=f"Cannot read the {noun}s of {where}.",
                summary=(
                    f"{endpoint} answered, but without a 'values' field. This does not mean none are set.{unknown}"
                ),
                next_steps=[
                    "Retry with --verbose to see what the API returned.",
                    "Report the response to the platform team if it keeps this shape.",
                ],
            )
        if reason == "no-read-path-deployment":
            return Diagnosis(
                fault=Fault.PLATFORM,
                headline=f"Cannot read the {noun}s of {where}.",
                summary=(
                    f"This API has no {endpoint}, and the component definition is component-wide, "
                    f"so it cannot answer a question about one deployment. "
                    f"This does not mean none are set.{unknown}"
                ),
                next_steps=["Read the component-wide values instead: drop --deployment."],
            )
        return Diagnosis(
            fault=Fault.PLATFORM,
            headline=f"Cannot read the {noun}s of {where}.",
            summary=(
                f"This API has no {endpoint}, and the component definition does not name them "
                f"either. This does not mean none are set.{unknown}"
            ),
            next_steps=["Check the component exists: zad component list."],
        )

    def _endpoint_shape(deployment: str | None) -> str:
        """The values path of the layer being read, without the concrete names in it."""
        return ".../values/" + (DEPLOYMENT_LAYER if deployment else COMPONENT_LAYER)

    @app.command("list")
    @handle_api_errors
    def list_values(
        ctx: typer.Context,
        component: str = component_option(),
        deployment: str = deployment_option(),
    ) -> None:
        """List the values set on a component.

        Read from this layer's values endpoint, so a `--deployment` override is answered
        by the deployment layer and not by the component-wide values. A value the API
        withholds is shown as set-but-not-shown rather than left out.
        """
        entry = require_service(ctx, service_name)
        _, formatter = get_helpers(ctx)
        values, source = _read_values(ctx, component, deployment)

        if values is None:
            diagnosis = _unreadable(component, deployment, source)
            formatter.render_diagnosis(diagnosis)
            raise typer.Exit(diagnosis.exit_code)

        if source == "components":
            formatter.render_warning_text(
                f"Read from the component definition: this API has no GET on the {noun} values "
                f"endpoint, so only what it names is shown."
            )
        if formatter.fmt in ("json", "yaml"):
            formatter.render_document(values)
            return
        formatter.render(
            [{"key": k, "value": v} for k, v in sorted(values.items())],
            columns=["key", "value"],
            title=f"{entry.name} on {component}" + (f" ({deployment})" if deployment else ""),
        )

    @app.command("get")
    @handle_api_errors
    def get_value(
        ctx: typer.Context,
        key: str = typer.Argument(help="Key to read"),
        component: str = component_option(),
        deployment: str = deployment_option(),
    ) -> None:
        """Print one value. Prints nothing and exits 1 when the key is not set.

        "Not set" and "set but not readable" are different answers and are reported as
        such: a value the API withholds is not a value it does not have.
        """
        _, formatter = get_helpers(ctx)
        values, source = _read_values(ctx, component, deployment)

        if values is None:
            diagnosis = _unreadable(component, deployment, source, key=key)
            formatter.render_diagnosis(diagnosis)
            raise typer.Exit(diagnosis.exit_code)
        if key not in values:
            typer.echo(f"Error: '{key}' is not set on component '{component}'.", err=True)
            raise typer.Exit(1)
        if source == "components":
            formatter.render_warning_text(
                f"'{key}' is set, but this API has no GET on the {noun} values endpoint, so its value cannot be shown."
            )
            raise typer.Exit(1)
        if formatter.fmt in ("json", "yaml"):
            formatter.render_document({key: values[key]})
        else:
            formatter.render_text(values[key])

    @app.command("add")
    @handle_api_errors
    def add_values(
        ctx: typer.Context,
        pairs: Annotated[list[str] | None, typer.Argument(help="KEY=VALUE, repeatable")] = None,
        component: str = component_option(),
        deployment: str = deployment_option(),
        env_file: str = typer.Option(None, "--env-file", help="Read KEY=VALUE lines from a dotenv-style file"),
        from_file: str = typer.Option(None, "--from-file", "-f", help="Read a YAML/JSON mapping ('-' for stdin)"),
        yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
        dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be sent without making the API call"),
    ) -> None:
        """Add values that do not exist yet.

        A key that is already set is a conflict, not an overwrite; use `set` to change one.
        """
        values = collect_values(pairs, env_file, from_file)
        path = _path(ctx, component, deployment)
        client, formatter = get_helpers(ctx)

        if dry_run:
            render_dry_run(formatter, "POST", path, {"values": values})
            return
        result = client.add_service_values(path, values)
        formatter.render(result)
        formatter.render_success(f"Added {len(values)} {noun}(s) to '{component}'.")
        surface_warnings(ctx, formatter, result)

    @app.command("set")
    @handle_api_errors
    def set_values(
        ctx: typer.Context,
        pairs: Annotated[list[str] | None, typer.Argument(help="KEY=VALUE, repeatable")] = None,
        component: str = component_option(),
        deployment: str = deployment_option(),
        env_file: str = typer.Option(None, "--env-file", help="Read KEY=VALUE lines from a dotenv-style file"),
        from_file: str = typer.Option(None, "--from-file", "-f", help="Read a YAML/JSON mapping ('-' for stdin)"),
        yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
        dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be sent without making the API call"),
    ) -> None:
        """Change values that already exist.

        A key that is not set yet is an error, not a create; use `add` for a new one.
        """
        values = collect_values(pairs, env_file, from_file)
        path = _path(ctx, component, deployment)
        client, formatter = get_helpers(ctx)

        if dry_run:
            render_dry_run(formatter, "PATCH", path, {"values": values})
            return
        result = client.change_service_values(path, values)
        formatter.render(result)
        formatter.render_success(f"Changed {len(values)} {noun}(s) on '{component}'.")
        surface_warnings(ctx, formatter, result)

    @app.command("unset")
    @handle_api_errors
    def unset_values(
        ctx: typer.Context,
        keys: Annotated[list[str], typer.Argument(help="Key(s) to remove")],
        component: str = component_option(),
        deployment: str = deployment_option(),
        yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
        dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be sent without making the API call"),
    ) -> None:
        """Remove one or more values."""
        path = _path(ctx, component, deployment)
        client, formatter = get_helpers(ctx)
        single = len(keys) == 1

        if dry_run:
            if single:
                render_dry_run(formatter, "DELETE", f"{path}/{keys[0]}")
            else:
                render_dry_run(formatter, "POST", f"{path}/:delete", {"keys": keys})
            return
        confirm_action(f"Remove {', '.join(keys)} from component '{component}'?", yes, ctx)

        result = client.remove_service_value(path, keys[0]) if single else client.remove_service_values(path, keys)
        formatter.render(result)
        formatter.render_success(f"Removed {len(keys)} {noun}(s) from '{component}'.")
        surface_warnings(ctx, formatter, result)

    @app.command("clear")
    @handle_api_errors
    def clear_values(
        ctx: typer.Context,
        component: str = component_option(),
        deployment: str = deployment_option(),
        yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
        dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be sent without making the API call"),
    ) -> None:
        """Remove every value at this layer."""
        path = _path(ctx, component, deployment)
        client, formatter = get_helpers(ctx)

        if dry_run:
            render_dry_run(formatter, "DELETE", path)
            return
        confirm_action(f"Remove every {noun} from component '{component}'?", yes, ctx)

        result = client.clear_service_values(path)
        formatter.render(result)
        formatter.render_success(f"Cleared all {noun}s on '{component}'.")
        surface_warnings(ctx, formatter, result)

    return app


env_app = build_app(
    "user-env-vars",
    noun="variable",
    names_field="env_var_names",
    help_text=(
        "Manage a component's own environment variables.\n\n"
        "A value set on a deployment is more specific than the component-wide one and "
        "overrides it.\n\n"
        "add and set look only at the layer you address. The deployment layer is its own "
        "store, so the first override there is add, even when the name already exists "
        "component-wide; set on a layer that does not have it yet fails."
    ),
)

alias_app = build_app(
    "aliases",
    noun="alias",
    names_field="aliases",
    help_text=(
        "Bind platform variables to the names a component expects "
        "(for example POSTGRES_HOST=$DATABASE_SERVER_HOST).\n\n"
        "Unlike your own environment variables, a reference to something that does not "
        "exist is a hard error here, not a value that is simply passed through."
    ),
)
