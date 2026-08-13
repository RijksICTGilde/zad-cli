"""One idea, one spelling, everywhere.

The cost of a CLI is not learning it once but checking it every time. If `--component`
means the same thing in twenty commands, you stop reading `--help`; if nineteen of them
take `-c` and the twentieth does not, you go back to reading all twenty. These tests are
about that twentieth, and they are mechanical on purpose: a rule nobody can forget is
better than one everybody agrees with.

Found by an agent that could only consult the CLI: `attachment list` refused the component
as an argument while `add` and `assign` took it that way, and `deployment create` had no
`-c` while everything else did.
"""

from __future__ import annotations

import typer.main

from zad_cli.cli import app


def _commands():
    """Every leaf command, with its full path."""
    root = typer.main.get_command(app)

    def walk(cmd, path=""):
        subs = getattr(cmd, "commands", None)
        if subs:
            for name, sub in subs.items():
                yield from walk(sub, f"{path} {name}".strip())
            return
        yield path, cmd

    return list(walk(root))


def _named_options(cmd, word: str) -> list[str]:
    """Every option spelling on this command whose parameter is about `word`."""
    spellings: list[str] = []
    for param in getattr(cmd, "params", []):
        if word in param.name:
            spellings.extend(opt for opt in getattr(param, "opts", []) if opt.startswith("-"))
    return spellings


def test_every_command_that_takes_a_component_accepts_the_same_two_spellings():
    """`--component` and `-c`, or the command explains itself in the exception list."""
    # `--components` is the deprecated JSON-array form and keeps its own name; `component
    # add` names the thing it creates positionally, which is the noun of the command
    # rather than a reference to another one.
    exempt = {"component add", "component update", "component delete", "component assign"}

    missing = []
    for path, cmd in _commands():
        if path in exempt:
            continue
        spellings = [s for s in _named_options(cmd, "component") if s != "--components"]
        if not spellings:
            continue
        if "--component" not in spellings or "-c" not in spellings:
            missing.append(f"{path}: {spellings}")

    assert not missing, "commands that spell the component differently from the rest:\n  " + "\n  ".join(missing)


def test_a_component_given_as_an_argument_can_also_be_given_as_an_option():
    """Two commands took it positionally only, which you find out after typing."""
    for path in ("attachment assign", "attachment list", "service attachments assign", "service attachments list"):
        cmd = dict(_commands())[path]
        spellings = _named_options(cmd, "component")
        assert "--component" in spellings and "-c" in spellings, f"{path} takes it positionally only: {spellings}"


def test_every_mutating_command_can_be_asked_what_it_would_send():
    """`--dry-run` is the answer to "is this what I meant?", and it only works if it is
    everywhere: one command without it sends you to the API to find out."""
    missing = []
    for path, cmd in _commands():
        opts = {opt for param in getattr(cmd, "params", []) for opt in getattr(param, "opts", [])}
        if "--yes" in opts and "--dry-run" not in opts:
            missing.append(path)

    assert not missing, f"commands that confirm but cannot be rehearsed: {missing}"
