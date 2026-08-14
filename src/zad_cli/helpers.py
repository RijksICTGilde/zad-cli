"""Shared helpers for command modules."""

from __future__ import annotations

import functools
import sys
from collections.abc import Callable
from datetime import UTC
from typing import TYPE_CHECKING, Any

import typer

from zad_cli import credentials

if TYPE_CHECKING:
    from zad_cli.api.client import ZadClient
    from zad_cli.api.registry import ServiceCatalog, ServiceEntry
    from zad_cli.output.formatter import OutputFormatter


def _ensure_client(ctx: typer.Context, *, require_api_key: bool = True) -> None:
    """Lazily create the API client when first needed."""
    if ctx.obj.get("client"):
        return

    from zad_cli.api.client import ZadClient

    settings = ctx.obj["settings"]
    if require_api_key and not settings.api_key:
        from zad_cli import envfile

        # The file this directory actually uses, which is not always the same name: a `.env`
        # that already held ZAD_ variables stays in use. Naming the wrong one sends someone
        # to edit a file that is not being read.
        print(
            f"Error: no API key. Set ZAD_API_KEY in {envfile.env_path().name} or the environment, "
            "pass --api-key, or run `zadctl login` and `zadctl project use <name>`.",
            file=sys.stderr,
        )
        raise typer.Exit(1)

    client = ZadClient(
        api_url=settings.api_url,
        api_key=settings.api_key,
        max_retries=settings.max_retries,
        retry_delay=settings.retry_delay,
        task_timeout=settings.task_timeout,
        task_poll_interval=settings.task_poll_interval,
    )
    client.wait = not ctx.obj.get("no_wait", False)
    client.verbose = settings.verbose
    # Only pin rollout when the user asked for --no-rollout; otherwise let the API decide.
    client.rollout = False if ctx.obj.get("rollout") is False else None
    ctx.obj["client"] = client


def get_helpers(ctx: typer.Context, *, require_api_key: bool = True) -> tuple[ZadClient, OutputFormatter]:
    """Get the API client and output formatter from context.

    ``require_api_key=False`` is for the two commands that authenticate with an SSO token
    instead: listing projects and creating one.
    """
    _ensure_client(ctx, require_api_key=require_api_key)
    return ctx.obj["client"], ctx.obj["formatter"]


def get_catalog(ctx: typer.Context) -> ServiceCatalog:
    """The service catalog for the configured API, fetched or cached.

    No API key is needed, so this works before a project is chosen. Failure to reach the
    API *and* find any cached or bundled copy is fatal: without the catalog the CLI has
    no idea which services exist, and guessing is exactly what this replaces.
    """
    if ctx.obj.get("catalog"):
        return ctx.obj["catalog"]

    from zad_cli.api.registry import load_catalog

    settings = ctx.obj["settings"]
    try:
        catalog = load_catalog(settings.api_url, refresh=ctx.obj.get("refresh_catalog", False))
    except Exception as e:  # noqa: BLE001 - httpx and json errors alike leave us without a catalog
        print(f"Error: could not load the service catalog from {settings.api_url}: {e}", file=sys.stderr)
        raise typer.Exit(2) from e

    if catalog.source == "snapshot":
        # Loud on purpose. The snapshot is close enough to the real catalog that the
        # difference does not show in the output, so a quiet line above a full-screen table
        # is a wrong answer that looks right.
        from zad_cli.api.registry import offline
        from zad_cli.output.formatter import err_console

        # Two different situations, and saying the wrong one sends someone to debug a
        # network that was never asked anything.
        if offline():
            err_console.print(
                "[bold yellow]![/bold yellow] [bold]Using the bundled service catalog.[/bold]\n"
                "  ZAD_CATALOG_OFFLINE is set, so the API was not asked; these services are "
                "whatever this CLI was released with.\n"
                "  Unset it to use the catalog the API publishes."
            )
        else:
            err_console.print(
                f"[bold yellow]![/bold yellow] [bold]Falling back to the bundled service catalog.[/bold]\n"
                f"  {settings.api_url} did not answer, so these services may be out of date "
                f"and may not match that API.\n"
                f"  Point at an API that serves the catalog with "
                f"[bold]zadctl config set api_url <url>[/bold]."
            )
    ctx.obj["catalog"] = catalog
    return catalog


