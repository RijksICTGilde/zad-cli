"""Where this CLI keeps its cache: one answer for the catalog, the spec and the release check."""

from __future__ import annotations

import os
import shutil
import stat
import tempfile
from pathlib import Path

__all__ = ["cache_dir", "cache_file"]


def cache_dir() -> Path:
    """`$XDG_CACHE_HOME/zad`, else `~/.cache/zad`, else a per-user directory in the tempdir.

    Asked on every call and not at import: `Path.home()` raises under a UID that is in no
    passwd file, and a cache that cannot be found is a cache miss, not a failed command.
    """
    xdg = (os.environ.get("XDG_CACHE_HOME") or "").strip()
    if xdg:
        return Path(xdg) / "zad"
    try:
        return Path.home() / ".cache" / "zad"
    except (RuntimeError, OSError):
        # The tempdir is shared and this name is predictable, so the uid keeps two users
        # apart and nothing more. `cache_file()` is what refuses a directory already there.
        uid = getattr(os, "geteuid", lambda: 0)()
        return Path(tempfile.gettempdir()) / f"zad-cache-{uid}"


def cache_file(name: str) -> Path | None:
    """`name` inside the cache directory, created 0700, or ``None`` when it is not ours.

    A predictable path in a world-writable tempdir can be planted before this CLI ever
    runs, and reading through it means reading a catalog, a spec or a release number
    somebody else chose. Every caller treats ``None`` as a cache miss.
    """
    directory = cache_dir()
    try:
        directory.parent.mkdir(parents=True, exist_ok=True)
        os.mkdir(directory, 0o700)
    except FileExistsError:
        if not _claim(directory):
            return None
    except OSError:
        return None
    return directory / name


def _claim(directory: Path) -> bool:
    """A real directory of ours, replaced by a fresh 0700 one when it was left open to others.

    `lstat`, because `mkdir(exist_ok=True)` followed by `is_dir()` accepts a symlink, and a
    symlink is how the directory gets taken over. A directory an earlier zadctl made carries
    the user's umask, so under `umask 002` it is 0775: ours to replace, not to refuse. What it
    held is dropped rather than read, which costs one fetch once and nothing after that.
    """
    try:
        info = os.lstat(directory)
    except OSError:
        return False
    if not stat.S_ISDIR(info.st_mode):
        return False
    geteuid = getattr(os, "geteuid", None)
    if geteuid is None:
        # Windows has no uid to compare and gives every directory the same mode bits; the
        # tempdir is per user there, which is the property the check stands in for.
        return True
    if info.st_uid != geteuid():
        return False
    if info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        # Everything the open window could have planted goes, because planting a catalog, a
        # spec or a release number needed exactly that window and nothing else.
        return _renew(directory)
    return True


def _renew(directory: Path) -> bool:
    """Move the open directory aside and put a fresh 0700 one in its place.

    One rename, so no entry survives the sweep and nothing lands in the directory between
    the sweep and the first read. A rename that fails leaves the open directory standing,
    so every later run refuses it too; a mkdir that fails leaves no directory at all, and
    the next command starts on a fresh 0700 one.
    """
    aside = directory.with_name(f"{directory.name}.{os.urandom(8).hex()}.old")
    try:
        os.rename(directory, aside)
    except OSError:
        return False
    try:
        os.mkdir(directory, 0o700)
    except OSError:
        return False
    finally:
        shutil.rmtree(aside, ignore_errors=True)
    return True
