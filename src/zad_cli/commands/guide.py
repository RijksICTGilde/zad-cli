"""`zad guide`: the whole CLI in one call, as markdown or as structure."""

from __future__ import annotations

import typer

from zad_cli.guide import SECTION_NAMES, UnknownSectionError, build_guide, render_markdown


def guide_command(
    ctx: typer.Context,
    section: str = typer.Option(
        None,
        "--section",
        help=f"Show one part instead: {', '.join(SECTION_NAMES)}",
    ),
    everything: bool = typer.Option(
        False, "--all", help="Include the full command reference (long; every line is also one --help away)"
    ),
) -> None:
    """How this CLI works: the model, and the order that gets you from nothing to running.

    By default this is the part that cannot be looked up per command: what the two kinds
    of credentials are for, what the configuration layers mean, saving versus rolling out,
    and the sequence with real commands. `--all` adds the full command reference, which is
    long and which `<command> --help` already answers one command at a time.

    Markdown on stdout, so `zad guide > GUIDE.md` and `zad guide | pbcopy` work.
    `--output json` gives the same content as structure rather than one string.

    Needs no credentials: this is how you find out what ZAD offers before you log in.
    The service list comes from the API's registry, and falls back to the snapshot
    bundled with the CLI when the API cannot be reached; the guide says which it used.

    [bold]Example:[/bold]

        $ zad guide

        $ zad guide --section workflow

        $ zad guide --all --output json > zad-guide.json
    """
    formatter = ctx.obj["formatter"]
    settings = ctx.obj["settings"]

    try:
        guide = build_guide(
            settings.api_url,
            refresh=ctx.obj.get("refresh_catalog", False),
            section=section,
            everything=everything,
        )
    except UnknownSectionError as e:
        raise typer.BadParameter(str(e)) from e

    if formatter.fmt in ("json", "yaml"):
        formatter.render_document(guide)
        return
    formatter.render_text(render_markdown(guide))
