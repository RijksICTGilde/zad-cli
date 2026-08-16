"""Deployment commands: list, url, describe, create, assign, update-image, refresh, delete."""

from __future__ import annotations

from typing import Annotated

import typer

from zad_cli.api.models import Component, DeploymentStatus, UpsertDeploymentRequest
from zad_cli.helpers import (
    complete_component,
    complete_deployment,
    confirm_action,
    get_helpers,
    handle_api_errors,
    issues_cell,
    one_name,
    render_dry_run,
    require_deployment,
    require_project,
    surface_warnings,
)

app = typer.Typer(
    help="Manage deployments.\n\nMost commands require ZAD_API_KEY and ZAD_PROJECT_ID (or --api-key and -p).",
    no_args_is_help=True,
)


@app.command("list")
@handle_api_errors
def list_deployments(ctx: typer.Context) -> None:
    """List all deployments in a project.

    [bold]Example:[/bold]

        $ zadctl deployment list
    """
    project = require_project(ctx)
    client, formatter = get_helpers(ctx)

    deployments = client.list_deployments(project)

    if formatter.fmt in ("json", "yaml"):
        formatter.render(deployments)
        return

    rows = []
    for dep in deployments:
        status = dep.get("status", "Active")
        rows.append(
            {
                "deployment": dep["deployment"],
                "components": str(len(dep["components"])),
                "status": status_cell(status),
                "issues": issues_cell(dep.get("errors")),
                "namespace": dep["namespace"],
            }
        )

    formatter.render(
        rows,
        columns=["deployment", "components", "status", "issues", "namespace"],
    )


_STATUS_COLORS: dict[DeploymentStatus, str] = {
    DeploymentStatus.HEALTHY: "green",
    DeploymentStatus.DEGRADED: "red",
    DeploymentStatus.MISSING: "red",
    DeploymentStatus.OUT_OF_SYNC: "red",
    DeploymentStatus.SUSPENDED: "red",
    DeploymentStatus.PROGRESSING: "yellow",
    DeploymentStatus.PENDING: "yellow",
}


def _status_color(status: str) -> str:
    """Color for a DeploymentStatus enum value."""
    return _STATUS_COLORS.get(status, "dim")


def status_cell(status: object) -> str:
    """A deployment status, coloured the same way wherever it is shown."""
    text = str(status or "-")
    color = _status_color(text)
    return f"[{color}]{text}[/{color}]"


@app.command()
@handle_api_errors
def url(
    ctx: typer.Context,
    deployment: str = typer.Argument(help="Deployment name", autocompletion=complete_deployment),
    component: str = typer.Option(
        None, "--component", "-c", help="One component; omit for all of them", autocompletion=complete_component
    ),
) -> None:
    """Print the public address of a component, and nothing else.

    For `URL=$(zadctl deployment url productie -c web)`. The addresses are in
    `deployment describe` too, but a script that wants one value should not
    have to know the shape of a document to get it: downstream tooling was
    reaching into a task result with `jq`, which is a shape this CLI never
    promised and which once carried an address for a component that had no
    ingress at all.

    An address exists as soon as the project file asks for one, so a component
    saved but not rolled out has a URL that nothing answers on yet. `zad
    deployment describe` says when that is the case.

    [bold]Examples:[/bold]

        $ zadctl deployment url productie -c web

        $ zadctl deployment url productie
    """
    project = require_project(ctx)
    client, formatter = get_helpers(ctx)

    urls = client.describe_deployment(project, deployment).get("urls") or {}

    if component:
        address = urls.get(component)
        if not address:
            raise typer.BadParameter(
                f"Component '{component}' has no address in deployment '{deployment}'. "
                f"With one: {', '.join(sorted(urls)) or 'none'}. "
                "A component gets an address from the publish-on-web service."
            )
        # Bare, so the shell can use it as-is. No table, no quotes, no trailing note.
        formatter.render_text(address)
        return

    if formatter.fmt in ("json", "yaml"):
        formatter.render(urls)
        return
    for name, address in sorted(urls.items()):
        formatter.render_text(f"{name}\t{address}")


