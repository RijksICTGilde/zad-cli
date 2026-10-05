"""Whether a newer `zadctl` exists, and how to install it.

Not under ``api/``: that package is the Operations Manager API, and this talks to GitHub.

The check is one `HEAD` on the release page's `latest` redirect, which answers with the tag
in its `Location` header. Not `api.github.com`: that allows 60 unauthenticated requests per
hour per IP, and one office NAT shares them, so a CLI that ran it on every invocation would
start handing people rate-limit errors for a courtesy. The redirect has no such limit and
needs no token.

Everything here is best effort. A version check may never be the reason a command fails,
prints a traceback, or waits: the fetch runs on a daemon thread, the notice is joined for a
fraction of a second after the command has already said what it had to say, and a cache that
cannot be written is not an error.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import httpx

from zad_cli import __version__

__all__ = [
    "CACHE_DIR",
    "DEFAULT_INTERVAL",
    "DOWNLOAD_BASE",
    "LATEST_URL",
    "STATE_FILE",
    "VALID_MODES",
    "UpgradeError",
    "asset_name",
    "asset_url",
    "cached_latest",
    "fetch_latest",
    "finish",
    "install_kind",
    "is_newer",
    "parse_version",
    "run_upgrade",
    "start",
    "suppressed",
]

# The same directory ``api/registry.py`` caches the service catalog in, spelled out here
# rather than imported from it: a test monkeypatches this module's own copy, and
# ``Path.home()`` is not redirected in the suite.
CACHE_DIR = Path.home() / ".cache" / "zad"
STATE_FILE = "version-check.json"

LATEST_URL = "https://github.com/RijksICTGilde/zad-cli/releases/latest"
DOWNLOAD_BASE = "https://github.com/RijksICTGilde/zad-cli/releases/download"
RELEASES_URL = "https://github.com/RijksICTGilde/zad-cli/releases"

DEFAULT_INTERVAL = 24 * 60 * 60

VALID_MODES = frozenset({"off", "notify", "prompt"})

# platform.machine() spells the same two architectures five ways between macOS, Linux and
# Windows; the release workflow builds for two.
_ARCHITECTURES = {
    "x86_64": "amd64",
    "amd64": "amd64",
    "x86-64": "amd64",
    "arm64": "arm64",
    "aarch64": "arm64",
}

# The labels .github/workflows/release-binaries.yml attaches to the archives.
_PLATFORM_LABELS = frozenset({"linux_amd64", "linux_arm64", "darwin_arm64", "darwin_amd64", "windows_amd64"})


class UpgradeError(RuntimeError):
    """An upgrade that cannot be done here, with a message saying what to do instead."""


# ---------------------------------------------------------------------------
# Versions


def parse_version(raw: str) -> tuple[int, ...]:
    """A version as something comparable. Anything unparseable sorts low rather than raising.

    A pre-release suffix is cut off, so `0.14.0-rc1` and `0.14.0` compare equal and
    :func:`is_newer` then calls the pre-release not newer. `releases/latest` never points at
    a pre-release, so this only has to not crash on one.
    """
    text = str(raw).strip().lstrip("vV")
    for separator in ("-", "+"):
        text = text.split(separator, 1)[0]
    parts: list[int] = []
    for part in text.split("."):
        try:
            parts.append(int(part))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def is_newer(latest: str, current: str) -> bool:
    """Whether `latest` is a release above `current`."""
    left, right = parse_version(latest), parse_version(current)
    width = max(len(left), len(right))
    # Padded, so 0.14 and 0.14.0 are the same version rather than one being below the other.
    return left + (0,) * (width - len(left)) > right + (0,) * (width - len(right))


def release_tag(version: str) -> str:
    """The git tag a version is released under: `0.13.4` and `v0.13.4` both give `v0.13.4`."""
    return "v" + str(version).strip().lstrip("vV")


# ---------------------------------------------------------------------------
# State


def _state_path() -> Path:
    return CACHE_DIR / STATE_FILE


def _read_state() -> dict[str, object]:
    """The stamps from the last check. Missing, unreadable or malformed is an empty one."""
    try:
        data = json.loads(_state_path().read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_state(state: dict[str, object]) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _state_path().write_text(json.dumps(state))
    except OSError:
        # A cache we cannot write is not a reason to fail the command.
        pass


def cached_latest() -> str | None:
    """The last release this CLI saw, from the state file. No network."""
    latest = _read_state().get("latest")
    return str(latest) if latest else None


def _stale(stamp: object, interval: float) -> bool:
    try:
        return time.time() - float(stamp or 0) >= interval
    except (TypeError, ValueError):
        return True


# ---------------------------------------------------------------------------
# The check


def fetch_latest(*, timeout: float = 2.0) -> str | None:
    """The newest released version, off the `releases/latest` redirect. None when it does not.

    A 200, or a redirect without a release tag in it, means GitHub answered something other
    than the release page. That is not an error worth reporting on an unrelated command.
    """
    response = httpx.head(LATEST_URL, follow_redirects=False, timeout=timeout)
    location = response.headers.get("location") or ""
    marker = "/releases/tag/"
    if marker not in location:
        return None
    tag = location.rsplit(marker, 1)[-1].strip().strip("/")
    return tag.lstrip("vV") or None


def _argv_output_format() -> str:
    """The output format without a parsed context, for a caller that has no settings.

    Same order ``Settings.resolve`` uses, minus the layers that need Click: a flag on argv,
    then the environment, then the `.env.zadctl`.
    """
    argv = sys.argv[1:]
    if "--json" in argv:
        return "json"
    if "--yaml" in argv:
        return "yaml"
    for index, arg in enumerate(argv):
        if arg in ("--output", "-o") and index + 1 < len(argv):
            return argv[index + 1].strip().lower()
        if arg.startswith(("--output=", "-o=")):
            return arg.split("=", 1)[1].strip().lower()
    from zad_cli import envfile

    return (os.environ.get("ZAD_OUTPUT_FORMAT") or envfile.get("ZAD_OUTPUT_FORMAT") or "table").strip().lower()


def suppressed(output_format: str | None = None) -> str | None:
    """Why the check is off without anyone configuring it, or None.

    The reason is a string rather than a bool so ``zadctl config list`` and a test can say
    *which* rule won. `output_format` is passed in where it has already been resolved; left
    out it is read off argv and the environment, because :func:`finish` runs after the
    context is gone.
    """
    # A completion runs for every keystroke and prints a word list; a notice in there ends
    # up as a suggestion. Click spells the variable `_<PROG>_COMPLETE`, and this program
    # answers to two names.
    for name in os.environ:
        if name.startswith("_ZAD") and name.endswith("_COMPLETE"):
            return f"a shell completion is running ({name})"
    for name in ("CI", "GITHUB_ACTIONS"):
        if os.environ.get(name):
            return f"{name} is set"
    if os.environ.get("ZAD_CATALOG_OFFLINE"):
        return "ZAD_CATALOG_OFFLINE is set"
    if not sys.stderr.isatty():
        return "stderr is not a terminal"
    fmt = (output_format or _argv_output_format()).strip().lower()
    if fmt in ("json", "yaml"):
        return f"output format is {fmt}"
    return None


@dataclass
class _Pending:
    """A check in flight: the thread, what it found, and what to do with it."""

    mode: str
    interval: float
    thread: threading.Thread | None = None
    latest: str | None = None
    failed: bool = False

    def run(self) -> None:
        try:
            self.latest = fetch_latest()
        except Exception:  # noqa: BLE001 - no fetch of a courtesy may surface anywhere
            self.failed = True


_pending: _Pending | None = None


def start(settings: object) -> None:
    """Begin the check, if it is due, and return immediately.

    The result lands in a module global rather than on ``ctx.obj``: ``main()`` has no
    context object, and the notice has to be printed after the command is done with stdout.
    """
    global _pending

    mode = str(getattr(settings, "version_check", "notify") or "notify").lower()
    if mode not in ("notify", "prompt"):
        return
    if suppressed(getattr(settings, "output_format", None)):
        return
    interval = float(getattr(settings, "version_check_interval", DEFAULT_INTERVAL) or DEFAULT_INTERVAL)
    if interval <= 0:
        return
    if not _stale(_read_state().get("checked_at"), interval):
        return

    pending = _Pending(mode=mode, interval=interval)
    pending.thread = threading.Thread(target=pending.run, daemon=True, name="zad-version-check")
    try:
        pending.thread.start()
    except RuntimeError:
        # A machine that will not give us a thread still has a command to run.
        return
    _pending = pending


def finish(*, mode: str | None = None, timeout: float = 0.3) -> None:
    """Say so when a newer release exists. Never raises, never waits long.

    `mode` defaults to what :func:`start` was given, because ``main()`` is where this has to
    be called from and ``main()`` has no settings.

    A thread that is not done inside `timeout` is left alone and nothing is stamped: the
    next run tries again, which is cheaper than making every command wait for GitHub.
    """
    global _pending

    pending, _pending = _pending, None
    if pending is None or pending.thread is None:
        return
    effective = (mode or pending.mode).lower()
    if effective not in ("notify", "prompt"):
        return
    try:
        pending.thread.join(timeout)
        if pending.thread.is_alive() or pending.failed or not pending.latest:
            return
        latest = pending.latest
        state = _read_state()
        state["checked_at"] = time.time()
        state["latest"] = latest
        tell = is_newer(latest, __version__) and _stale(state.get("notified_at"), pending.interval)
        if tell:
            state["notified_at"] = time.time()
        _write_state(state)
        if tell:
            _notify(latest, mode=effective)
    except Exception:  # noqa: BLE001 - a courtesy that throws is worse than one that is silent
        pass


def _warn(message: str) -> None:
    """One line on stderr, the way the rest of the CLI puts a caveat there."""
    try:
        from zad_cli.output.formatter import OutputFormatter

        OutputFormatter(fmt="table").render_warning_text(message)
    except Exception:  # noqa: BLE001 - a notice is not worth an import error
        print(message, file=sys.stderr)


def _notify(latest: str, *, mode: str) -> None:
    _warn(f"zadctl {latest} is available (you have {__version__}). Upgrade: zadctl upgrade")
    _warn("Turn this off: zadctl config set version_check off")
    if mode != "prompt" or not (sys.stdin.isatty() and sys.stderr.isatty()):
        return
    # The question goes to stderr with the notice it belongs to: stdout is the command's
    # answer, and a half-written prompt in a piped document is a corrupted document.
    print("Upgrade now? [y/N] ", end="", file=sys.stderr, flush=True)
    try:
        answer = sys.stdin.readline().strip().lower()
    except (OSError, ValueError):
        return
    if answer not in ("y", "yes"):
        return
    try:
        result = run_upgrade(release_tag(latest), log=lambda line: print(line, file=sys.stderr))
    except UpgradeError as e:
        _warn(str(e))
        return
    _warn(f"Now running {result.get('version', latest)}.")


# ---------------------------------------------------------------------------
# Where this copy came from


def executable_path() -> Path | None:
    """The `zadctl` the shell just ran, through symlinks. None when it cannot be found."""
    candidates = [sys.argv[0] if sys.argv else "", shutil.which("zadctl") or ""]
    for candidate in candidates:
        if not candidate:
            continue
        try:
            path = Path(candidate).resolve()
        except OSError:
            continue
        if path.exists():
            return path
    return None


def _source_checkout() -> bool:
    """Whether `zad_cli` is being imported from a git working copy of this repo."""
    module = Path(__file__).resolve()
    if module.parent.parent.name != "src":
        return False
    return (module.parent.parent.parent / ".git").exists()


def install_kind() -> str:
    """How this copy was installed: binary, uv-tool, pipx, pip or source.

    The binary test is Nuitka's own: it defines ``__compiled__`` in every module it
    compiles, so its presence here is the build saying what it is.

    A source checkout is recognised before pip, not after: a working copy installed in
    editable mode into its own venv matches both, and `git pull` is the honest answer there.
    """
    if "__compiled__" in globals():
        return "binary"
    paths = [str(sys.executable)]
    located = executable_path()
    if located is not None:
        paths.append(str(located))
    haystack = " ".join(paths).replace("\\", "/")
    if "uv/tools" in haystack:
        return "uv-tool"
    if "pipx" in haystack:
        return "pipx"
    if _source_checkout():
        return "source"
    return "pip"


def python_upgrade_command(kind: str | None = None, *, tag: str | None = None) -> list[str]:
    """The command that upgrades a Python install. Empty for a binary or a working copy.

    With a `tag` the same package managers install that exact release, which is what makes
    ``--to`` able to go back as well as forward.
    """
    kind = kind or install_kind()
    spec = "git+https://github.com/RijksICTGilde/zad-cli.git"
    if tag:
        spec = f"{spec}@{release_tag(tag)}"
    if kind == "uv-tool":
        if tag:
            return ["uv", "tool", "install", "--force", spec]
        return ["uv", "tool", "upgrade", "zad-cli"]
    if kind == "pipx":
        if tag:
            return ["pipx", "install", "--force", spec]
        return ["pipx", "upgrade", "zad-cli"]
    if kind == "pip":
        return [sys.executable, "-m", "pip", "install", "--upgrade", spec]
    return []


# ---------------------------------------------------------------------------
# Release assets


def platform_label() -> str | None:
    """This machine's label in the release assets, or None when nothing is built for it."""
    system = platform.system().strip().lower()
    arch = _ARCHITECTURES.get(platform.machine().strip().lower())
    if not arch:
        return None
    label = f"{system}_{arch}"
    return label if label in _PLATFORM_LABELS else None


