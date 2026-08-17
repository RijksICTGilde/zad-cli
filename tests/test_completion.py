"""Autocompletion, exercised the way a shell exercises it.

A completion runs before the command does, and that makes it a different world twice over.

Click builds the contexts it needs to work out what you are typing but never invokes the
callback that fills `ctx.obj` -- so every callback that read `ctx.obj["settings"]` got
`None`, returned an empty list, and looked exactly like "nothing matches".

And the line being completed is not a valid command line: it ends in `--set` with nothing
after it, which is a parse error. Click swallows it under `resilient_parsing` and abandons
the rest, so `ctx.params` comes back empty while the words are still in `ctx.args`.

Both of those are invisible to a test that calls the callback with a context it built
itself from a complete command line. These tests go through `_resolve_context` and
`_resolve_incomplete`, which is the path the shell takes.
"""

from __future__ import annotations

import pytest
import typer.main
from typer._click.shell_completion import _resolve_context, _resolve_incomplete

from zad_cli import helpers
from zad_cli.cli import app


@pytest.fixture(autouse=True)
def _fresh_settings():
    """The resolved settings are cached per process; a test that sets env must not inherit."""
    helpers.completion_settings.cache_clear()
    yield
    helpers.completion_settings.cache_clear()


def complete(args: list[str], incomplete: str) -> list[str]:
    """What the shell would be offered for `zadctl <args> <incomplete>`."""
    cli = typer.main.get_command(app)
    ctx = _resolve_context(cli, {}, "zadctl", args)
    obj, resolved = _resolve_incomplete(ctx, args, incomplete)
    return [item.value for item in obj.shell_complete(ctx, resolved)]


def test_a_service_name_completes():
    """The regression this file exists for: these callbacks read `ctx.obj`, which is None
    here, so nothing has ever completed."""
    assert "sleep-mode" in complete(["service", "describe"], "sle")


def test_set_completes_the_options_of_the_named_service():
    offered = complete(["service", "config", "set", "sleep-mode", "--set"], "wa")
    # With the `=` attached: half a flag is not something you can run, and the shell will
    # not add it for you.
    assert offered == ["wake-mode=", "waker-component=", "waker="]


def test_set_reads_the_service_name_off_a_line_that_does_not_parse():
    """The line ends in a dangling `--set`, so every parameter is `None` by the time a
    completion callback runs. The words are still there."""
    after_one = complete(["service", "config", "set", "sleep-mode", "--set", "enabled=true", "--set"], "wa")
    assert after_one == ["wake-mode=", "waker-component=", "waker="]


def test_set_completes_a_nested_option_the_way_you_type_it():
    args = ["service", "config", "set", "cross-domain-access", "--target", "project", "--set"]
    assert "inbound[0].from.project=" in complete(args, "inbound[0].from.")


def test_set_completes_the_values_a_field_accepts():
    args = ["service", "config", "set", "sleep-mode", "--set"]
    assert complete(args, "wake-mode=") == ["wake-mode=auto", "wake-mode=confirm", "wake-mode=manual"]
    assert complete(args, "wake-mode=m") == ["wake-mode=manual"]


def test_a_layer_it_cannot_know_offers_nothing():
    """`publish-on-web` takes more than one layer, and its component layer and deployment
    layer have different fields. Offering one of them would be a guess."""
    assert complete(["service", "config", "set", "publish-on-web", "--set"], "") == []
    with_target = ["service", "config", "set", "publish-on-web", "--target", "component", "--set"]
    assert "tls=" in complete(with_target, "")


def test_an_option_value_is_not_mistaken_for_the_service():
    """`--target component` names a layer. Reading `component` as the service would offer
    the fields of something nobody named."""
    assert complete(["service", "config", "set", "--target", "component", "--set"], "t") == []


def test_an_unknown_service_completes_to_nothing_rather_than_failing():
    """A completion that raises prints a traceback into somebody's prompt."""
    assert complete(["service", "config", "set", "not-a-service", "--set"], "") == []
