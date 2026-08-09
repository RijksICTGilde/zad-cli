"""An arrow-key picker, built from what the CLI already carries.

Rich draws the list and the terminal's own raw mode delivers the keys, so choosing a
project costs no extra dependency. Everything the picker draws goes to **stderr**: the
picker is interaction, not data, and `--output json` must stay machine-readable.

Where raw mode does not exist (Windows without a console, a stdin that is not a
terminal), the picker falls back to a numbered prompt. Callers should still check
:func:`is_interactive` first and refuse to guess when there is no terminal at all.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass

from zad_cli.output.formatter import err_console


def _no_raw_mode_errors() -> tuple[type[BaseException], ...]:
    """The ways a terminal says it cannot do raw mode. Anything else is a real bug.

    ``termios`` does not exist on Windows, so the tuple is built rather than written out.
    """
    errors: list[type[BaseException]] = [
        ImportError,  # no termios/tty on this platform
        OSError,  # a file descriptor that is not a terminal (io.UnsupportedOperation included)
        ValueError,  # a closed or captured stdin has no fileno
        AttributeError,  # a stdin replacement that is not a file at all
    ]
    try:
        import termios
    except ImportError:  # pragma: no cover - Windows
        pass
    else:
        errors.append(termios.error)
    return tuple(errors)


@dataclass
class Choice:
    """One line in the picker: what is returned, what is shown, and a dim suffix."""

    value: str
    label: str
    hint: str = ""


def is_interactive() -> bool:
    """True when there is a terminal on both ends to run a picker in."""
    try:
        return sys.stdin.isatty() and sys.stderr.isatty()
    except (AttributeError, ValueError):
        return False


def _render(choices: list[Choice], index: int, title: str):
    from rich.text import Text

    body = Text()
    body.append(f"{title}\n", style="bold")
    for i, choice in enumerate(choices):
        selected = i == index
        body.append("  ")
        body.append("> " if selected else "  ", style="cyan")
        body.append(choice.label, style="bold cyan" if selected else "")
        if choice.hint:
            body.append(f"  {choice.hint}", style="dim")
        body.append("\n")
    body.append("  ↑/↓ to move, Enter to choose, q to cancel", style="dim")
    return body


def _read_key(fd: int) -> str:
    """One keypress, normalised to a name. Unknown keys come back as themselves."""
    char = os.read(fd, 1).decode(errors="ignore")
    if char == "\x1b":
        rest = os.read(fd, 2).decode(errors="ignore")
        return {"[A": "up", "[B": "down"}.get(rest, "escape")
    if char in ("\r", "\n"):
        return "enter"
    if char == "\x03":
        return "escape"
    return char


def _pick_raw(choices: list[Choice], title: str, initial: int) -> str | None:
    """The arrow-key loop. Returns None when the user cancels."""
    import termios
    import tty

    from rich.live import Live

    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    index = initial
    try:
        tty.setcbreak(fd)
        with Live(_render(choices, index, title), console=err_console, auto_refresh=False, transient=True) as live:
            while True:
                key = _read_key(fd)
                if key == "up":
                    index = (index - 1) % len(choices)
                elif key == "down":
                    index = (index + 1) % len(choices)
                elif key == "enter":
                    return choices[index].value
                elif key in ("escape", "q"):
                    return None
                live.update(_render(choices, index, title), refresh=True)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)


def _pick_numbered(choices: list[Choice], title: str) -> str | None:
    """Fallback for terminals without raw mode: a numbered list and one prompt."""
    import typer
    from rich.markup import escape

    err_console.print(f"[bold]{escape(title)}[/bold]")
    for i, choice in enumerate(choices, start=1):
        # Label and hint carry names and descriptions the server wrote; brackets in them
        # are text, not Rich markup.
        hint = f"  [dim]{escape(choice.hint)}[/dim]" if choice.hint else ""
        err_console.print(f"  {i}. {escape(choice.label)}{hint}")
    answer = typer.prompt("Number (or empty to cancel)", default="", show_default=False, err=True).strip()
    if not answer:
        return None
    try:
        number = int(answer)
    except ValueError:
        return None
    if 1 <= number <= len(choices):
        return choices[number - 1].value
    return None


_NO_RAW_MODE = _no_raw_mode_errors()


def pick(choices: list[Choice], *, title: str, initial: int = 0) -> str | None:
    """Let the user choose one of ``choices``; None when they cancel.

    A single choice is still shown rather than auto-picked: what the CLI is about to make
    active should be something the user saw.
    """
    if not choices:
        return None
    initial = initial if 0 <= initial < len(choices) else 0
    try:
        return _pick_raw(choices, title, initial)
    except _NO_RAW_MODE:
        # Only "this terminal has no raw mode" falls back. Catching everything here would
        # turn a genuine drawing bug into a silently different, working-looking picker.
        return _pick_numbered(choices, title)
