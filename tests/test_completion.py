"""Autocompletion, which is a different world from the rest of the CLI.

A completion runs before the command does. Click builds the contexts it needs to work out
what you are typing, but never invokes the callback that fills `ctx.obj` -- so every
callback that read `ctx.obj["settings"]` got `None`, returned an empty list, and looked
exactly like "nothing matches". That is why these tests call the callbacks the way Click
does: through a context built with `resilient_parsing`, with nothing invoked.
"""

from __future__ import annotations

import pytest
import typer.main

from zad_cli import helpers
from zad_cli.cli import app
from zad_cli.commands.service import complete_set
from zad_cli.helpers import complete_service


@pytest.fixture(autouse=True)
def _fresh_settings():
    """The resolved settings are cached per process; a test that sets env must not inherit."""
    helpers.completion_settings.cache_clear()
    yield
    helpers.completion_settings.cache_clear()


def _command(*path: str):
    command = typer.main.get_command(app)
    for name in path:
        command = command.get_command(None, name)
    return command


def _context(path: tuple[str, ...], argv: list[str]):
    return _command(*path).make_context(path[-1], argv, parent=None, resilient_parsing=True)


def test_a_completion_callback_works_without_the_command_having_run():
    """The regression this whole file exists for: `ctx.obj` is None here, and used to be
    the only place these callbacks looked."""
    ctx = _context(("service", "describe"), [])
    assert ctx.obj is None
    assert "sleep-mode" in complete_service(ctx, "sle")


def test_set_completes_the_options_of_the_named_service():
    ctx = _context(("service", "config", "set"), ["sleep-mode"])
    offered = complete_set(ctx, "wa")
    # With the `=` attached: half a flag is not something you can run, and the shell will
    # not add it for you.
    assert offered == ["wake-mode=", "waker-component=", "waker="]


def test_set_completes_a_nested_option_the_way_you_type_it():
    ctx = _context(("service", "config", "set"), ["cross-domain-access", "--target", "project"])
    assert "inbound[0].from.project=" in complete_set(ctx, "inbound[0].from.")


def test_set_completes_the_values_a_field_accepts():
    ctx = _context(("service", "config", "set"), ["sleep-mode"])
    assert complete_set(ctx, "wake-mode=") == ["wake-mode=auto", "wake-mode=confirm", "wake-mode=manual"]
    assert complete_set(ctx, "wake-mode=m") == ["wake-mode=manual"]


def test_set_offers_nothing_for_a_layer_it_cannot_know():
    """`publish-on-web` takes more than one layer, and its component layer and deployment
    layer have different fields. Offering one of them would be a guess."""
    without = _context(("service", "config", "set"), ["publish-on-web"])
    assert complete_set(without, "") == []

    with_target = _context(("service", "config", "set"), ["publish-on-web", "--target", "component"])
    assert "tls=" in complete_set(with_target, "")


def test_an_unknown_service_completes_to_nothing_rather_than_failing():
    """A completion that raises prints a traceback into somebody's prompt."""
    ctx = _context(("service", "config", "set"), ["not-a-service"])
    assert complete_set(ctx, "") == []
