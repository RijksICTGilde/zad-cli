"""Where this CLI keeps its cache: one answer for the catalog, the spec and the release check."""

from __future__ import annotations

import os
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
        if not _ours(directory):
            return None
    except OSError:
        return None
    return directory / name


def _ours(directory: Path) -> bool:
    """A real directory, owned by this user, that nobody else may write to.

    `lstat`, because `mkdir(exist_ok=True)` followed by `is_dir()` accepts a symlink, and a
    symlink is how the directory gets taken over.
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
    return info.st_uid == geteuid() and not info.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
