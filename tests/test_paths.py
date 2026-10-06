"""Where the caches live, and what happens on a machine with no home directory.

The subprocess tests below are deliberately not `CliRunner` calls: a `Path.home()` that
raises used to break at import time, and only a fresh interpreter can meet that.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from zad_cli import __version__, envfile, update
from zad_cli.api import registry, spec
from zad_cli.paths import cache_dir

# Patched before `zad_cli` is imported, which is the only moment that reproduces the failure.
NO_HOME = (
    "import pathlib\n"
    "def _raise(*args, **kwargs):\n"
    "    raise RuntimeError('Could not determine home directory.')\n"
    "pathlib.Path.home = _raise\n"
)


def _home_raises(monkeypatch: pytest.MonkeyPatch, failure: Exception) -> None:
    """A `Path.home()` that fails the way a machine without a passwd entry fails."""

    def _raise(_cls: type) -> Path:
        raise failure

    monkeypatch.setattr(Path, "home", classmethod(_raise))


def _run(code: str, **env: str) -> subprocess.CompletedProcess[str]:
    """A fresh interpreter with no `HOME` and no `XDG_CACHE_HOME`, running `code`."""
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "ZAD_CATALOG_OFFLINE": "1",
        "ZAD_VERSION_CHECK": "off",
        "NO_COLOR": "1",
        # Wide, because Rich wraps at 80 in a pipe and a wrapped
        # message is a different string to an assertion.
        "COLUMNS": "200",
        # The fallback directory is the one this process would pick, since the assertions
        # compare against `tempfile.gettempdir()` here. On macOS TMPDIR is always set.
        "TMPDIR": tempfile.gettempdir(),
        **env,
    }
    return subprocess.run(  # noqa: S603
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=120, env=environment, check=False
    )


# --- Which directory ---


def test_xdg_cache_home_wins(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    assert cache_dir() == tmp_path / "xdg" / "zad"


def test_home_is_the_default(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: tmp_path / "home"))
    assert cache_dir() == tmp_path / "home" / ".cache" / "zad"


def test_an_empty_xdg_cache_home_is_no_answer(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """An exported but empty variable is how a shell says nothing, not `/zad`."""
    monkeypatch.setenv("XDG_CACHE_HOME", "   ")
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: tmp_path / "home"))
    assert cache_dir() == tmp_path / "home" / ".cache" / "zad"


@pytest.mark.parametrize("failure", [RuntimeError("no home"), OSError("no passwd entry")])
def test_no_home_falls_back_to_the_tempdir(monkeypatch: pytest.MonkeyPatch, failure: Exception) -> None:
    """A missing `HOME` raises `RuntimeError`, a missing passwd entry `OSError`."""
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    _home_raises(monkeypatch, failure)
    resolved = cache_dir()
    assert resolved.parent == Path(tempfile.gettempdir())
    assert resolved.name.startswith("zad-cache-")


def test_the_tempdir_fallback_names_a_user_even_without_geteuid(monkeypatch: pytest.MonkeyPatch) -> None:
    """`os.geteuid` is POSIX only, and the fallback has to answer on Windows as well."""
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    _home_raises(monkeypatch, RuntimeError("no home"))
    monkeypatch.delattr(os, "geteuid", raising=False)

    assert cache_dir() == Path(tempfile.gettempdir()) / "zad-cache-0"


def test_every_cache_is_in_the_same_place(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """One function, so the catalog, the spec and the release check cannot disagree."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    expected = tmp_path / "xdg" / "zad"
    assert registry.cache_path("https://api.example.com/api").parent == expected
    assert spec.live_cache_path("https://api.example.com/api").parent == expected
    assert update._state_path().parent == expected


# --- A run without a usable home ---


def test_a_command_runs_without_a_resolvable_home() -> None:
    """The whole point: no home, no traceback, and the command still answers."""
    done = _run(NO_HOME + "import sys; sys.argv = ['zadctl', '--version']\nfrom zad_cli.cli import main\nmain()\n")
    assert done.returncode == 0, done.stderr
    assert f"zadctl {__version__}" in done.stdout


def test_the_service_catalog_still_answers_without_a_home() -> None:
    """A command that does read a cache, since `--version` returns before anything is read."""
    done = _run(
        NO_HOME + "import sys; sys.argv = ['zadctl', 'service', 'list']\nfrom zad_cli.cli import main\nmain()\n"
    )
    assert done.returncode == 0, done.stderr
    assert "postgresql-database" in done.stdout


def test_the_cache_is_written_without_a_home() -> None:
    """Not just importable: the fallback directory is one the CLI can actually write."""
    done = _run(
        NO_HOME + "from zad_cli import update\nupdate._write_state({'latest': '9.9.9'})\n"
        "print(update.cached_latest())\nprint(update._state_path())\n"
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout.splitlines()[0] == "9.9.9"
    assert done.stdout.splitlines()[1].startswith(tempfile.gettempdir())


@pytest.mark.parametrize("failure", [RuntimeError("no home"), OSError("no passwd entry")])
def test_legacy_files_without_a_home_is_an_empty_list(monkeypatch: pytest.MonkeyPatch, failure: Exception) -> None:
    """The note about files an older version wrote under ~ needs a ~ to look in.

    Both failures, because `Path.home()` answers a missing `HOME` with `RuntimeError` and a
    missing passwd entry with `OSError`, and the note is worth exactly as little either way.
    """
    _home_raises(monkeypatch, failure)
    assert envfile.legacy_files() == []