def require_service(ctx: typer.Context, name: str) -> ServiceEntry:
    """Resolve a service name against the catalog, failing with the valid names."""
    from zad_cli.api.registry import UnknownServiceError

    try:
        return get_catalog(ctx).get(name)
    except UnknownServiceError as e:
        raise typer.BadParameter(str(e)) from e


def resolve_target(entry: ServiceEntry, target: str | None, *, available: list[str] | None = None) -> str:
    """Pick the config layer to act on.

    One target means no choice to make, so ``--target`` is optional. More than one means
    the CLI must not guess: writing project-wide config when a deployment override was
    meant is not something a default should decide.
    """
    choices = available if available is not None else entry.targets
    if target:
        if target not in choices:
            raise typer.BadParameter(
                f"Service '{entry.name}' has no '{target}' layer. Available: {', '.join(choices) or 'none'}"
            )
        return target
    if not choices:
        raise typer.BadParameter(f"Service '{entry.name}' takes no configuration.")
    if len(choices) == 1:
        return choices[0]
    raise typer.BadParameter(
        f"Service '{entry.name}' accepts more than one layer; pass --target ({', '.join(choices)})."
    )


def require_project(ctx: typer.Context) -> str:
    """Get project ID from the global --project flag or ZAD_PROJECT_ID."""
    settings = ctx.obj["settings"]
    if settings.project_id:
        return settings.project_id
    from zad_cli import envfile

    print(
        f"Error: project is required. Set ZAD_PROJECT_ID in {envfile.env_path().name} or pass -p.",
        file=sys.stderr,
    )
    raise typer.Exit(1)


# Which parameter names a thing whose existing values we can list, and how to list them.
# One entry per kind, so a 404 can say what does exist rather than only what does not.
NAME_SOURCES: dict[str, str] = {
    "deployment": "deployments",
    "component": "components",
    "service": "services",
}


def _existing_names(ctx: typer.Context, kind: str) -> list[str]:
    """The names of this kind that do exist, or an empty list when we cannot say.

    Best-effort on purpose: this runs while another error is already being reported, so a
    second failure here must not replace the first one. Silence is the right answer when
    the lookup itself does not work.
    """
    try:
        if kind == "service":
            return sorted(get_catalog(ctx).names())
        _ensure_client(ctx)
        client = ctx.obj["client"]
        project = ctx.obj["settings"].project_id
        if not project:
            return []
        if kind == "deployment":
            return sorted(d["deployment"] for d in client.list_deployments(project))
        components: set[str] = set()
        for deployment in client.list_deployments(project):
            components.update(deployment.get("components") or [])
        return sorted(components)
    except Exception:  # noqa: BLE001 - a failed suggestion must not hide the real error
        return []


def name_suggestions(ctx: typer.Context | None) -> list[str]:
    """Lines naming what does exist, for a command that was given a name that does not.

    Reading a 404 and then having to run `list` to find the spelling is two commands for
    one question. The parameters of the command that failed say which kind was meant, so
    the answer is available without the caller asking for it.
    """
    if ctx is None or not getattr(ctx, "params", None):
        return []
    lines: list[str] = []
    for param, kind in NAME_SOURCES.items():
        if not ctx.params.get(param):
            continue
        names = _existing_names(ctx, param)
        if names:
            lines.append(f"{kind} in this project: {', '.join(names)}")
    return lines


