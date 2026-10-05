"""Upgrade command: zadctl upgrade [--check] [--to TAG] [--dry-run]."""

from __future__ import annotations

import sys

import httpx
import typer

from zad_cli import __version__, update
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
        reason = f"Could not reach {update.LATEST_URL}: {e}"
    else:
        reason = f"{update.LATEST_URL} did not name a release; see {update.RELEASES_URL}."
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
        plan["asset"] = update.asset_url(tag or __version__, name)
        plan["checksums"] = update.checksums_url(tag or __version__)
        return plan
    command = update.python_upgrade_command(kind, tag=tag)
    plan["command"] = " ".join(command) if command else f"unknown for a {kind} install"
    return plan


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
    if tag is None and kind != "source":
        latest = _latest(formatter, required=(kind == "binary"))
        if latest and not update.is_newer(latest, __version__):
            formatter.render_document({"installed": __version__, "latest_release": latest, "update_available": False})
            formatter.render_success(f"zadctl {__version__} is already the newest release.")
            return
        tag = latest

    if dry_run:
        plan = _plan(kind, tag)
        plan["dry_run"] = True
        if tag:
            plan["tag"] = update.release_tag(tag)
        formatter.render_document(plan)
        formatter.render_warning_text("Dry run: nothing was installed.")
        return

    try:
        result = update.run_upgrade(tag, log=_log)
    except update.UpgradeError as e:
        formatter.render_error(str(e))
        raise typer.Exit(1) from e

    formatter.render_document(result)
    formatter.render_success(f"Upgraded. {result.get('version', 'zadctl')} is what runs now.")
