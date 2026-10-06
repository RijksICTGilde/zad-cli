"""Where this CLI keeps its cache: one answer for the catalog, the spec and the release check."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

__all__ = ["cache_dir"]


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
        # The tempdir is shared: a directory owned by another user is not one to write in.
        uid = getattr(os, "geteuid", lambda: 0)()
        return Path(tempfile.gettempdir()) / f"zad-cache-{uid}"
