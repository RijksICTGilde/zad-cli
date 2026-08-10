"""Key/value services: `zad env` (user-env-vars) and `zad alias` (aliases).

These two services own *values*, not config: the catalog lists them under
``value_targets`` rather than ``targets``, and the API gives each layer four endpoints
with four different meanings. None of them is a synonym for another, so each gets its own
verb here:

===========  ==============================  ==========================================
Verb         Endpoint                        Meaning
===========  ==============================  ==========================================
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


def extract_values(payload: Any, *, component: str, deployment: str | None) -> dict[str, str] | None:
    """Find one layer's key/value map inside the service's config document.

    The document nests values under the component, and under the deployment as well for
    the deployment-component layer. This walks it and picks the branch whose path matches
    what was asked for, so a shape change upstream degrades to "show the whole document"
    instead of showing the wrong layer's values.
    """
    candidates: list[tuple[tuple[str, ...], dict[str, str]]] = []

    def walk(node: Any, path: tuple[str, ...]) -> None:
        if not isinstance(node, dict):
            if isinstance(node, list):
                for item in node:
                    walk(item, path)
            return
        if node and all(isinstance(v, str) for v in node.values()) and component in path:
            candidates.append((path, {str(k): v for k, v in node.items()}))
            return
        for key, value in node.items():
            walk(value, (*path, str(key)))

    walk(payload, ())
    if not candidates:
        return None
    if deployment:
        matching = [values for path, values in candidates if deployment in path]
        return matching[0] if matching else None
    # Without a deployment, prefer the branch that mentions no deployment name at all.
    plain = [values for path, values in candidates if "deployment" not in " ".join(path).lower()]
    return (plain or [values for _, values in candidates])[0]


def build_app(service_name: str, *, noun: str, help_text: str) -> typer.Typer:
    """Build the command group for one key/value service."""
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

    @app.command("list")
    @handle_api_errors
    def list_values(
        ctx: typer.Context,
        component: str = component_option(),
        deployment: str = deployment_option(),
    ) -> None:
        """List the values set on a component."""
        entry = require_service(ctx, service_name)
        project = require_project(ctx)
        client, formatter = get_helpers(ctx)

        document = client.get_service_config(project, entry.name)
        values = extract_values(document, component=component, deployment=deployment)
        if values is None:
            # Better to show the whole document than to claim there is nothing.
            formatter.render_document(document)
            return
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
        """Print one value. Prints nothing and exits 1 when the key is not set."""
        entry = require_service(ctx, service_name)
        project = require_project(ctx)
        client, formatter = get_helpers(ctx)

        document = client.get_service_config(project, entry.name)
        values = extract_values(document, component=component, deployment=deployment) or {}
        if key not in values:
            typer.echo(f"Error: '{key}' is not set on component '{component}'.", err=True)
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
        confirm_action(f"Add {len(values)} {noun}(s) to component '{component}'?", yes, ctx)

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
        confirm_action(f"Change {len(values)} {noun}(s) on component '{component}'?", yes, ctx)

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
    help_text=(
        "Manage a component's own environment variables.\n\n"
        "A value set on a deployment is more specific than the component-wide one and "
        "overrides it."
    ),
)

alias_app = build_app(
    "aliases",
    noun="alias",
    help_text=(
        "Bind platform variables to the names a component expects "
        "(for example POSTGRES_HOST=$DATABASE_SERVER_HOST).\n\n"
        "Unlike your own environment variables, a reference to something that does not "
        "exist is a hard error here, not a value that is simply passed through."
    ),
)
