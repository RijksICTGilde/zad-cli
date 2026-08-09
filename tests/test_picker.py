"""The picker itself: what it draws, what it returns, and what it needs."""

from __future__ import annotations

import pytest

from zad_cli.picker import Choice, _read_key, _render, is_interactive, pick


class _FakeStdin:
    def __init__(self, tty: bool) -> None:
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


def test_is_interactive_needs_a_terminal_on_both_ends(monkeypatch: pytest.MonkeyPatch):
    import sys

    monkeypatch.setattr(sys, "stdin", _FakeStdin(True))
    monkeypatch.setattr(sys, "stderr", _FakeStdin(True))
    assert is_interactive() is True

    monkeypatch.setattr(sys, "stdin", _FakeStdin(False))
    assert is_interactive() is False


def test_is_interactive_survives_a_stdin_that_is_not_a_stream(monkeypatch: pytest.MonkeyPatch):
    import sys

    monkeypatch.setattr(sys, "stdin", object())
    assert is_interactive() is False


def test_the_rendered_list_marks_the_selection_and_keeps_the_hints():
    text = _render([Choice("a", "aap", "hint-a"), Choice("b", "beer")], 1, "Pick a project").plain
    assert "Pick a project" in text
    assert "hint-a" in text
    assert "> beer" in text
    assert "> aap" not in text


def test_arrow_keys_are_read_as_names(monkeypatch: pytest.MonkeyPatch):
    reads = iter([b"\x1b", b"[B"])
    monkeypatch.setattr("os.read", lambda fd, n: next(reads))
    assert _read_key(0) == "down"


def test_enter_and_ctrl_c_are_read_as_names(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("os.read", lambda fd, n: b"\r")
    assert _read_key(0) == "enter"
    monkeypatch.setattr("os.read", lambda fd, n: b"\x03")
    assert _read_key(0) == "escape"


def test_picking_from_nothing_returns_nothing():
    assert pick([], title="Pick") is None


def test_without_raw_mode_it_falls_back_to_a_numbered_prompt(monkeypatch: pytest.MonkeyPatch):
    """A terminal without termios still has a keyboard."""
    import zad_cli.picker as picker

    monkeypatch.setattr(picker, "_pick_raw", lambda *a, **k: (_ for _ in ()).throw(OSError("no raw mode")))
    monkeypatch.setattr("typer.prompt", lambda *a, **k: "2")
    assert pick([Choice("a", "aap"), Choice("b", "beer")], title="Pick") == "b"


def test_the_numbered_fallback_treats_nonsense_as_a_cancel(monkeypatch: pytest.MonkeyPatch):
    import zad_cli.picker as picker

    monkeypatch.setattr(picker, "_pick_raw", lambda *a, **k: (_ for _ in ()).throw(OSError("no raw mode")))
    monkeypatch.setattr("typer.prompt", lambda *a, **k: "99")
    assert pick([Choice("a", "aap")], title="Pick") is None
    monkeypatch.setattr("typer.prompt", lambda *a, **k: "")
    assert pick([Choice("a", "aap")], title="Pick") is None