def binary_name() -> str:
    return "zadctl.exe" if os.name == "nt" else "zadctl"


def asset_name(label: str | None = None) -> str | None:
    """The archive built for this platform. None when there is no build for it."""
    label = label or platform_label()
    if label is None:
        return None
    suffix = ".zip" if label.startswith("windows") else ".tar.gz"
    return f"zadctl_{label}{suffix}"


def asset_url(tag: str, name: str) -> str:
    return f"{DOWNLOAD_BASE}/{release_tag(tag)}/{name}"


def checksums_url(tag: str) -> str:
    return f"{DOWNLOAD_BASE}/{release_tag(tag)}/SHA256SUMS"


def manual_install_hint() -> str:
    """The download line from the README, for when this cannot write the file itself."""
    label = platform_label() or "linux_amd64"
    if label.startswith("windows"):
        return (
            f'Invoke-WebRequest -Uri "{LATEST_URL}/download/zadctl_{label}.zip" '
            '-OutFile "$env:TEMP\\zadctl.zip"; Expand-Archive -Force "$env:TEMP\\zadctl.zip" '
            "-DestinationPath <dir>"
        )
    return f"curl -fsSL {LATEST_URL}/download/zadctl_{label}.tar.gz | tar -xzf - -C ~/.local/bin zadctl"


