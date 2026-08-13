"""Attachment commands: files a project owns, and how components receive them.

The API keeps these two apart and so does this group:

* the **catalog** is project-level: a file exists in the project and is used by nothing
  until something references it (`add`, `update`, `delete`, `list`);
* the **coupling** is component-level: which catalog entry a component uses, and how it
  reaches the pod (`assign`).

``--mount-path`` belongs to the coupling, not to the file: the same certificate can land
on a different path per deployment. ``--path`` already means *ingress path* elsewhere in
this CLI, which is why the flag is spelled out.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

import typer

from zad_cli.helpers import (
    complete_component,
    confirm_action,
    get_helpers,
    handle_api_errors,
    one_name,
    render_dry_run,
    require_project,
    require_service,
    surface_warnings,
)

# The API encrypts and stores each attachment inline; it rejects anything larger.
MAX_ATTACHMENT_BYTES = 64 * 1024

SERVICE = "attachments"

app = typer.Typer(
    help=(
        "Manage the project's attachments: files a component receives as a mounted file "
        "or as an environment variable.\n\n"
        "Requires ZAD_API_KEY and ZAD_PROJECT_ID (or --api-key and -p)."
    ),
    no_args_is_help=True,
)


def read_attachment(source: str) -> tuple[str, bytes]:
    """Read an attachment's bytes; ``-`` reads stdin. Returns (filename, content)."""
    import sys

    if source == "-":
        content = sys.stdin.buffer.read()
        name = "stdin"
    else:
        path = Path(source).expanduser()
        if not path.exists():
            raise typer.BadParameter(f"File not found: {path}")
        content = path.read_bytes()
        name = path.name
    if len(content) > MAX_ATTACHMENT_BYTES:
        raise typer.BadParameter(
            f"{name} is {len(content)} bytes; the API accepts at most {MAX_ATTACHMENT_BYTES} (64 KB)."
        )
    if not content:
        raise typer.BadParameter(f"{name} is empty.")
    return name, content


def _coupling(provide_as: str, mount_path: str | None, env_name: str | None) -> dict[str, str]:
    """Validate and build the fields that say how the component receives the file."""
    if provide_as not in ("file", "env-var"):
        raise typer.BadParameter("--provide-as must be 'file' or 'env-var'.")
    if provide_as == "file":
        if not mount_path:
            raise typer.BadParameter("--mount-path is required when --provide-as is 'file'.")
        return {"provide-as": "file", "path": mount_path}
    if not env_name:
        raise typer.BadParameter("--env-name is required when --provide-as is 'env-var'.")
    return {"provide-as": "env-var", "env-name": env_name}


def _base(ctx: typer.Context) -> tuple[str, Any]:
    """Project name and the attachments service entry, validated against the catalog."""
    entry = require_service(ctx, SERVICE)
    return require_project(ctx), entry


@app.command("list")
@handle_api_errors
def list_attachments(
    ctx: typer.Context,
    component_arg: Annotated[
        str | None,
        typer.Argument(
            metavar="[component]",
            help="Only show what this component uses; same as --component",
            autocompletion=complete_component,
        ),
    ] = None,
    component: Annotated[
        str | None,
        typer.Option("--component", "-c", help="Only show what this component uses", autocompletion=complete_component),
    ] = None,
) -> None:
    """List the project's attachments, or what one component uses.

    The component may be given either way. `add` and `assign` take it as a
    positional argument, so refusing it here was a difference with no reason
    behind it, and one you only find out about after typing.

    [bold]Examples:[/bold]

        $ zad attachment list

        $ zad attachment list web
    """
    # Not `one_name`: giving neither is the ordinary case here, and means "everything".
    # Giving both is only a mistake when they disagree.
    if component_arg and component and component_arg != component:
        raise typer.BadParameter(f"Two different components given: '{component_arg}' and '{component}'.")
    component = component or component_arg
    project, entry = _base(ctx)
    client, formatter = get_helpers(ctx)

    document = client.get_service_config(project, entry.name)
    rows = _flatten(document, component)
    if rows is None:
        # The catalogue, not the document. Falling back to the whole thing printed every
        # file's AGE-encrypted contents down the terminal: pages of ciphertext in place of
        # an answer, and a secret on screen for no gain even though it cannot be read.
        catalogue = _catalogue(document)
        if catalogue:
            formatter.render(catalogue, columns=["id", "filename", "size"])
            return
        formatter.render_document(document)
        return
    if formatter.fmt in ("json", "yaml"):
        formatter.render_document(rows)
        return
    formatter.render(
        rows,
        columns=["component", "reference", "provide-as", "path", "env-name"],
    )


