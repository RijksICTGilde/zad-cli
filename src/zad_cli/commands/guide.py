"""`zad guide`: the whole CLI in one call, as markdown or as structure."""

from __future__ import annotations

import typer

from zad_cli.guide import SECTION_NAMES, UnknownSectionError, build_guide, render_markdown


def guide_command(
    ctx: typer.Context,
    section: str = typer.Option(
        None,
        "--section",
        help=f"Show one part of the guide instead of all of it: {', '.join(SECTION_NAMES)}",
    ),
) -> None:
    """Explain the whole CLI in one call: the model, every command, the settings.

    Markdown on stdout by default, so `zad guide > GUIDE.md` and `zad guide | pbcopy`
    work. `--output json` gives the same content as structure (sections, commands,
    parameters) rather than one string of markdown.

    Needs no credentials: this is how you find out what ZAD offers before you log in.
    The service list comes from the API's registry, and falls back to the snapshot
    bundled with the CLI when the API cannot be reached — the guide says which it used.

    [bold]Example:[/bold]

        $ zad guide

        $ zad guide --section auth

        $ zad guide --output json > zad-guide.json
    """
    formatter = ctx.obj["formatter"]
    settings = ctx.obj["settings"]

    try:
        guide = build_guide(
            settings.api_url,
            refresh=ctx.obj.get("refresh_catalog", False),
            section=section,
        )
    except UnknownSectionError as e:
        raise typer.BadParameter(str(e)) from e

    if formatter.fmt in ("json", "yaml"):
        formatter.render_document(guide)
        return
    formatter.render_text(render_markdown(guide))
