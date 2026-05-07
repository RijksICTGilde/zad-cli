"""Unit tests for command-level helpers in commands/deployment.py."""

import pytest

from zad_cli.commands.deployment import _status_color


@pytest.mark.parametrize(
    "status,expected",
    [
        ("Healthy", "green"),
        ("Degraded", "red"),
        ("Missing", "red"),
        ("OutOfSync", "red"),
        ("Suspended", "red"),
        ("Progressing", "yellow"),
        ("Pending", "yellow"),
        ("Unavailable", "dim"),
        ("Unknown", "dim"),
        ("", "dim"),
    ],
)
def test_status_color(status: str, expected: str) -> None:
    assert _status_color(status) == expected
