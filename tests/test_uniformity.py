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

import re

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


def _confirming_commands() -> set[str]:
    """Every command that actually asks before it acts.

    Read from the source rather than from a list here: a list would be one more thing to
    keep in step with the code, which is the failure this test exists to catch.
    """
    import ast
    from pathlib import Path

    import zad_cli.commands

    asking: set[str] = set()
    for path in Path(next(iter(zad_cli.commands.__path__))).glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            calls = (n.func for n in ast.walk(node) if isinstance(n, ast.Call))
            if any(isinstance(f, ast.Name) and f.id == "confirm_action" for f in calls):
                asking.add(node.name)
    return asking


def test_no_help_text_promises_a_confirmation_that_is_not_there():
    """Help that describes behaviour the command no longer has.

    `deployment create --help` said "Use --yes to skip confirmation" for weeks after the
    confirmation was taken off it -- found by an agent that had nothing but the CLI to go
    on, and had no way to tell the sentence from the truth. Documentation that is wrong is
    worse than absent: it is read, believed, and planned around.
    """
    asking = _confirming_commands()
    liars = []
    for path, cmd in _commands():
        help_text = (cmd.help or "") + " " + (cmd.short_help or "")
        # A command *named* `orphan-confirm` is not a promise to prompt, so the name is
        # taken out before the sentence is read. The option's own `help="Skip
        # confirmation"` is Typer's boilerplate, not prose we wrote; this is about the
        # sentences in the docstring.
        prose = re.sub(r"[\w-]*-confirm\b|\bconfirm-[\w-]*", " ", help_text.lower())
        if "confirm" not in prose:
            continue
        if (cmd.callback.__name__ if cmd.callback else "") not in asking:
            liars.append(path)
    assert liars == [], f"help text mentions confirming, but these commands never ask: {liars}"


def _task_returning_client_methods() -> set[str]:
    """Every `ZadClient` method that hands back a *task* result.

    Read from the client rather than listed here: a v1 endpoint that becomes v2 upstream
    should pull its command into the rule on the day the client method changes, not on the
    day someone remembers this file.
    """
    import ast
    import inspect

    from zad_cli.api import client as client_module

    tree = ast.parse(inspect.getsource(client_module))
    returning: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        for call in (n for n in ast.walk(node) if isinstance(n, ast.Call)):
            func = call.func
            if isinstance(func, ast.Attribute) and func.attr == "_async_request":
                returning.add(node.name)
    return returning


def test_every_command_that_waits_for_a_task_says_what_came_back():
    """A task result carries more than success: `superseded`, component failures, warnings.

    `surface_warnings` is what turns those into a sentence -- and into a non-zero exit
    under `--strict`. Left off one command, the platform's own hand-over message ("a newer
    task took over the rollout") appears after `env add` and not after `component assign`,
    which is how a practice run came to record the same event twice as two different
    things: once as normal, once as a failure.
    """
    import ast
    from pathlib import Path

    import zad_cli.commands

    waiting = _task_returning_client_methods()
    silent: list[str] = []
    for path in Path(next(iter(zad_cli.commands.__path__))).glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            calls = [n.func for n in ast.walk(node) if isinstance(n, ast.Call)]
            polls = any(isinstance(f, ast.Attribute) and f.attr in waiting for f in calls)
            surfaces = any(isinstance(f, ast.Name) and f.id == "surface_warnings" for f in calls)
            if polls and not surfaces:
                silent.append(f"{path.name}:{node.name}")

    assert not silent, f"commands that wait for a task but never say what it reported: {sorted(silent)}"
