"""Main CLI entrypoint: Typer app with sub-command groups."""

from __future__ import annotations

import os
import sys

import typer
from typer.core import TyperGroup

from zad_cli import __version__
from zad_cli.commands import (
    admin,
    attachment,
    backup,
    clone,
    component,
    db,
    deployment,
    guide,
    login,
    logs,
    project,
    registry,
    resource,
    restore,
    service,
    task,
)
from zad_cli.commands.config_cmd import app as config_app
from zad_cli.commands.open_cmd import app as open_app
from zad_cli.commands.values import alias_app, env_app


def _one_output_format(output: str | None, *, json_out: bool, yaml_out: bool) -> str | None:
    """Fold `--json` / `--yaml` into `--output`, refusing a combination that contradicts itself.

    They are sugar, not a second channel: two ways of asking for a format that disagree is a
    typo worth reporting, not a precedence rule worth inventing.
    """
    shorthands = [fmt for fmt, given in (("json", json_out), ("yaml", yaml_out)) if given]
    if not shorthands:
        return output
    if len(shorthands) > 1:
        raise typer.BadParameter("--json and --yaml cannot be combined.")
    shorthand = shorthands[0]
    if output is not None and output.strip().lower() != shorthand:
        raise typer.BadParameter(f"--{shorthand} contradicts --output {output}; pass one of the two.")
    return shorthand


class _GlobalOptionsGroup(TyperGroup):
    """Hoist global options to before the subcommand, and answer to the plural too."""

    def get_command(self, ctx, name):  # noqa: ANN001, ANN201
        """`zad deployments list` reaches `zadctl deployment list`.

        The nouns are singular because the noun names the *kind* of thing, not how many
        there are; `zadctl deployment list` reads as one sentence and `zad deployments list`
        does not. But everybody types the plural anyway when they are listing, and being
        corrected by a usage error for a word the CLI understood perfectly well is the
        kind of friction that adds up over a day.

        Derived, not listed: strip the plural and look again. A new command group gets its
        plural for free, and there is no table of spellings to keep in step with the tree.
        """
        command = super().get_command(ctx, name)
        if command is not None:
            return command
        # On the ending, not a fixed number of characters: cutting two off anything would
        # make `deploymentss` reach `deployment`, and a typo that silently works is worse
        # than one that is refused.
        candidates = []
        if name.endswith("es"):
            candidates.append(name[:-2])  # aliases -> alias
        if name.endswith("s"):
            candidates.append(name[:-1])  # tasks -> task
        for singular in candidates:
            found = super().get_command(ctx, singular)
            if found is not None:
                return found
        return None

    _OPTS_WITH_VALUE = frozenset(
        {
            "--output",
            "-o",
            "--api-key",
            "--api-url",
            "--project",
            "-p",
            "--keycloak-url",
            "--keycloak-realm",
            "--keycloak-client-id",
        }
    )
    _FLAGS = frozenset(
        {
            "--no-wait",
            "--verbose",
            "-v",
            "--version",
            "-V",
            "--strict",
            "--rollout",
            "--no-rollout",
            "--refresh-catalog",
            "--json",
            "--yaml",
        }
    )

    def parse_args(self, ctx, args):  # noqa: ANN001
        global_args: list[str] = []
        remaining: list[str] = []
        i = 0
        while i < len(args):
            arg = args[i]
            if arg == "--":
                remaining.extend(args[i:])
                break
            elif "=" in arg and arg.split("=", 1)[0] in self._OPTS_WITH_VALUE:
                global_args.append(arg)
                i += 1
            elif arg in self._OPTS_WITH_VALUE:
                global_args.append(arg)
                if i + 1 < len(args):
                    global_args.append(args[i + 1])
                    i += 2
                else:
                    i += 1
            elif arg in self._FLAGS:
                global_args.append(arg)
                i += 1
            else:
                remaining.append(arg)
                i += 1
        return super().parse_args(ctx, global_args + remaining)


