"""Where the caches live, and what happens on a machine with no home directory.

The subprocess tests below are deliberately not `CliRunner` calls: a `Path.home()` that
raises used to break at import time, and only a fresh interpreter can meet that.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from zad_cli import __version__, envfile, update
from zad_cli.api import registry, spec
from zad_cli.paths import cache_dir, cache_file

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


def test_the_fallback_follows_the_tempdir_the_environment_names(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A child that is handed another `TMPDIR` falls back inside that one.

    The assertions above compare the child's answer against this process's
    `tempfile.gettempdir()`, so the two have to resolve to the same directory. On macOS
    `TMPDIR` is always set, and a child whose environment is stripped of it answered `/tmp`
    while the parent asked somewhere else.
    """
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(elsewhere))

    done = _run(NO_HOME + "from zad_cli import update\nprint(update._state_path())\n")

    assert done.returncode == 0, done.stderr
    assert done.stdout.strip().startswith(str(elsewhere)), done.stdout


@pytest.mark.parametrize("failure", [RuntimeError("no home"), OSError("no passwd entry")])
def test_legacy_files_without_a_home_is_an_empty_list(monkeypatch: pytest.MonkeyPatch, failure: Exception) -> None:
    """The note about files an older version wrote under ~ needs a ~ to look in.

    Both failures, because `Path.home()` answers a missing `HOME` with `RuntimeError` and a
    missing passwd entry with `OSError`, and the note is worth exactly as little either way.
    """
    _home_raises(monkeypatch, failure)
    assert envfile.legacy_files() == []


# --- A cache directory somebody else prepared ---
#
# Without a usable home the cache lands on a predictable name in a shared tempdir, so the
# directory can be there before this CLI ever runs. These tests use `XDG_CACHE_HOME`
# because the check does not care which of the three answers picked the path.


def _hijacked(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """A symlink where the cache directory belongs, pointing at somebody else's directory."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    elsewhere = tmp_path / "attacker"
    elsewhere.mkdir()
    (tmp_path / "xdg").mkdir()
    (tmp_path / "xdg" / "zad").symlink_to(elsewhere)
    return elsewhere


def test_a_symlinked_cache_directory_is_no_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """`mkdir(exist_ok=True)` plus `is_dir()` accepts a symlink. `lstat` is why this one does not."""
    elsewhere = _hijacked(monkeypatch, tmp_path)

    assert cache_file("version-check.json") is None
    assert list(elsewhere.iterdir()) == []


def test_nothing_is_written_through_a_hijacked_cache_directory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    elsewhere = _hijacked(monkeypatch, tmp_path)

    update._write_state({"latest": "9.9.9"})

    assert list(elsewhere.iterdir()) == []


def test_a_planted_release_number_is_not_read_back(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The reader is the half that matters: planting happens before the victim ever runs."""
    elsewhere = _hijacked(monkeypatch, tmp_path)
    (elsewhere / "version-check.json").write_text('{"latest": "666.0.0"}')

    assert update.cached_latest() is None


def test_the_catalog_and_the_spec_refuse_the_same_directory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A planted catalog decides what `service list` shows; a planted spec, who gets `rollout`."""
    _hijacked(monkeypatch, tmp_path)

    assert registry.cache_path("https://api.example.com/api") is None
    assert spec.live_cache_path("https://api.example.com/api") is None


def test_a_directory_owned_by_another_user_is_no_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    (tmp_path / "xdg" / "zad").mkdir(parents=True)
    monkeypatch.setattr(os, "geteuid", lambda: os.stat(tmp_path / "xdg" / "zad").st_uid + 1)

    assert cache_file("version-check.json") is None


@pytest.mark.parametrize("mode", [0o777, 0o770, 0o702])
def test_a_cache_directory_others_may_write_to_is_no_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mode: int
) -> None:
    """Ours, but open: anyone who can write there can plant the same files."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    directory = tmp_path / "xdg" / "zad"
    directory.mkdir(parents=True)
    directory.chmod(mode)

    assert cache_file("version-check.json") is None


def test_a_file_where_the_cache_directory_belongs_is_no_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    (tmp_path / "xdg").mkdir()
    (tmp_path / "xdg" / "zad").write_text("not a directory")

    assert cache_file("version-check.json") is None


def test_the_cache_directory_is_created_for_this_user_only(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))

    path = cache_file("version-check.json")

    assert path == tmp_path / "xdg" / "zad" / "version-check.json"
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700


def test_a_cache_directory_we_made_is_used_again(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The second run has to find its own cache, or the check costs every run its cache."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    update._write_state({"latest": "9.9.9"})

    assert update.cached_latest() == "9.9.9"


def test_without_geteuid_a_symlink_is_still_refused(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Windows has no uid and no real mode bits, so only the symlink half of the check runs."""
    _hijacked(monkeypatch, tmp_path)
    monkeypatch.delattr(os, "geteuid", raising=False)

    assert cache_file("version-check.json") is None


def test_without_geteuid_an_existing_directory_is_used(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Every Windows directory reads as group writable, which may not disable the cache."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    directory = tmp_path / "xdg" / "zad"
    directory.mkdir(parents=True)
    directory.chmod(0o777)
    monkeypatch.delattr(os, "geteuid", raising=False)

    assert cache_file("x") == directory / "x"


def test_the_tempdir_fallback_refuses_a_name_that_was_already_taken(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The reported case end to end: no home, a shared tempdir, and the name already there."""
    shared = tmp_path / "shared"
    shared.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(shared))
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    _home_raises(monkeypatch, RuntimeError("no home"))
    elsewhere = tmp_path / "attacker"
    elsewhere.mkdir()
    (shared / cache_dir().name).symlink_to(elsewhere)
    (elsewhere / "version-check.json").write_text('{"latest": "666.0.0"}')

    assert update.cached_latest() is None
    update._write_state({"latest": "9.9.9"})
    assert list(elsewhere.iterdir()) == [elsewhere / "version-check.json"]
    assert json.loads((elsewhere / "version-check.json").read_text()) == {"latest": "666.0.0"}
