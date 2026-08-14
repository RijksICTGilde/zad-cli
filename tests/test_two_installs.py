"""`zad` and `zadctl` are two names for one program, until they are not.

An agent reported behaviour that changed between two commands that are supposed to be the
same tool: `zadctl` was the fresh build, `zad` an older install still first on PATH. Nothing
in the output said so, so the difference read as the platform being inconsistent.

`version` runs the other name and reports what it *is*, rather than assuming the two names
share an install.
"""

from typer.testing import CliRunner

from zad_cli import cli
from zad_cli.cli import app

runner = CliRunner()


def _fake_path(monkeypatch, *, other_version: str) -> None:
    """Put a second binary named `zad` on PATH that answers with `other_version`."""
    import subprocess

    monkeypatch.setattr(cli.sys, "argv", ["/opt/new/zadctl", "version"])
    monkeypatch.setattr(
        "shutil.which",
        lambda name: {"zad": "/usr/local/bin/zad", "zadctl": "/opt/new/zadctl"}.get(name),
    )

    def fake_run(args, **kwargs):  # noqa: ANN001, ANN003
        return subprocess.CompletedProcess(args, 0, stdout=other_version, stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)


def test_a_second_install_under_the_other_name_is_named(monkeypatch):
    _fake_path(monkeypatch, other_version="zad_cli 0.9.1\n")

    result = runner.invoke(app, ["version", "--client-only"], env={"NO_COLOR": "1"})

    assert result.exit_code == 0
    combined = " ".join(result.output.split())
    assert "/usr/local/bin/zad" in combined
    assert "0.9.1" in combined


def test_the_same_version_under_both_names_is_not_worth_saying(monkeypatch):
    from zad_cli import __version__

    _fake_path(monkeypatch, other_version=f"zad_cli {__version__}\n")

    result = runner.invoke(app, ["version", "--client-only"], env={"NO_COLOR": "1"})

    assert result.exit_code == 0
    assert "/usr/local/bin/zad" not in result.output


def test_the_binary_being_run_is_not_reported_as_a_second_one(monkeypatch):
    """`zadctl` finding itself on PATH is the normal case, not a warning."""
    monkeypatch.setattr(cli.sys, "argv", ["/opt/new/zadctl", "version"])
    monkeypatch.setattr("shutil.which", lambda name: "/opt/new/zadctl")

    assert cli._other_binaries_on_path() == []