app = typer.Typer(
    cls=_GlobalOptionsGroup,
    help="CLI for ZAD (Zelfservice Applicatie Deployment).",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

# Panels group 25 command groups into something a reader can scan. The order within a
# panel goes from what you reach for most to what you reach for least.
SETUP = "Getting set up"
WORKLOADS = "Projects and deployments"
SERVICES = "Services and configuration"
DATA = "Data and recovery"
INSIGHT = "Seeing what is happening"
PLATFORM = "Platform administration"

app.command(name="guide", rich_help_panel=SETUP)(guide.guide_command)
app.command(name="login", rich_help_panel=SETUP)(login.login_command)
app.command(name="logout", rich_help_panel=SETUP)(login.logout_command)
app.add_typer(config_app, name="config", rich_help_panel=SETUP)

app.add_typer(project.app, name="project", rich_help_panel=WORKLOADS)
app.add_typer(deployment.app, name="deployment", rich_help_panel=WORKLOADS)
app.add_typer(component.app, name="component", rich_help_panel=WORKLOADS)
app.add_typer(task.app, name="task", rich_help_panel=WORKLOADS)

app.add_typer(service.app, name="service", rich_help_panel=SERVICES)
app.add_typer(env_app, name="env", rich_help_panel=SERVICES)
app.add_typer(alias_app, name="alias", rich_help_panel=SERVICES)
app.add_typer(attachment.app, name="attachment", rich_help_panel=SERVICES)
app.add_typer(db.app, name="db", rich_help_panel=SERVICES)
app.add_typer(registry.app, name="registry", rich_help_panel=SERVICES)
app.add_typer(resource.app, name="resource", rich_help_panel=SERVICES)

app.add_typer(backup.app, name="backup", rich_help_panel=DATA)
app.add_typer(restore.app, name="restore", rich_help_panel=DATA)
app.add_typer(clone.app, name="clone", rich_help_panel=DATA)

app.command(name="logs", rich_help_panel=INSIGHT)(logs.logs_command)
app.add_typer(open_app, name="open", rich_help_panel=INSIGHT)

app.add_typer(admin.app, name="admin", rich_help_panel=PLATFORM)


def _version_callback(value: bool) -> None:
    if value:
        print(f"zadctl {__version__}")
        raise typer.Exit()


@app.callback()
def main_callback(
    ctx: typer.Context,
    output: str = typer.Option(
        None,
        "--output",
        "-o",
        help="Output format: table, json, yaml. Default: table, or ZAD_OUTPUT_FORMAT / "
        "`zadctl config set output json`.",
    ),
    json_out: bool = typer.Option(False, "--json", help="Shorthand for --output json"),
    yaml_out: bool = typer.Option(False, "--yaml", help="Shorthand for --output yaml"),
    # No envvar= here: the environment is read in settings.py, which is also where the
    # precedence lives. Letting Typer fill the flag from the environment would make the
    # two indistinguishable, and `zadctl config list` could no longer say which one won.
    api_key: str = typer.Option(None, "--api-key", help="API key for the project (env: ZAD_API_KEY)"),
    api_url: str = typer.Option(None, "--api-url", help="Operations Manager API base URL (env: ZAD_API_URL)"),
    project_id: str = typer.Option(None, "--project", "-p", help="Project ID (env: ZAD_PROJECT_ID)"),
    no_wait: bool = typer.Option(False, "--no-wait", help="Don't wait for async operations, return task ID"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable verbose request logging"),
    strict: bool = typer.Option(
        False, "--strict", help="Exit non-zero when an operation succeeds but reports warnings (for CI/CD)"
    ),
    rollout: bool | None = typer.Option(
        None,
        "--rollout/--no-rollout",
        help="Roll the change out to the cluster. --no-rollout saves it and leaves the cluster untouched "
        "until `zadctl project refresh`; see `zadctl project pending`. Default: true, or ZAD_ROLLOUT / "
        "`zadctl config set rollout false`.",
    ),
    refresh_catalog: bool = typer.Option(
        False, "--refresh-catalog", help="Re-fetch the service catalog instead of using the cached copy"
    ),
    keycloak_url: str = typer.Option(
        None, "--keycloak-url", help="Keycloak base URL for `zadctl login` (env: ZAD_KEYCLOAK_URL)"
    ),
    keycloak_realm: str = typer.Option(
        None, "--keycloak-realm", help="Keycloak realm for `zadctl login` (env: ZAD_KEYCLOAK_REALM)"
    ),
    keycloak_client_id: str = typer.Option(
        None, "--keycloak-client-id", help="OAuth client `zadctl login` uses (env: ZAD_KEYCLOAK_CLIENT_ID)"
    ),
    version: bool = typer.Option(
        False, "--version", "-V", help="Show version and exit", callback=_version_callback, is_eager=True
    ),
) -> None:
    """Global options applied to all commands."""
    from zad_cli.output.formatter import OutputFormatter
    from zad_cli.settings import Settings

    ctx.ensure_object(dict)
    output_format = _one_output_format(output, json_out=json_out, yaml_out=yaml_out)
    settings = Settings.resolve(
        api_url=api_url,
        api_key=api_key,
        project_id=project_id,
        output_format=output_format,
        verbose=verbose,
        rollout=rollout,
        keycloak_url=keycloak_url,
        keycloak_realm=keycloak_realm,
        keycloak_client_id=keycloak_client_id,
    )
    ctx.obj["settings"] = settings
    ctx.obj["formatter"] = OutputFormatter(fmt=settings.output_format, table_style=settings.table_style)
    ctx.obj["no_wait"] = no_wait
    ctx.obj["strict"] = strict
    # Already resolved through flag > env > config > default; the flag is one of four voices.
    ctx.obj["rollout"] = settings.rollout
    ctx.obj["refresh_catalog"] = refresh_catalog


def _other_binaries_on_path() -> list[dict[str, str]]:
    """Any *other* zad binary the shell would find, and what version it is.

    `zad` and `zadctl` are two names for this program, and both end up on PATH. That is
    fine until they come from different installs: someone types `zad` out of habit and
    silently runs a version behind, with behaviour that changed in between. This runs the
    ones it finds so the report is what they *are*, not what they are named.
    """
    import shutil
    import subprocess
    from pathlib import Path

    here = Path(sys.argv[0]).resolve() if sys.argv and sys.argv[0] else None
    found: list[dict[str, str]] = []
    seen: set[str] = set()
    for name in ("zad", "zadctl"):
        located = shutil.which(name)
        if not located:
            continue
        resolved = str(Path(located).resolve())
        if resolved in seen or (here is not None and resolved == str(here)):
            continue
        seen.add(resolved)
        try:
            out = subprocess.run(  # noqa: S603 - a binary the user's own PATH points at
                [located, "--version"], capture_output=True, text=True, timeout=15, check=False
            )
            reported = out.stdout.strip() or out.stderr.strip() or "unknown"
        except Exception:  # noqa: BLE001 - a binary that will not answer is still worth naming
            reported = "did not answer"
        found.append({"name": name, "path": located, "version": reported})
    return found


@app.command(rich_help_panel="Getting set up")
def version(
    ctx: typer.Context,
    client_only: bool = typer.Option(False, "--client-only", help="Skip the call to the server"),
) -> None:
    """Show the CLI version, and the version of the API it is pointed at.

    Two versions matter when something behaves unexpectedly: which CLI you are running,
    and which build of the platform is answering it.

    [bold]pod[/bold] and [bold]image[/bold] say which instance answered. During a rollout
    two pods serve the same address, so two calls can report two different commits: if the
    pod name changes between them, wait rather than conclude the build failed. The image
    is what the cluster actually started, which is the only thing that survives a build
    made from uncommitted changes ([bold]dirty[/bold]).

    [bold]Example:[/bold]

        $ zadctl version
    """
    formatter = ctx.obj["formatter"]
    info: dict = {"zad_cli": __version__, "api_url": ctx.obj["settings"].api_url}

    # Named before the server is asked anything: a second install answering to the other
    # name is the likeliest reason for "it behaved differently a minute ago".
    others = _other_binaries_on_path()
    mismatched = [o for o in others if __version__ not in o["version"]]
    if mismatched:
        info["also_on_path"] = others
        for other in mismatched:
            formatter.render_warning_text(
                f"`{other['name']}` on your PATH is a different install: {other['path']} reports {other['version']}."
            )

    if not client_only:
        from zad_cli.api.client import ZadClient

        client = ZadClient(api_url=ctx.obj["settings"].api_url, api_key=ctx.obj["settings"].api_key)
        try:
            server = client.server_version()
            # Ordered on purpose, and `in server` rather than a default: outside
            # Kubernetes the server leaves pod and image empty, and an absent field is a
            # truthful "not applicable" where an empty string reads like a failed lookup.
            info["server"] = {
                key: server.get(key)
                for key in ("name", "version", "commit", "branch", "build_date", "dirty", "pod", "image")
                if key in server
            }
        except Exception as e:  # noqa: BLE001 - an unreachable server must not hide the CLI version
            info["server"] = {"error": f"could not reach {ctx.obj['settings'].api_url}: {e}"}
        finally:
            client.close()

    formatter.render_document(info)


def _usage_error_format() -> str:
    """The output format, without a parsed context.

    A usage error happens *because* parsing failed, so ctx.obj does not exist yet. The
    flags are read straight off argv, then the environment and the `.env.zadctl` below them, in
    the same order `Settings.resolve` uses.
    """
    argv = sys.argv[1:]
    if "--json" in argv:
        return "json"
    if "--yaml" in argv:
        return "yaml"
    for index, arg in enumerate(argv):
        if arg in ("--output", "-o") and index + 1 < len(argv):
            return argv[index + 1].strip().lower()
        if arg.startswith(("--output=", "-o=")):
            return arg.split("=", 1)[1].strip().lower()
    from zad_cli import envfile

    return (os.environ.get("ZAD_OUTPUT_FORMAT") or envfile.get("ZAD_OUTPUT_FORMAT") or "table").strip().lower()


def main() -> None:
    """CLI entrypoint.

    The `.env.zadctl` is not pushed into the environment here: settings reads it as its own layer,
    so `zadctl config list` can tell an exported variable apart from a remembered one.

    Click renders its own usage errors as a Rich panel, which is right for a terminal and
    wrong for `--output json`: a caller that parses stdout would get structure for every
    success and a drawn box for the most ordinary failure there is. Catching those means
    leaving Click's standalone mode, so everything standalone mode does is done here
    instead: an unhandled exit, an abort, and any other ClickException.
    """
    try:
        _run()
    finally:
        # After the command, whatever it did: this is a note about a file, not about the
        # outcome, and a failed run that still wrote a token deserves it just as much.
        _advise_on_shared_env()


def _advise_on_shared_env() -> None:
    from zad_cli import envfile
    from zad_cli.output.formatter import err_console

    advice = envfile.legacy_advice()
    if advice:
        err_console.print(f"[yellow]! {advice}[/yellow]")


def _run() -> None:
    """Everything `main` does apart from the note about the env file."""
    from typer._click.exceptions import Abort, ClickException, Exit, UsageError

    try:
        # Outside standalone mode Click *returns* the code for `typer.Exit` instead of
        # raising it, so the return value is the exit status and the handler below is only
        # for the paths that do raise.
        result = app(standalone_mode=False)
    except Exit as e:
        raise SystemExit(e.exit_code) from None
    except Abort:
        from typer.rich_utils import rich_abort_error

        rich_abort_error()
        raise SystemExit(1) from None
    except UsageError as e:
        # 1, not Click's 2. This CLI publishes what its exit codes mean -- 1 is your input,
        # 2 is the platform and worth retrying -- and a mistyped flag is as much "your
        # input" as a rejected field. Leaving Click's convention in place made a typo look
        # retryable to anything reading the code, which is the one reader that cannot tell
        # the difference by looking at the message.
        usage_exit = 1
        fmt = _usage_error_format()
        if fmt not in ("json", "yaml"):
            # Typer's renderer, not Click's: `show()` prints plain text, and the panel is
            # what this CLI looks like everywhere else.
            from typer.rich_utils import rich_format_error

            rich_format_error(e)
            raise SystemExit(usage_exit) from None
        from zad_cli.output.formatter import OutputFormatter

        details: dict[str, str] = {}
        if e.ctx is not None:
            details["usage"] = " ".join(e.ctx.get_usage().split())
            details["help"] = f"{e.ctx.command_path} --help"
        OutputFormatter(fmt=fmt).render_error(str(e), details=details or None, status_code=usage_exit)
        raise SystemExit(usage_exit) from None
    except ClickException as e:
        e.show()
        raise SystemExit(e.exit_code) from None
    raise SystemExit(result if isinstance(result, int) else 0)