@app.command()
@handle_api_errors
def describe(
    ctx: typer.Context,
    deployment: str = typer.Argument(None, help="Deployment name", autocompletion=complete_deployment),
    deployment_opt: str = typer.Option(
        None,
        "--name",
        help="Same value as the positional, spelled out; pass one of the two",
        autocompletion=complete_deployment,
    ),
) -> None:
    """Show detailed info about a deployment.

    [bold]Example:[/bold]

        $ zadctl deployment describe regelrecht
    """
    deployment = one_name(deployment, deployment_opt, what="deployment name")
    project = require_project(ctx)
    client, formatter = get_helpers(ctx)

    result = client.describe_deployment(project, deployment)

    if formatter.fmt in ("json", "yaml"):
        formatter.render(result)
        return

    console = formatter.console

    console.print(f"\n[bold]Deployment:[/bold] {result['deployment']}")
    console.print(f"[bold]Project:[/bold] {result['project']}")
    console.print(f"[bold]Namespace:[/bold] {result['namespace']}")

    color = _status_color(result["status"])
    console.print(f"[bold]Status:[/bold] [{color}]{result['status']}[/{color}]")
    if result["sync_revision"]:
        console.print(f"[bold]Revision:[/bold] {result['sync_revision'][:12]}")
    if result["last_synced_at"]:
        # Upstream documents this as the last sync attempt regardless of
        # outcome, so phrasing avoids implying a clean state.
        console.print(f"[bold]Last sync attempt:[/bold] {result['last_synced_at']}")

    # The count first, because it changes how everything under it should be read: these
    # URLs come from the project file, so a component saved but not rolled out already has
    # one while nothing answers on it. Saying that here saves the reader from concluding
    # the platform is broken when they get a 404.
    waiting = (result.get("pending_rollout") or {}).get("count") or 0
    if waiting:
        console.print(
            f"\n[yellow]{waiting} change(s) saved but not rolled out.[/yellow] "
            "Addresses below are what the project file asks for, not what is serving yet.\n"
            "  Roll them out with: [bold]zadctl project refresh[/bold]"
        )

    # Next to the count above, and for the same reason: `pending_rollout` says a change is
    # not on the cluster yet, an approval says the platform is waiting on a person. Either
    # way the address below is what was asked for and not what answers, and a deployment
    # that reads Healthy while its domain was refused is the case this exists for.
    from zad_cli.api.errors import approval_notices

    approvals = approval_notices(result)
    if approvals:
        console.print()
        formatter.render_approvals(approvals)

    if result["urls"]:
        console.print("\n[bold]URLs:[/bold]")
        for comp_name, url in result["urls"].items():
            console.print(f"  {comp_name}: {url}")

    console.print()

    # The coupling knows only name and image; the project's component definitions carry
    # everything else the reader asks here (ports, services, attachments). One extra call,
    # the same one `project describe` makes.
    try:
        definitions = {c.get("name", ""): c for c in client.project_components(project).get("components") or []}
    except Exception:  # noqa: BLE001 - the coupling alone is still a describe, just a thinner one
        definitions = {}

    def _detail(name: str) -> dict:
        return definitions.get(name) or {}

    rows = [
        {
            "name": comp["name"],
            "image": comp["image"],
            "ports": ", ".join(str(p) for p in (_detail(comp["name"]).get("ports") or {}).get("inbound") or []) or "-",
            "services": ", ".join(_detail(comp["name"]).get("services") or []) or "-",
            "attachments": ", ".join(a.get("reference", "") for a in _detail(comp["name"]).get("attachments") or [])
            or "-",
        }
        for comp in result["components"]
    ]
    formatter.render(rows, columns=["name", "image", "ports", "services", "attachments"], title="Components")

    errors = result["errors"]
    if errors:
        formatter.render(
            [{"category": e["category"], "resource": e["resource"], "message": e["message"]} for e in errors],
            columns=["category", "resource", "message"],
            title="Errors",
        )

        seen_explanations: set[str] = set()
        for err in errors:
            cat = err["category"]
            explanation = err.get("explanation")
            if explanation and cat not in seen_explanations:
                seen_explanations.add(cat)
                console.print(f"  [dim]{cat}: {explanation}[/dim]")