def handle_api_errors(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator that catches API and task errors and renders them via the formatter."""
    from zad_cli.api.client import TaskFailedError, TaskTimeoutError, ZadApiError

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        ctx_arg = kwargs.get("ctx") or next((a for a in args if isinstance(a, typer.Context)), None)
        try:
            result = fn(*args, **kwargs)
        except (ZadApiError, TaskFailedError, TaskTimeoutError) as e:
            ctx = ctx_arg
            formatter = ctx.obj["formatter"] if ctx else None
            diagnosis = getattr(e, "diagnosis", None)
            exit_code = 1
            # A 404 on a name is the one error where the answer is a list we can fetch.
            if diagnosis is not None and getattr(e, "status_code", None) == 404:
                diagnosis.details = [*diagnosis.details, *name_suggestions(ctx)]
            if formatter and diagnosis is not None:
                formatter.render_diagnosis(diagnosis)
                exit_code = diagnosis.exit_code
            elif formatter:
                formatter.render_error(
                    str(e), details=getattr(e, "details", None), status_code=getattr(e, "status_code", None)
                )
            else:
                print(f"Error: {e}", file=sys.stderr)
            # On timeout, show task ID so the user can follow up
            task_id = getattr(e, "task_id", None)
            if task_id:
                print(f"Task is still running. Check status with: zadctl task status {task_id}", file=sys.stderr)
                print(f"Or wait for completion with: zadctl task wait {task_id}", file=sys.stderr)
            raise typer.Exit(exit_code) from e
        if ctx_arg is not None:
            warn_deferred_rollout(ctx_arg)
        return result

    return wrapper


def warn_deferred_rollout(ctx: typer.Context) -> None:
    """After a --no-rollout mutation, say what is now waiting and how to roll it out.

    A saved change nobody rolls out is a project quietly out of step, so this is loud on
    purpose. It never fails the command: the mutation already succeeded.
    """
    client = ctx.obj.get("client")
    if client is None or not getattr(client, "rollout_deferred", 0):
        return
    client.rollout_deferred = 0

    from zad_cli.output.formatter import err_console

    project = ctx.obj["settings"].project_id
    pending = None
    if project:
        try:
            waiting = client.pending_rollout(project)
            pending = waiting.get("count")
            oldest = age(waiting.get("since"))
        except Exception:  # noqa: BLE001 - a best-effort count must not mask the success
            pending, oldest = None, ""

    count = f"{pending} change(s)" if pending is not None else "This change"
    # How long it has been waiting is the part that matters: one change saved a minute ago
    # is a workflow, three that have been waiting since this morning is drift.
    since = f", the oldest since {oldest}" if oldest else ""
    err_console.print(
        f"[yellow]Saved without rolling out. {count} waiting in project "
        f"'{project or '?'}'{since}.[/yellow]\n  Roll everything out with: zadctl project refresh\n"
        "  See what is waiting with: zadctl project pending"
    )


def surface_warnings(ctx: typer.Context, formatter: OutputFormatter, result: Any) -> None:
    """After a successful mutating op, surface any degraded state (unhealthy components,
    warnings, partial status). Under global --strict, exit non-zero so CI/CD fails the build.
    """
    from zad_cli.api.errors import degraded_diagnoses, superseded_note

    note = superseded_note(result)
    if note:
        # Said in the voice of a success, because it is one.
        formatter.render_success(note)

    diagnoses = degraded_diagnoses(result)
    if not diagnoses:
        return
    formatter.render_warnings(diagnoses)
    if ctx.obj.get("strict"):
        # Honor the per-fault exit code contract: a retryable (PLATFORM/NETWORK)
        # warning exits 2, not 1. Pick the most severe across all diagnoses.
        raise typer.Exit(max(d.exit_code for d in diagnoses))


def issues_cell(errors: list[dict] | None) -> str:
    """Rich-markup summary of a deployment's cluster errors for list/status tables.

    Empty string when clean; otherwise a colored ``<count> <dominant-category>`` cell so
    degraded deployments are never silently green.
    """
    if not errors:
        return ""
    from collections import Counter

    from zad_cli.api.errors import CATEGORY_FAULT, FAULT_COLOR, category_of

    counts = Counter(str(e.get("category", "Unknown")) for e in errors)
    top, _ = counts.most_common(1)[0]
    total = len(errors)
    label = f"{total} {top}" if total > 1 else top
    color = FAULT_COLOR[CATEGORY_FAULT[category_of(top)]]
    return f"[{color}]{label}[/{color}]"


SECRET_KEY_PARTS = ("password", "secret", "token", "access_key", "api_key", "private_key")

# The user's own document, where the keys are names they chose. Not masked: see below.
UNMASKED_SUBDOCUMENTS = ("values",)


def _mask_secrets(value: object) -> object:
    """A payload as it may appear on screen, with the credentials in it made unusable.

    Masking lives here rather than in each command because a dry run prints whatever it
    is given: a command that forgets is a command that writes a password to stdout. The
    redacted form keeps the first and last few characters, so you can still tell which
    credential it was without being able to use it.

    What is deliberately *not* masked is the `values` document of `zadctl env` and
    `zadctl alias`. There the keys are the user's own, and the value is the subject of the
    command rather than plumbing to reach the API: a dry run is how you check that
    `KEY=@file` read the file you meant, and `******` answers nothing. Redaction would
    also erase short values entirely, so the check it exists for would stop working.
    """
    if isinstance(value, dict):
        return {
            k: credentials.redact(v)
            if isinstance(v, str) and any(part in k.lower() for part in SECRET_KEY_PARTS)
            else v
            if k in UNMASKED_SUBDOCUMENTS
            else _mask_secrets(v)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_mask_secrets(item) for item in value]
    return value


def render_dry_run(formatter: OutputFormatter, method: str, endpoint: str, payload: dict | None = None) -> None:
    """Show what would be sent without making the API call."""
    info: dict = {"dry_run": True, "method": method, "endpoint": endpoint}
    # `is not None`, not truthiness: an empty body is a request ("use this service, with
    # nothing set") and leaving it out would make it look like no body was sent at all.
    if payload is not None:
        info["payload"] = _mask_secrets(payload)
    formatter.render(info)
    from zad_cli.output.formatter import err_console

    err_console.print("[yellow]Dry run: no changes made.[/yellow]")


def age(timestamp: object) -> str:
    """How long ago a timestamp was, in words. Empty when it cannot be read.

    Best-effort on purpose: this decorates a message, so an unparseable timestamp leaves
    the sentence shorter rather than raising in the middle of a successful command.
    """
    if not isinstance(timestamp, str) or not timestamp:
        return ""
    from datetime import datetime

    try:
        when = datetime.fromisoformat(timestamp)
    except ValueError:
        return ""
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    seconds = int((datetime.now(UTC) - when).total_seconds())
    if seconds < 60:
        return "just now"
    for unit, size in (("day", 86400), ("hour", 3600), ("minute", 60)):
        if seconds >= size:
            n = seconds // size
            return f"{n} {unit}{'s' if n > 1 else ''} ago"
    return "just now"


def confirm_action(message: str, yes: bool, ctx: typer.Context | None = None) -> None:
    """Ask for confirmation unless --yes was passed, or ZAD_YES says not to ask.

    ``ctx`` is optional so the old two-argument call keeps working; without it only the
    flag is consulted.
    """
    if yes:
        return
    if ctx is not None and ctx.obj and ctx.obj.get("settings") and ctx.obj["settings"].assume_yes:
        return
    typer.confirm(message, abort=True)


def complete_service(ctx: typer.Context, incomplete: str) -> list[str]:
    """Autocompletion callback for service names, from the cached catalog."""
    try:
        return [n for n in get_catalog(ctx).names(include_hidden=True) if n.startswith(incomplete)]
    except Exception:
        return []


def complete_deployment(ctx: typer.Context, incomplete: str) -> list[str]:
    """Autocompletion callback for deployment names."""
    try:
        _ensure_client(ctx)
        client = ctx.obj["client"]
        settings = ctx.obj["settings"]
        if not settings.project_id:
            return []
        deployments = client.list_deployments(settings.project_id)
        return [d["deployment"] for d in deployments if d["deployment"].startswith(incomplete)]
    except Exception:
        return []


def complete_component(ctx: typer.Context, incomplete: str) -> list[str]:
    """Autocompletion callback for component names."""
    try:
        _ensure_client(ctx)
        client = ctx.obj["client"]
        settings = ctx.obj["settings"]
        if not settings.project_id:
            return []
        deployments = client.list_deployments(settings.project_id)
        names: set[str] = set()
        for dep in deployments:
            for comp in dep["components"]:
                if comp.startswith(incomplete):
                    names.add(comp)
        return sorted(names)
    except Exception:
        return []


def one_name(positional: str | None, option: str | None, *, what: str, flag: str = "--name") -> str:
    """The name, however it was spelled, refusing two spellings that disagree.

    Both forms exist on purpose: the positional reads well by hand, and the option says
    what the value *is*, which is what a script or an agent wants. What may not happen is
    the two disagreeing and one silently winning, because that acts on the wrong resource.
    """
    if positional and option and positional != option:
        raise typer.BadParameter(f"'{positional}' and {flag} '{option}' disagree; pass one of the two.")
    name = positional or option
    if not name:
        raise typer.BadParameter(f"Missing {what}: pass it as an argument or with {flag}.")
    return name
