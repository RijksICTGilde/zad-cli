"""Volumes on a component: `zadctl service persistent-storage` and `service temp-storage`.

These two services carry a *list of entries* rather than a config document, the same shape
as `attachments`. That is why they get their own verbs: "add a volume called data2" is not
expressible as "set this document", and the generic setter writes the block whole -- so
naming one volume used to remove the other, and for persistent storage removing a volume
prunes its PVC and the data on it.

The API grew a per-entry PATCH for exactly this (question 18 in RIG-Cluster's
`plans/vragen-uit-zad-cli.md`), so `add` and `delete` touch one entry and leave the rest
alone. `set` remains for writing the whole list on purpose.

**No top-level alias.** `zadctl attachment`, `zadctl env` and `zadctl alias` sit at the root
because they got there first; the entry point is `zadctl service <name>`, and the root does
not grow a keyword per service. `zadctl service list` is the index.

One factory, two services: a third list-shaped storage service upstream costs one line.
"""

from __future__ import annotations

from typing import Annotated, Any

import typer

from zad_cli.helpers import (
    complete_component,
    confirm_action,
    get_helpers,
    handle_api_errors,
    render_dry_run,
    require_project,
    require_service,
    surface_warnings,
)

# The field that identifies one entry. Named by the API in the PATCH body's description
# ("Keys ('name') of entries to remove"), and the same for both storage services.
KEY_FIELD = "name"


def _endpoint(ctx: typer.Context, service: str, component: str) -> tuple[str, Any]:
    """The component-layer config path for this service, with the project filled in."""
    from zad_cli.commands.service import _endpoint as resolve

    entry = require_service(ctx, service)
    project = require_project(ctx)
    return resolve(entry, "component", project, component, None), entry


def _entries(document: Any, component: str) -> list[dict[str, Any]]:
    """The entries this component has, out of the config document across layers."""
    if not isinstance(document, dict):
        return []
    for configuration in document.get("configurations") or []:
        if not isinstance(configuration, dict) or configuration.get("component") != component:
            continue
        found = configuration.get("config")
        if isinstance(found, list):
            return [item for item in found if isinstance(item, dict)]
    return []


def build(service: str, noun: str, example_mount: str = "/data") -> typer.Typer:
    """One command group for one list-shaped storage service."""
    app = typer.Typer(
        help=(
            f"Manage the {noun} of a component ({service}).\n\n"
            "Requires ZAD_API_KEY and ZAD_PROJECT_ID (or --api-key and -p)."
        ),
        no_args_is_help=True,
    )

    component_option = typer.Option(
        ..., "--component", "-c", help="Component the volume belongs to", autocompletion=complete_component
    )

    @app.command("list")
    @handle_api_errors
    def list_entries(ctx: typer.Context, component: str = component_option) -> None:
        """List this component's volumes.

        [bold]Example:[/bold]

            $ zadctl service persistent-storage list -c backend
        """
        project = require_project(ctx)
        entry = require_service(ctx, service)
        client, formatter = get_helpers(ctx)

        rows = _entries(client.get_service_config(project, entry.name), component)
        formatter.render(rows, columns=[KEY_FIELD, "size", "mount-path"])

    @app.command()
    @handle_api_errors
    def add(
        ctx: typer.Context,
        name: Annotated[str, typer.Argument(help="Name of this volume within the component")],
        component: str = component_option,
        size: str = typer.Option(..., "--size", help="Size as a Kubernetes quantity, e.g. 1Gi"),
        mount_path: str = typer.Option(..., "--mount-path", help="Absolute path in the container"),
        dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be sent without making the API call"),
    ) -> None:
        """Give a component a volume, without touching the ones it already has.

        A name that already exists is replaced rather than duplicated, so this is also how
        you resize one. Everything not named here stays as it is -- unlike
        `service config set`, which writes the whole list.

        [bold]--mount-path[/bold], not `--path`: `--path` means *ingress path* elsewhere in
        this CLI.

        [bold]Example:[/bold]

            $ zadctl service persistent-storage add data -c backend --size 1Gi --mount-path /data
        """
        path, _ = _endpoint(ctx, service, component)
        client, formatter = get_helpers(ctx)
        payload = {"add": [{KEY_FIELD: name, "size": size, "mount-path": mount_path}]}

        if dry_run:
            render_dry_run(formatter, "PATCH", path, payload)
            return

        result = client.patch_service_config(path, payload)
        formatter.render(result)
        formatter.render_success(f"Volume '{name}' on '{component}' is {size} at {mount_path}.")
        surface_warnings(ctx, formatter, result)

    @app.command()
    @handle_api_errors
    def delete(
        ctx: typer.Context,
        name: Annotated[str, typer.Argument(help="Name of the volume to delete")],
        component: str = component_option,
        yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
        dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be sent without making the API call"),
    ) -> None:
        """Delete one volume from a component, leaving its other volumes alone.

        [bold]Not `unassign`, and the difference matters.[/bold] Unassigning takes a binding
        away and leaves the thing itself: `attachment unassign` keeps the file in the
        project's catalog, `service unassign` keeps the service on the project. A volume has
        no such second home -- it exists only as this entry, so taking the entry away is
        deleting it. RIG-Cluster measured what follows: the mount leaves the list, ArgoCD
        prunes the PVC, and their own code says that prunes "the PVC and its data
        immediately". On temp storage there is nothing to lose; the volume was ephemeral.

        [bold]Example:[/bold]

            $ zadctl service persistent-storage delete data -c backend
        """
        path, _ = _endpoint(ctx, service, component)
        client, formatter = get_helpers(ctx)
        payload = {"remove": [name]}

        if dry_run:
            render_dry_run(formatter, "PATCH", path, payload)
            return

        confirm_action(
            f"Delete volume '{name}' from component '{component}'? "
            f"On persistent storage this prunes the volume and the data on it.",
            yes,
            ctx,
        )

        result = client.patch_service_config(path, payload)
        formatter.render(result)
        formatter.render_success(f"Volume '{name}' deleted from '{component}'.")
        surface_warnings(ctx, formatter, result)

    # The examples are written out once and belong to whichever service this group was
    # built for. Left alone they said `persistent-storage` in both of them, so
    # `zadctl service temp-storage add --help` offered a line that configures the other
    # service -- and `service describe temp-storage`, which now reads its examples out of
    # these docstrings, would have repeated it. Typer reads a docstring when the CLI is
    # invoked rather than at decoration, so rewriting it here still lands.
    # The mount path travels with them. `/data` is where a persistent volume goes and
    # `/tmp` is where an ephemeral one goes -- the registry says so per service -- so an
    # example that names the wrong one is an example that teaches the wrong habit.
    for func in (list_entries, add, delete):
        func.__doc__ = (func.__doc__ or "").replace("persistent-storage", service).replace("/data", example_mount)

    return app


persistent_app = build("persistent-storage", "persistent volumes")
temp_app = build("temp-storage", "ephemeral volumes", example_mount="/tmp")
