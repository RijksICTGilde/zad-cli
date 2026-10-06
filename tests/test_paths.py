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
import time
from pathlib import Path

import httpx
import pytest
import respx
from typer.testing import CliRunner

from zad_cli import __version__, envfile, update
from zad_cli.api import registry, spec
from zad_cli.cli import app
from zad_cli.paths import cache_dir, cache_file

#: Any URL will do: what is under test is the cache directory, not the API behind it.
CACHE_TEST_API = "https://api.example.com/api"

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
    """Open as well as somebody else's, which is the combination narrowing may not rescue.

    0777 is the mode the narrowing accepts from a directory of our own, so ownership has to
    be weighed first. And a directory we refuse is one we leave alone: changing its mode
    would be writing to a place we just decided is not ours.
    """
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    directory = tmp_path / "xdg" / "zad"
    directory.mkdir(parents=True)
    directory.chmod(0o777)
    monkeypatch.setattr(os, "geteuid", lambda: os.stat(directory).st_uid + 1)

    assert cache_file("version-check.json") is None
    assert stat.S_IMODE(directory.stat().st_mode) == 0o777


@pytest.mark.parametrize("mode", [0o777, 0o775, 0o770, 0o702])
def test_a_cache_directory_others_may_write_to_is_replaced(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mode: int
) -> None:
    """Ours, but open: anyone who may write there plants the same files, so it does not stay.

    0775 is what an earlier zadctl left behind under `umask 002`, which `/etc/login.defs`
    makes the default wherever `USERGROUPS_ENAB yes` is on. Refusing that one would cost such
    a user the catalog and the spec on every command, and turn a daily release check into a
    request per command.
    """
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    directory = tmp_path / "xdg" / "zad"
    directory.mkdir(parents=True)
    directory.chmod(mode)

    assert cache_file("version-check.json") == directory / "version-check.json"
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700


def test_a_cache_directory_that_cannot_be_replaced_is_no_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Replacing it is the whole reason the open directory is accepted, so a failed one refuses.

    Twice, and the mode after it, because the refusal has to outlive this command: one that
    gave up halfway with the mode already at 0700 would hand the next run a directory of our
    own, still holding whatever the open window put there.
    """
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    directory = tmp_path / "xdg" / "zad"
    directory.mkdir(parents=True)
    (directory / "version-check.json").write_text('{"latest": "666.0.0"}')
    directory.chmod(0o777)

    def _refuse(*args: object, **kwargs: object) -> None:
        raise PermissionError("read-only file system")

    monkeypatch.setattr(os, "rename", _refuse)

    assert cache_file("version-check.json") is None
    assert update.cached_latest() is None
    assert cache_file("version-check.json") is None
    assert stat.S_IMODE(directory.stat().st_mode) == 0o777
    assert json.loads((directory / "version-check.json").read_text()) == {"latest": "666.0.0"}


def test_an_open_caches_contents_go_and_the_stamp_after_it_stays(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The replacement takes the mode away, so what the open window could have planted goes too.

    Two files, because one cannot tell replacing the directory from dropping the first entry
    found, and whoever had the window planted every cache that lives here at once: a stamp
    only costs a request, a catalog decides which paths `service config set` writes.

    And the run that narrows is the one that fills the cache again: a release number the
    next command cannot read is a thread and a request to github.com per command, which is
    the reason the directory is narrowed instead of refused.
    """
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    directory = tmp_path / "xdg" / "zad"
    directory.mkdir(parents=True)
    planted_catalog = registry.cache_path(CACHE_TEST_API)
    assert planted_catalog is not None, "a directory of our own has to answer with a path"
    planted_catalog.write_text('{"fetched_at": 1e12, "payload": {"services": []}}')
    (directory / "version-check.json").write_text('{"latest": "666.0.0"}')
    directory.chmod(0o775)

    assert update.cached_latest() is None
    assert list(directory.iterdir()) == []
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700

    update._write_state({"latest": "9.9.9", "checked_at": time.time()})

    assert update.cached_latest() == "9.9.9"
    assert not update._stale(update._read_state().get("checked_at"), 86400)