def _fetch(url: str, *, timeout: float) -> bytes:
    response = httpx.get(url, follow_redirects=True, timeout=timeout)
    response.raise_for_status()
    return response.content


def _digest_for(sums: str, name: str) -> str | None:
    """The sha256 `SHA256SUMS` lists for one filename. None when it lists none."""
    for line in sums.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[-1].lstrip("*") == name:
            return parts[0].strip().lower()
    return None


def _member(archive: bytes, name: str) -> bytes:
    """The binary inside the archive. One member, as the release packs it."""
    import io
    import tarfile
    import zipfile

    wanted = binary_name()
    if name.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            for entry in bundle.namelist():
                if Path(entry).name in (wanted, "zadctl.exe", "zadctl"):
                    return bundle.read(entry)
        raise UpgradeError(f"{name} does not contain {wanted}.")
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as bundle:
        for entry in bundle.getmembers():
            if entry.isfile() and Path(entry.name).name in (wanted, "zadctl.exe", "zadctl"):
                extracted = bundle.extractfile(entry)
                if extracted is not None:
                    return extracted.read()
    raise UpgradeError(f"{name} does not contain {wanted}.")


def ensure_writable(target: Path) -> None:
    """Refuse early when the file cannot be replaced, naming the path and the manual way.

    No `sudo` attempt: a binary under a root-owned prefix was put there by someone who
    decided that, and silently escalating to overwrite it is not this command's call.
    """
    directory = target.parent
    if not os.access(directory, os.W_OK):
        raise UpgradeError(
            f"{directory} is not writable, so {target.name} cannot be replaced here.\n"
            f"  Install it somewhere of your own instead: {manual_install_hint()}"
        )
    if target.exists() and not os.access(target, os.W_OK):
        raise UpgradeError(
            f"{target} is not writable.\n  Install it somewhere of your own instead: {manual_install_hint()}"
        )


