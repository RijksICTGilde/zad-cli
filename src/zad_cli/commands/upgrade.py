"""Upgrade command: zadctl upgrade [--check] [--to TAG] [--dry-run].

`--dry-run` here renders a *plan* and not `render_dry_run`'s method/endpoint/payload: there is
no request to rehearse, and what someone wants to see before letting a command replace the
binary they are running is the asset URL, the target path and the checksum file, or the exact
package-manager command.
"""

from __future__ import annotations

import sys

import httpx
import typer

from zad_cli import __version__, update
from zad_cli.helpers import handle_api_errors
from zad_cli.output.formatter import OutputFormatter

#: Longer than the courtesy check in `update.start`: there a slow answer is worth dropping,
#: here it is the whole command and the user is waiting for it on purpose.
CHECK_TIMEOUT = 10.0

#: What the CLI prints instead of upgrading when the install is a git working copy.
SOURCE_HINT = "git pull"


def _log(line: str) -> None:
    """Progress from the download and the package manager, on stderr with everything else."""
    print(line, file=sys.stderr)


def _latest(formatter: OutputFormatter, *, required: bool) -> str | None:
    """The newest release, or None. Fatal when the caller cannot do anything without it.

    A binary upgrade needs the tag to build the asset URL, so there the failure ends the
    command. A package manager resolves the newest version itself, so there a failed check
    is a caveat and the upgrade still runs.
    """
    try:
        latest = update.fetch_latest(timeout=CHECK_TIMEOUT)
    except httpx.HTTPError as e:
        latest = None
        reason = f"Could not reach {update.latest_url()}: {e}"
    else:
        reason = f"{update.latest_url()} did not name a release; see {update.RELEASES_URL}."
    if latest:
        return latest
    if required:
        formatter.render_error(reason)
        raise typer.Exit(2)
    formatter.render_warning_text(reason)
    return None


def _plan(kind: str, tag: str | None) -> dict[str, object]:
    """What an upgrade of this install would do, without doing any of it."""
    plan: dict[str, object] = {"install": kind}
    if kind == "source":
        plan["action"] = SOURCE_HINT
        return plan
    if kind == "binary":
        target = update.executable_path()
        name = update.asset_name()
        plan["target"] = str(target) if target else "unknown"
        if name is None:
            plan["action"] = f"no binary is built for this platform; see {update.RELEASES_URL}"
            return plan
        if tag is None:
            # Never substitute the installed version: a plan to download the release you are
            # already on is worse than saying nothing was resolved.
            plan["action"] = f"no release resolved; see {update.RELEASES_URL}"
            return plan
        plan["asset"] = update.asset_url(tag, name)
        plan["checksums"] = update.checksums_url(tag)
        return plan
    command = update.python_upgrade_command(kind, tag=tag)
    plan["command"] = " ".join(command) if command else f"nothing here can upgrade a {kind} install"
    return plan


@handle_api_errors
def upgrade_command(
    ctx: typer.Context,
    check: bool = typer.Option(False, "--check", help="Only report what is available, change nothing"),
    to: str = typer.Option(None, "--to", metavar="TAG", help="Install a specific release, e.g. v0.13.2"),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show what would be downloaded or run without changing anything"
    ),
) -> None:
    """Install the newest zadctl release, however this copy was installed.

    The standalone binary is replaced in place, after its published sha256 has been
    checked; a `uv tool`, `pipx` or `pip` install is upgraded by running that tool. A git
    working copy is not touched, because there `git pull` is the upgrade.

    [bold]--check[/bold] only reports, and exits 1 when a newer release exists, so a
    pipeline can ask without installing anything. [bold]--to[/bold] names a release and
    can therefore also go back to one.

    [bold]Examples:[/bold]

        $ zadctl upgrade

        $ zadctl upgrade --check

        $ zadctl upgrade --to v0.13.2

        $ zadctl upgrade --dry-run
    """
    formatter = ctx.obj["formatter"]
    kind = update.install_kind()

    if to is not None and not update.valid_version(to):
        formatter.render_error(f"'{to}' is not a release version. Name one like v0.13.2.")
        raise typer.Exit(1)
    if check and to is not None:
        # A flag that parses and then does nothing is worse than a refusal: `--check` reports
        # the newest release and has nothing to say about a tag you named yourself.
        formatter.render_error("--check reports the newest release, so --to has nothing to do. Drop one of the two.")
        raise typer.Exit(1)

    if check:
        latest = _latest(formatter, required=True)
        available = update.is_newer(latest, __version__)
        report: dict[str, object] = {
            "installed": __version__,
            "latest_release": latest,
            "update_available": available,
            "install": kind,
        }
        if available:
            report["upgrade_with"] = SOURCE_HINT if kind == "source" else "zadctl upgrade"
        formatter.render_document(report)
        # Exit 1 when behind: a status question answered in the exit code is what makes
        # this usable in a pipeline that has no json parser.
        raise typer.Exit(1 if available else 0)

    tag = to
    current = False
    if tag is None and kind != "source":
        latest = _latest(formatter, required=(kind == "binary"))
        current = bool(latest) and not update.is_newer(latest, __version__)
        tag = latest

    # Before the "already newest" return, not after: being up to date is exactly when someone
    # reads the plan, since it is the one moment inspecting it costs nothing.
    if dry_run:
        plan = _plan(kind, tag)
        plan["dry_run"] = True
        if tag:
            plan["tag"] = update.release_tag(tag)
        if current:
            plan["update_available"] = False
        formatter.render_document(plan)
        formatter.render_warning_text("Dry run: nothing was installed.")
        return

    if current:
        formatter.render_document({"installed": __version__, "latest_release": tag, "update_available": False})
        formatter.render_success(f"zadctl {__version__} is already the newest release.")
        return

    try:
        result = update.run_upgrade(tag, log=_log)
    except update.UpgradeError as e:
        formatter.render_error(str(e))
        # 2 for the download and the release page, 1 for this install's own configuration:
        # the same split the API errors publish, so a pipeline can tell a retry from a fix.
        raise typer.Exit(2 if e.transient else 1) from e

    version = result.get("version")
    if not version:
        # The file is already replaced at this point, so this is not a failed download: it is
        # an installed zadctl that would not run, and reporting success for it sends a pipeline
        # straight into the next command. What was installed goes in the details rather than
        # through `render_document`, so json mode still answers with one document.
        details = {key: str(value) for key, value in result.items()}
        details["check"] = f"{result.get('target', 'zadctl')} --version"
        if result.get("install") == "binary":
            details["reinstall"] = update.manual_install_hint()
        formatter.render_error("zadctl was replaced but would not say which version it now is.", details=details)
        raise typer.Exit(1)

    formatter.render_document(result)
    formatter.render_success(f"Upgraded. {version} is what runs now.")