def _catalogue(document: Any) -> list[dict[str, Any]]:
    """The files a project has, by name and size, without their contents.

    What a reader wants from `attachment list` when nothing is coupled yet is which files
    exist. The contents are encrypted and enormous, so they are described rather than
    shown; `zad service config get attachments` still gives the raw document.
    """
    if not isinstance(document, dict):
        return []
    rows: list[dict[str, Any]] = []
    for configuration in document.get("configurations") or []:
        if not isinstance(configuration, dict):
            continue
        # `config` is a dict on the project layer, where the catalogue of files lives, and
        # a *list* on a component layer, where the couplings live. Assuming the first
        # shape crashed this command the moment a project had both, which is every project
        # that has ever used an attachment.
        config = configuration.get("config")
        if not isinstance(config, dict):
            continue
        for item in config.get("data") or []:
            if not isinstance(item, dict) or "id" not in item:
                continue
            content = item.get("content") or item.get("data") or ""
            rows.append(
                {
                    "id": item["id"],
                    "filename": item.get("filename") or "",
                    "size": f"{len(str(content))} bytes (encrypted)",
                }
            )
    return rows


def _flatten(document: Any, component: str | None) -> list[dict[str, Any]] | None:
    """One row per coupling: which component uses which file, and how it arrives.

    Reads the document's own structure rather than hunting for dictionaries that happen to
    carry a "reference" key. The generic walk it replaces looked one level into a list and
    returned, so every real coupling -- which lives at
    `configurations[].config[]` under a component -- was invisible, and the command fell
    back to printing the whole document: pages of encrypted content in place of the one
    line the reader asked for.

    Returns None when the document has no couplings at all, so the caller can say what the
    project *does* have instead of showing an empty table.
    """
    if not isinstance(document, dict):
        return None
    rows: list[dict[str, Any]] = []
    for configuration in document.get("configurations") or []:
        if not isinstance(configuration, dict):
            continue
        # The catalogue of files sits on the project layer as a dict; the couplings sit on
        # a component layer as a list. Only the second kind is a coupling.
        couplings = configuration.get("config")
        if not isinstance(couplings, list):
            continue
        owner = configuration.get("component") or ""
        for item in couplings:
            if not isinstance(item, dict) or "reference" not in item:
                continue
            rows.append(
                {
                    "component": owner,
                    "reference": item.get("reference", ""),
                    "provide-as": item.get("provide-as", ""),
                    "path": item.get("path") or "",
                    "env-name": item.get("env-name") or "",
                }
            )

    if not rows:
        return None
    if component:
        rows = [r for r in rows if r["component"] == component]
    return rows