def install_archive(archive: bytes, *, name: str, sums: str, target: Path) -> None:
    """Verify `archive` against `sums` and put the binary it holds at `target`.

    The verification is not optional: without it this command is a download-and-execute
    mechanism, and a mirror or proxy that changed the bytes would be invisible. So a
    mismatch, or a `SHA256SUMS` that does not mention this file at all, aborts before
    anything is unpacked.
    """
    import tempfile

    expected = _digest_for(sums, name)
    if expected is None:
        raise UpgradeError(f"SHA256SUMS lists no checksum for {name}; not installing an unverified binary.")
    actual = hashlib.sha256(archive).hexdigest()
    if actual != expected:
        raise UpgradeError(
            f"{name} does not match its published checksum, so it was not installed.\n"
            f"  expected {expected}\n  received {actual}"
        )

    payload = _member(archive, name)
    # Windows cannot overwrite a running .exe, so the old one is moved aside first. A
    # leftover from an earlier upgrade is cleared here rather than at exit: the process that
    # would have cleaned it up is the one still holding it open.
    aside = target.with_name(target.name + ".old")
    with contextlib.suppress(OSError):
        aside.unlink(missing_ok=True)

    # In the target's own directory, so the replace stays on one filesystem and is atomic.
    with tempfile.NamedTemporaryFile(dir=target.parent, prefix=f".{target.name}.", delete=False) as handle:
        handle.write(payload)
        temporary = Path(handle.name)
    try:
        os.chmod(temporary, 0o755)
        if os.name == "nt" and target.exists():
            target.rename(aside)
        os.replace(temporary, target)
    except OSError as e:
        temporary.unlink(missing_ok=True)
        raise UpgradeError(f"Could not install {target}: {e}") from e
    # No xattr call on macOS: this file was not downloaded by a browser, so it carries no
    # quarantine flag to remove.


