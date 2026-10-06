"""Where this CLI keeps its cache, answered when it is asked and not when it is imported.

One function for all three caches (the service catalog, the OpenAPI spec and the release
check), so a machine that has no usable home directory does not get three different answers
to the same question.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

__all__ = ["cache_dir"]


def cache_dir() -> Path:
    """`$XDG_CACHE_HOME/zad`, else `~/.cache/zad`, else a per-user directory in the tempdir.

    Resolved on every call rather than at import. As a module constant this was computed
    while `zad_cli` was being imported, so a container running under a UID that is in no
    passwd file -- where `Path.home()` raises -- failed every command with a traceback,
    including the ones that never read a cache. Nothing here is important enough for that:
    a cache that cannot be found is a cache miss.
    """
    xdg = (os.environ.get("XDG_CACHE_HOME") or "").strip()
    if xdg:
        return Path(xdg) / "zad"
    try:
        return Path.home() / ".cache" / "zad"
    except (RuntimeError, OSError):
        # Per user: the tempdir is shared on a multi-user machine, and a directory owned by
        # somebody else is one this CLI cannot write to.
        uid = getattr(os, "geteuid", lambda: 0)()
        return Path(tempfile.gettempdir()) / f"zad-cache-{uid}"