def test_an_entry_an_unlink_would_leave_behind_goes_too(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A directory is the entry a sweep per entry gives up on, and the planter picks the order.

    The second read is the assertion that matters: by then the mode is 0700, so a run that
    swept what it could and narrowed anyway answers with the number that survived. Measured
    on the state before this: run 1 refused, runs 2 and 3 answered `666.0.0`.
    """
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    directory = tmp_path / "xdg" / "zad"
    directory.mkdir(parents=True)
    # Sorted first, which is the order `os.scandir` reports on the filesystems that sort.
    (directory / "aaa-a-directory").mkdir()
    (directory / "version-check.json").write_text('{"latest": "666.0.0", "checked_at": 1e12}')
    directory.chmod(0o775)

    assert update.cached_latest() is None
    assert update.cached_latest() is None
    assert list(directory.iterdir()) == []
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    # The directory that was moved aside is gone as well, rather than left next to the cache.
    assert [child.name for child in (tmp_path / "xdg").iterdir()] == ["zad"]


def test_a_cache_directory_that_cannot_be_remade_is_no_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The second half of the replacement: moved aside, and then no fresh directory.

    A caller on its way to a cache gets the same `None` as from any other refusal, and the
    directory that was moved aside is cleaned up rather than left behind as a second copy.
    """
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    directory = tmp_path / "xdg" / "zad"
    directory.mkdir(parents=True)
    (directory / "version-check.json").write_text('{"latest": "666.0.0"}')
    directory.chmod(0o775)
    real_mkdir = os.mkdir

    def _refuse_once_it_is_gone(path: object, *args: object, **kwargs: object) -> None:
        if Path(str(path)) == directory and not directory.exists():
            raise PermissionError("read-only file system")
        return real_mkdir(path, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(os, "mkdir", _refuse_once_it_is_gone)

    assert cache_file("version-check.json") is None
    assert list((tmp_path / "xdg").iterdir()) == []


def test_a_cache_directory_others_may_only_read_is_left_alone(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Writing is what plants a file, so a group that may only look keeps its mode.

    `umask 027` makes 0750 the everyday case, and narrowing a directory nobody else may
    write to would change a mode for nothing.
    """
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    directory = tmp_path / "xdg" / "zad"
    directory.mkdir(parents=True)
    directory.chmod(0o750)

    assert cache_file("version-check.json") == directory / "version-check.json"
    assert stat.S_IMODE(directory.stat().st_mode) == 0o750


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
    """Every Windows directory reads as group writable, which may not disable the cache.

    Nor narrow it: the mode there says nothing about who may write, so acting on it would
    rewrite the mode of the user's cache directory on every command for no gain.
    """
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    directory = tmp_path / "xdg" / "zad"
    directory.mkdir(parents=True)
    directory.chmod(0o777)
    monkeypatch.delattr(os, "geteuid", raising=False)

    assert cache_file("x") == directory / "x"
    assert stat.S_IMODE(directory.stat().st_mode) == 0o777


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


# --- A refused cache is a miss, and a miss breaks nothing ---
#
# `cache_file()` answers `None` for a directory that is not ours, so every reader and
# writer of a cache meets that `None`. These drive the whole load path rather than the
# path builder: a guard that is missing there turns a hijacked directory into a traceback
# on a command that would otherwise have fetched.


@respx.mock
def test_the_catalog_is_fetched_live_when_the_cache_is_refused(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """No cache to read and none to write, so both calls go out and neither fails."""
    elsewhere = _hijacked(monkeypatch, tmp_path)
    monkeypatch.delenv("ZAD_CATALOG_OFFLINE", raising=False)
    route = respx.get(f"{CACHE_TEST_API}/v2/services").mock(
        return_value=httpx.Response(200, json=json.loads(registry.SNAPSHOT_PATH.read_text()))
    )

    first = registry.load_catalog(CACHE_TEST_API)
    second = registry.load_catalog(CACHE_TEST_API)

    assert first.source == "live"
    assert "postgresql-database" in first.names()
    # "cache" would mean it read through the hijacked directory; a second fetch is the price.
    assert second.source == "live"
    assert route.call_count == 2
    assert list(elsewhere.iterdir()) == []


@respx.mock
def test_the_live_spec_is_fetched_when_the_cache_is_refused(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The spec decides which operations get `rollout`, so a refused cache may not stop it."""
    elsewhere = _hijacked(monkeypatch, tmp_path)
    monkeypatch.delenv("ZAD_CATALOG_OFFLINE", raising=False)
    route = respx.get(spec.live_url(CACHE_TEST_API)).mock(return_value=httpx.Response(200, json=spec.load_spec()))
    spec.load_live_spec.cache_clear()

    try:
        loaded = spec.load_live_spec(CACHE_TEST_API)
    finally:
        spec.load_live_spec.cache_clear()

    assert loaded is not None
    assert "paths" in loaded
    assert route.called
    assert list(elsewhere.iterdir()) == []


@respx.mock
def test_a_command_still_answers_with_a_hijacked_cache_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The promise at command level: a cache nobody may use is a miss, not a failure."""
    _hijacked(monkeypatch, tmp_path)
    monkeypatch.delenv("ZAD_CATALOG_OFFLINE", raising=False)
    monkeypatch.setenv("ZAD_API_URL", CACHE_TEST_API)
    respx.get(f"{CACHE_TEST_API}/v2/services").mock(
        return_value=httpx.Response(200, json=json.loads(registry.SNAPSHOT_PATH.read_text()))
    )

    result = CliRunner().invoke(app, ["service", "list"])

    assert result.exit_code == 0, result.output
    assert "postgresql-database" in result.output


def test_a_cache_directory_that_cannot_be_created_is_no_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """`XDG_CACHE_HOME` under a regular file: `mkdir` fails before anything exists to check.

    Not every refusal comes from a directory that is already there. One that cannot be made
    at all has to answer the same way, because the caller is on its way to a cache.
    """
    blocker = tmp_path / "a-file"
    blocker.write_text("not a directory")
    monkeypatch.setenv("XDG_CACHE_HOME", str(blocker / "cache"))

    assert cache_file("version-check.json") is None
    # And the two halves that would otherwise meet the failure: neither raises.
    update._write_state({"latest": "9.9.9"})
    assert update.cached_latest() is None


def test_no_cache_path_is_built_around_the_gate() -> None:
    """Every cache file is asked for with `cache_file()`, which is where the refusal sits.

    A fourth cache that composes `cache_dir() / name` itself reads straight through a
    directory somebody else prepared, which is what this whole section exists to stop. The
    list comes from the tree, so a module nobody thought of here is covered too.
    """
    source = Path(__file__).resolve().parent.parent / "src"
    offenders = [
        f"{module.relative_to(source)}:{number}"
        for module in sorted(source.rglob("*.py"))
        if module.name != "paths.py"
        for number, line in enumerate(module.read_text().splitlines(), 1)
        if "cache_dir()" in line
    ]
    assert offenders == []