def reported_version(kind: str) -> str:
    """What the upgraded install says it is, by asking it."""
    if kind == "pip":
        command = [sys.executable, "-m", "zad_cli", "--version"]
    else:
        located = shutil.which("zadctl")
        if not located:
            return "unknown"
        command = [located, "--version"]
    try:
        done = subprocess.run(command, capture_output=True, text=True, timeout=60, check=False)  # noqa: S603
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return (done.stdout.strip() or done.stderr.strip() or "unknown").splitlines()[0]


def binary_version(target: Path) -> str:
    """What the binary at `target` reports, so the upgrade can be confirmed rather than assumed."""
    try:
        done = subprocess.run(  # noqa: S603 - the file this command just installed
            [str(target), "--version"], capture_output=True, text=True, timeout=60, check=False
        )
    except (OSError, subprocess.SubprocessError) as e:
        return f"could not run {target}: {e}"
    return (done.stdout.strip() or done.stderr.strip() or "unknown").splitlines()[0]


def upgrade_binary(tag: str, *, target: Path, log: Callable[[str], None], timeout: float = 120.0) -> str:
    """Download, verify and replace the standalone binary. Returns what it reports afterwards."""
    name = asset_name()
    if name is None:
        raise UpgradeError(
            f"No binary is built for {platform.system()} {platform.machine()}. See {RELEASES_URL} for what there is."
        )
    ensure_writable(target)
    url = asset_url(tag, name)
    log(f"Downloading {url}")
    try:
        archive = _fetch(url, timeout=timeout)
        sums = _fetch(checksums_url(tag), timeout=timeout).decode("utf-8", "replace")
    except httpx.HTTPError as e:
        raise UpgradeError(f"Could not download {release_tag(tag)}: {e}") from e
    log("Verifying its checksum")
    install_archive(archive, name=name, sums=sums, target=target)
    return binary_version(target)


def run_upgrade(tag: str | None = None, *, log: Callable[[str], None], timeout: float = 120.0) -> dict[str, str]:
    """Upgrade this copy, however it was installed. Raises :class:`UpgradeError` when it cannot.

    `tag` is a specific release, which is what lets this go back as well as forward. Without
    one a Python install runs its package manager's plain upgrade, and the binary resolves
    the newest release first so it can say afterwards what it installed.
    """
    kind = install_kind()
    if kind == "source":
        raise UpgradeError(
            "This is a git working copy of zad-cli, so there is nothing to download: `git pull` is the upgrade."
        )
    if kind == "binary":
        target = executable_path()
        if target is None:
            raise UpgradeError(f"Could not find the zadctl binary to replace. Reinstall it: {manual_install_hint()}")
        if tag is None:
            try:
                latest = fetch_latest(timeout=10.0)
            except httpx.HTTPError as e:
                raise UpgradeError(f"Could not reach {LATEST_URL}: {e}") from e
            if not latest:
                raise UpgradeError(f"{LATEST_URL} did not name a release; see {RELEASES_URL}.")
            tag = latest
        version = upgrade_binary(tag, target=target, log=log, timeout=timeout)
        return {"install": kind, "tag": release_tag(tag), "target": str(target), "version": version}

    command = python_upgrade_command(kind, tag=tag)
    if not command:
        raise UpgradeError(f"Nothing here knows how to upgrade a {kind} install.")
    if command[0] != sys.executable and shutil.which(command[0]) is None:
        raise UpgradeError(
            f"{command[0]} is not on PATH, so this cannot run the upgrade for you. Run it yourself:\n"
            f"  {' '.join(command)}"
        )
    log(f"Running {' '.join(command)}")
    done = subprocess.run(command, check=False)  # noqa: S603 - the install's own package manager
    if done.returncode != 0:
        raise UpgradeError(f"{command[0]} exited with {done.returncode}; nothing was changed by this command.")
    return {"install": kind, "command": " ".join(command), "version": reported_version(kind)}