@app.command()
@handle_api_errors
def add(
    ctx: typer.Context,
    attachment_id: str = typer.Argument(help="Id for this attachment within the project (e.g. server-cert)"),
    from_file: str = typer.Option(..., "--from-file", "-f", help="File to upload ('-' for stdin), at most 64 KB"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be sent without making the API call"),
) -> None:
    """Put a file in the project's catalog, without coupling it to anything yet.

    Use `attachment assign` afterwards to let a component use it.

    [bold]Example:[/bold]

        $ zad attachment add server-cert --from-file ./server.pem
    """
    project, _ = _base(ctx)
    filename, content = read_attachment(from_file)
    client, formatter = get_helpers(ctx)
    path = f"/v2/projects/{project}/services/attachments/attachment"

    if dry_run:
        render_dry_run(
            formatter, "POST", path, {"attachment_id": attachment_id, "file": f"{filename} ({len(content)} bytes)"}
        )
        return
    result = client.create_attachment(project, attachment_id, filename, content)
    formatter.render(result)
    formatter.render_success(f"Attachment '{attachment_id}' added.")
    surface_warnings(ctx, formatter, result)


@app.command()
@handle_api_errors
def update(
    ctx: typer.Context,
    attachment_id: str = typer.Argument(help="Id of the attachment to replace"),
    from_file: str = typer.Option(..., "--from-file", "-f", help="New content ('-' for stdin), at most 64 KB"),
    upsert: bool = typer.Option(False, "--upsert", help="Write the attachment even if it does not exist yet"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be sent without making the API call"),
) -> None:
    """Replace an attachment's content. Its couplings stay as they are.

    [bold]Example:[/bold]

        $ zad attachment update server-cert --from-file ./server.pem
    """
    project, _ = _base(ctx)
    filename, content = read_attachment(from_file)
    client, formatter = get_helpers(ctx)
    path = f"/v2/projects/{project}/services/attachments/attachment/{attachment_id}"

    if dry_run:
        render_dry_run(formatter, "PUT", path, {"file": f"{filename} ({len(content)} bytes)", "upsert": upsert})
        return
    result = client.update_attachment(project, attachment_id, filename, content, upsert=upsert)
    formatter.render(result)
    formatter.render_success(f"Attachment '{attachment_id}' updated.")
    surface_warnings(ctx, formatter, result)


@app.command()
@handle_api_errors
def assign(
    ctx: typer.Context,
    attachment_id: str = typer.Argument(help="Attachment id, existing in the catalog or created by --from-file"),
    component_arg: Annotated[
        str | None,
        typer.Argument(metavar="[component]", help="Component that uses it", autocompletion=complete_component),
    ] = None,
    component_opt: Annotated[
        str | None,
        typer.Option("--component", "-c", help="Same as the positional; every other command spells it this way"),
    ] = None,
    from_file: str = typer.Option(
        None, "--from-file", "-f", help="Upload this file under the id at the same time ('-' for stdin)"
    ),
    provide_as: str = typer.Option("file", "--provide-as", help="How the component receives it: file or env-var"),
    mount_path: str = typer.Option(None, "--mount-path", help="Absolute path to mount at, when --provide-as is file"),
    env_name: str = typer.Option(
        None, "--env-name", help="Variable to put the content in, when --provide-as is env-var"
    ),
    replace: bool = typer.Option(False, "--replace", help="Update an existing coupling instead of creating one"),
    upsert: bool = typer.Option(False, "--upsert", help="With --replace: write the coupling either way"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be sent without making the API call"),
) -> None:
    """Let a component use an attachment, and say how it reaches the pod.

    The mount path belongs here rather than to the file, so the same attachment can land
    somewhere else for another component. With --from-file the upload and the coupling
    happen in one call, which cannot half-succeed the way two calls can.

    [bold]Example:[/bold]

        $ zad attachment assign server-cert web --mount-path /etc/ssl/certs/server.pem
    """
    component = one_name(component_arg, component_opt, what="component name", flag="--component")
    project, _ = _base(ctx)
    coupling = _coupling(provide_as, mount_path, env_name)
    client, formatter = get_helpers(ctx)

    filename, content = read_attachment(from_file) if from_file else (None, None)
    base = f"/v2/projects/{project}/services/attachments/component/{component}/attachment"
    path = f"{base}/{attachment_id}" if replace else base
    method = "PUT" if replace else "POST"

    if dry_run:
        payload: dict[str, Any] = dict(coupling)
        if content is not None:
            payload["attachment_id"] = attachment_id
            payload["file"] = f"{filename} ({len(content)} bytes)"
        elif not replace:
            payload["reference"] = attachment_id
        render_dry_run(formatter, method, path, payload)
        return

    result = client.assign_attachment(
        project,
        component,
        attachment_id,
        coupling,
        filename=filename,
        content=content,
        replace=replace,
        upsert=upsert,
    )
    formatter.render(result)
    formatter.render_success(f"Attachment '{attachment_id}' assigned to '{component}'.")
    surface_warnings(ctx, formatter, result)


@app.command()
@handle_api_errors
def delete(
    ctx: typer.Context,
    attachment_id: str = typer.Argument(help="Attachment id to remove from the catalog"),
    confirm_in_use: bool = typer.Option(
        False, "--confirm-in-use", help="Delete even when a component still references it"
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be sent without making the API call"),
) -> None:
    """Remove an attachment from the project's catalog.

    [bold]Example:[/bold]

        $ zad attachment delete server-cert
    """
    project, _ = _base(ctx)
    client, formatter = get_helpers(ctx)
    path = f"/v2/projects/{project}/services/attachments/attachment/{attachment_id}"

    if dry_run:
        render_dry_run(formatter, "DELETE", path, {"confirm_in_use": confirm_in_use})
        return
    confirm_action(f"Delete attachment '{attachment_id}' from project '{project}'?", yes, ctx)

    result = client.delete_attachment(project, attachment_id, confirm_in_use=confirm_in_use)
    formatter.render(result)
    formatter.render_success(f"Attachment '{attachment_id}' deleted.")
    surface_warnings(ctx, formatter, result)