@app.command()
@handle_api_errors
def create(
    ctx: typer.Context,
    deployment_name: str = typer.Argument(None, help="Deployment name"),
    deployment_name_opt: str = typer.Option(
        None, "--name", help="Same value as the positional, spelled out; pass one of the two"
    ),
    component: str = typer.Option(None, "--component", "-c", help="Component reference"),
    image: str = typer.Option(None, "--image", help="Container image"),
    file: str = typer.Option(None, "--file", "-f", help="YAML/JSON manifest with the whole deployment ('-' for stdin)"),
    sets: Annotated[
        list[str] | None,
        typer.Option("--set", help="Set a field: dotted.path=value, repeatable. Wins over --file."),
    ] = None,
    generate_skeleton: bool = typer.Option(False, "--generate-skeleton", help="Print an example manifest and exit"),
    clone_from: str = typer.Option(None, "--clone-from", help="Clone config from existing deployment"),
    force_clone: bool = typer.Option(False, "--force-clone", help="Force clone"),
    domain_format: str = typer.Option(None, "--domain-format", help="Domain format template"),
    subdomain: str = typer.Option(None, "--subdomain", help="Custom subdomain"),
    base_domain: str = typer.Option(None, "--base-domain", help="Base domain"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be sent without making the API call"),
) -> None:
    """Create or update a deployment (upsert).

    This is an upsert operation: if the deployment already exists, it will be updated.
    It does not ask first -- only the commands that take something away do. `--yes` is
    still accepted so that scripts passing it keep working, and does nothing here.

    A deployment with more than one component is easier to keep in a manifest than on a
    command line; --set overrides individual fields on top of it, the way Helm does.

    [bold]Examples:[/bold]

        $ zadctl deployment create staging --component web --image ghcr.io/org/app:v1.2

        $ zadctl deployment create staging -f staging.yaml

        $ zadctl deployment create staging -f staging.yaml --set components[0].image=ghcr.io/org/app:v1.3

        $ zadctl deployment create pr-42 --component web --image ghcr.io/org/app:pr-42 --clone-from production
    """
    from zad_cli.manifest import apply_sets, load_payload_file

    formatter = ctx.obj["formatter"]

    if generate_skeleton:
        formatter.render_document(
            {
                "components": [{"name": "web", "image": "ghcr.io/org/app:v1.0"}],
                "clone_from": None,
                "domain_format": None,
                "subdomain": None,
                "base_domain": None,
            }
        )
        return

    # After the skeleton, not before: printing an example manifest needs no name.
    deployment_name = one_name(deployment_name, deployment_name_opt, what="deployment name")
    project = require_project(ctx)
    client, formatter = get_helpers(ctx)

    manifest: dict = {}
    if file:
        loaded = load_payload_file(file)
        if not isinstance(loaded, dict):
            raise typer.BadParameter(f"{file} must contain a mapping.")
        manifest = loaded
    if sets:
        manifest = apply_sets(manifest, sets)

    if component and image:
        comp_list = [Component(name=component, image=image)]
    elif manifest.get("components"):
        try:
            comp_list = [Component(name=c["name"], image=c["image"]) for c in manifest["components"]]
        except (KeyError, TypeError) as e:
            raise typer.BadParameter(f"Each component needs a name and an image: {e}") from e
    elif component or image:
        # One half of the pair is a slip, not a request for an empty deployment.
        raise typer.BadParameter(
            "--component and --image go together; pass both, or neither for a deployment that runs nothing yet."
        )
    else:
        # A deployment without components runs nothing yet. That is a valid state, and the
        # one you want while building the parts up separately; attach them afterwards with
        # `zadctl component assign`.
        comp_list = []

    # Flags win over the manifest, so a script can override one field of a shared file.
    request = UpsertDeploymentRequest(
        deployment_name=deployment_name,
        components=comp_list,
        clone_from=clone_from or manifest.get("clone_from"),
        force_clone=force_clone or bool(manifest.get("force_clone", False)),
        domain_format=domain_format or manifest.get("domain_format"),
        subdomain=subdomain or manifest.get("subdomain"),
        base_domain=base_domain or manifest.get("base_domain"),
    )

    if dry_run:
        render_dry_run(formatter, "POST", f"/v2/projects/{project}/:upsert-deployment", request.to_api_payload())
        return

    result = client.upsert_deployment(project, request.to_api_payload())
    formatter.render(result)
    formatter.render_success(f"Deployment '{deployment_name}' created/updated in project '{project}'.")
    surface_warnings(ctx, formatter, result)


@app.command()
@handle_api_errors
def assign(
    ctx: typer.Context,
    deployment: str = typer.Argument(None, help="Deployment to attach to", autocompletion=complete_deployment),
    deployment_opt: str = typer.Option(
        None,
        "--name",
        help="Same value as the first positional, spelled out; pass one of the two",
        autocompletion=complete_deployment,
    ),
    component: str = typer.Argument(None, help="Component to attach", autocompletion=complete_component),
    component_opt: str = typer.Option(
        None,
        "--component",
        "-c",
        help="Same value as the second positional, spelled out",
        autocompletion=complete_component,
    ),
    image: str = typer.Option(..., "--image", help="Container image URL for this deployment"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be sent without making the API call"),
) -> None:
    """Attach an existing component to this deployment.

    The same act as `zadctl component assign`, entered from the deployment instead of
    from the component -- which one reads better depends on what you are holding. The
    image lives on the attachment, so it is asked for here even though the component
    already exists.

    With two positionals the order is what fills them: deployment first, component
    second. Naming one with an option and leaving the other positional puts the
    positional in the other one's slot: pass both as options, or both as positionals.

    [bold]Examples:[/bold]

        $ zadctl deployment assign production web --image ghcr.io/org/app:v1

        $ zadctl deployment assign --name production --component web --image ghcr.io/org/app:v1
    """
    deployment = one_name(deployment, deployment_opt, what="deployment name")
    component = one_name(component, component_opt, what="component name", flag="--component")
    project = require_project(ctx)
    client, formatter = get_helpers(ctx)

    payload = {"component_name": component, "image": image}

    if dry_run:
        render_dry_run(formatter, "POST", f"/v2/projects/{project}/deployments/{deployment}/components", payload)
        return

    require_deployment(ctx, project, deployment)
    result = client.add_component_to_deployment(project, deployment, payload)
    formatter.render(result)
    formatter.render_success(f"Component '{component}' assigned to deployment '{deployment}'.")
    surface_warnings(ctx, formatter, result)


@app.command("update-image")
@handle_api_errors
def update_image(
    ctx: typer.Context,
    deployment: str = typer.Argument(None, help="Deployment name", autocompletion=complete_deployment),
    deployment_opt: str = typer.Option(
        None,
        "--name",
        help="Same value as the positional, spelled out; pass one of the two",
        autocompletion=complete_deployment,
    ),
    component: str = typer.Option(..., "--component", "-c", help="Component reference"),
    image: str = typer.Option(..., "--image", help="New container image"),
    recreate_storage: bool = typer.Option(False, "--recreate-storage", help="Recreate persistent storage"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be sent without making the API call"),
) -> None:
    """Update a deployment's container image.

    [bold]Examples:[/bold]

        $ zadctl deployment update-image staging --component web --image ghcr.io/org/app:v1.3

        $ zadctl deployment update-image staging --component web --image ghcr.io/org/app:v1.3 --recreate-storage
    """
    deployment = one_name(deployment, deployment_opt, what="deployment name")
    project = require_project(ctx)
    client, formatter = get_helpers(ctx)

    payload: dict = {"componentName": component, "newImageUrl": image}
    if recreate_storage:
        payload["services"] = {"persistent-storage": {"reference": {"data": {"action": "recreate"}}}}

    if dry_run:
        render_dry_run(formatter, "PUT", f"/v2/projects/{project}/deployments/{deployment}/image", payload)
        return

    kwargs: dict = {}
    if recreate_storage:
        kwargs["services"] = {"persistent-storage": {"reference": {"data": {"action": "recreate"}}}}

    result = client.update_image(project, deployment, component, image, **kwargs)
    formatter.render(result)
    formatter.render_success(f"Image updated: {component} -> {image}")
    surface_warnings(ctx, formatter, result)


@app.command()
@handle_api_errors
def refresh(
    ctx: typer.Context,
    deployment: str = typer.Argument(None, help="Deployment name", autocompletion=complete_deployment),
    deployment_opt: str = typer.Option(
        None,
        "--name",
        help="Same value as the positional, spelled out; pass one of the two",
        autocompletion=complete_deployment,
    ),
    force_clone: bool = typer.Option(False, "--force-clone", help="Force clone"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be sent without making the API call"),
) -> None:
    """Refresh a single deployment from git."""
    deployment = one_name(deployment, deployment_opt, what="deployment name")
    project = require_project(ctx)
    client, formatter = get_helpers(ctx)

    if dry_run:
        render_dry_run(
            formatter,
            "POST",
            f"/v2/projects/{project}/deployments/{deployment}/:refresh",
            {"force_clone": force_clone},
        )
        return

    result = client.refresh_deployment(project, deployment, force_clone=force_clone)
    formatter.render(result)
    formatter.render_success(f"Deployment '{deployment}' refreshed.")
    surface_warnings(ctx, formatter, result)


@app.command()
@handle_api_errors
def delete(
    ctx: typer.Context,
    deployment: str = typer.Argument(None, help="Deployment name", autocompletion=complete_deployment),
    deployment_opt: str = typer.Option(
        None,
        "--name",
        help="Same value as the positional, spelled out; pass one of the two",
        autocompletion=complete_deployment,
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
    ignore_not_found: bool = typer.Option(False, "--ignore-not-found", help="Exit 0 if deployment doesn't exist"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be sent without making the API call"),
) -> None:
    """Delete a single deployment."""
    deployment = one_name(deployment, deployment_opt, what="deployment name")
    from zad_cli.api.client import ZadApiError
    from zad_cli.api.errors import FAULT_EXIT_CODE, Diagnosis, Fault

    project = require_project(ctx)
    client, formatter = get_helpers(ctx)

    if dry_run:
        render_dry_run(formatter, "DELETE", f"/v2/projects/{project}/{deployment}")
        return

    confirm_action(f"Delete deployment '{deployment}' in project '{project}'?", yes, ctx)

    def _absent() -> None:
        """Say nothing was deleted, and let --ignore-not-found decide whether that is fine.

        The API used to answer 404 here and now completes the task with
        ``deleted: false``/``already_absent``. Reporting that as "deleted" would claim an
        action that did not happen, so the answer is read rather than assumed.

        The payload is only written on the branch that reports success. On the failing
        branch the diagnosis *is* the stdout document in json mode, and printing a body
        in front of it would leave two json documents on stdout.
        """
        if ignore_not_found:
            formatter.render({"deleted": False, "reason": "not_found"})
            formatter.render_success(f"Deployment '{deployment}' not found (already deleted).")
            return
        formatter.render_diagnosis(
            Diagnosis(
                fault=Fault.USER_INPUT,
                headline=f"Deployment '{deployment}' does not exist in project '{project}'.",
                summary="Nothing was deleted.",
                next_steps=[
                    "Check the name with: zadctl deployment list",
                    "Pass --ignore-not-found to make an absent deployment a success.",
                ],
            )
        )
        raise typer.Exit(FAULT_EXIT_CODE[Fault.USER_INPUT])

    try:
        result = client.delete_deployment(project, deployment)
    except ZadApiError as e:
        if e.status_code == 404:
            _absent()
            return
        raise

    if isinstance(result, dict) and (result.get("already_absent") or result.get("deleted") is False):
        _absent()
        return
    formatter.render(result)
    formatter.render_success(f"Deployment '{deployment}' deleted.")
    surface_warnings(ctx, formatter, result)
