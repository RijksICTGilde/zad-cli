"""Where the caches live, and what happens on a machine with no home directory.

The second half is the one worth having. Every cache path used to be a module constant
computed while `zad_cli` was being imported, so a container running under a UID that is in
no passwd file -- where `Path.home()` raises -- met a traceback on `zadctl --version`. The
subprocess tests below are deliberately not `CliRunner` calls: the failure was at import
time, and only a fresh interpreter can meet it.
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


def _run(code: str, **env: str) -> subprocess.CompletedProcess[str]:
    """A fresh interpreter with no `HOME` and no `XDG_CACHE_HOME`, running `code`."""
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "ZAD_CATALOG_OFFLINE": "1",
        "ZAD_VERSION_CHECK": "off",
        "NO_COLOR": "1",
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


def test_no_home_falls_back_to_the_tempdir(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: (_ for _ in ()).throw(RuntimeError("no home"))))
    resolved = cache_dir()
    assert resolved.parent == Path(tempfile.gettempdir())
    assert resolved.name.startswith("zad-cache-")


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


def test_legacy_files_without_a_home_is_an_empty_list(monkeypatch: pytest.MonkeyPatch) -> None:
    """The note about files an older version wrote under ~ needs a ~ to look in."""
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: (_ for _ in ()).throw(RuntimeError("no home"))))
    assert envfile.legacy_files() == []
