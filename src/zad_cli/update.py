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

`ZAD_RELEASES_BASE_URL` moves the release page and the downloads, and only to a loopback
address; :func:`releases_base` says why.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import platform
import re
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
from zad_cli.paths import cache_dir

__all__ = [
    "DEFAULT_INTERVAL",
    "DOWNLOAD_BASE",
    "LATEST_URL",
    "MAX_DOWNLOAD",
    "RELEASES_BASE_ENV",
    "RELEASES_URL",
    "STATE_FILE",
    "UpgradeError",
    "ask_version",
    "asset_name",
    "asset_url",
    "binary_version",
    "cached_latest",
    "checksums_url",
    "download_base",
    "ensure_writable",
    "executable_path",
    "fetch_latest",
    "finish",
    "git_spec",
    "install_archive",
    "install_kind",
    "is_newer",
    "latest_url",
    "manual_install_hint",
    "parse_version",
    "platform_label",
    "python_upgrade_command",
    "release_tag",
    "releases_base",
    "reported_version",
    "run_upgrade",
    "start",
    "suppressed",
    "upgrade_binary",
    "valid_version",
]

STATE_FILE = "version-check.json"

RELEASES_URL = "https://github.com/RijksICTGilde/zad-cli/releases"
LATEST_URL = f"{RELEASES_URL}/latest"
DOWNLOAD_BASE = f"{RELEASES_URL}/download"

RELEASES_BASE_ENV = "ZAD_RELEASES_BASE_URL"

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})

DEFAULT_INTERVAL = 24 * 60 * 60

#: A download that is bigger than this is not one of our archives: the binary is about 20 MB,
#: and reading whatever arrives into memory is how a hostile or broken endpoint reaches the
#: OOM killer.
MAX_DOWNLOAD = 300 * 1024 * 1024

# A release version, and nothing else. See :func:`valid_version` for why the shape is pinned.
_VERSION = re.compile(r"\d+(?:\.\d+){0,3}(?:[-+][0-9A-Za-z.]+)?")

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
    """An upgrade that cannot be done here, with a message saying what to do instead.

    `transient` separates the two kinds of refusal the way ``api/errors.py`` does for the API:
    the download or the release page failing is the platform or the network and exits 2, an
    unwritable target or a working copy is this install and exits 1.
    """

    def __init__(self, message: str, *, transient: bool = False) -> None:
        super().__init__(message)
        self.transient = transient


# ---------------------------------------------------------------------------
# Where the releases are read from


#: Overrides already refused, so a refusal is said once and not once per request.
_ignored_bases: set[str] = set()


def _loopback(url: str) -> bool:
    try:
        host = (httpx.URL(url).host or "").strip().lower()
    except (ValueError, TypeError):
        return False
    return host in _LOOPBACK_HOSTS


def releases_base() -> str:
    """Where the releases live: GitHub, or a loopback stand-in an integration test serves.

    Loopback only: `SHA256SUMS` is fetched from the same base as the archive, so a free
    redirect verifies the bytes against a digest from the same hand that wrote them. Anything
    else is refused out loud, since an ignored setting that says nothing reads like a gate
    that held.
    """
    override = (os.environ.get(RELEASES_BASE_ENV) or "").strip().rstrip("/")
    if not override:
        return RELEASES_URL
    if _loopback(override):
        return override
    if override not in _ignored_bases:
        _ignored_bases.add(override)
        _warn(
            f"Ignoring {RELEASES_BASE_ENV}={override}: only a loopback address is accepted, "
            f"because the checksums come from the same host as the archive. Using {RELEASES_URL}."
        )
    return RELEASES_URL


def latest_url() -> str:
    """The redirect that names the newest release."""
    return f"{releases_base()}/latest"


def download_base() -> str:
    """The prefix every release asset hangs under."""
    return f"{releases_base()}/download"


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


def valid_version(raw: str) -> bool:
    """Whether `raw` is shaped like a release version and nothing else.

    A tag arrives from a `Location` header or from ``--to``, and both end up pasted into the
    archive URL *and* into the `SHA256SUMS` URL that is supposed to vouch for it. httpx
    removes `..` segments the way RFC 3986 says to, so a tag of `v1.0.0/../../../evil` moves
    both downloads to a path of someone else's choosing and the checksum gate then compares
    their bytes to their own digest, which passes. A version is digits, dots and at most one
    suffix; checking that here is what keeps a header out of the URL path, and out of the Rich
    markup the notice is rendered as.
    """
    return bool(_VERSION.fullmatch(str(raw).strip().lstrip("vV")))


def release_tag(version: str) -> str:
    """The git tag a version is released under: `0.13.4` and `v0.13.4` both give `v0.13.4`."""
    text = str(version).strip().lstrip("vV")
    if not valid_version(text):
        raise UpgradeError(f"'{version}' is not a release version, so there is no release to download.")
    return "v" + text


# ---------------------------------------------------------------------------
# State


def _state_path() -> Path:
    return cache_dir() / STATE_FILE


def _read_state() -> dict[str, object]:
    """The stamps from the last check. Missing, unreadable or malformed is an empty one."""
    try:
        data = json.loads(_state_path().read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_state(state: dict[str, object]) -> None:
    try:
        cache_dir().mkdir(parents=True, exist_ok=True)
        # Written next to the real name and moved onto it, so a second zadctl reading at the
        # same moment sees either the old file or the new one and never half of one.
        temporary = _state_path().with_suffix(f".{os.getpid()}.tmp")
        temporary.write_text(json.dumps(state))
        os.replace(temporary, _state_path())
    except OSError:
        # A cache we cannot write is not a reason to fail the command.
        pass


def cached_latest() -> str | None:
    """The last release this CLI saw, from the state file. No network."""
    latest = _read_state().get("latest")
    return str(latest) if latest else None


def _stale(stamp: object, interval: float) -> bool:
    try:
        elapsed = time.time() - float(stamp or 0)
    except (TypeError, ValueError):
        return True
    # A stamp in the future is nonsense, not a recent check: a container before NTP has run,
    # or a VM resumed from a snapshot, writes one, and treating it as fresh would switch the
    # feature off until wall time caught up with it. Nonsense behaves like a missing stamp,
    # which is what every other unreadable value here already does.
    return elapsed >= interval or elapsed < 0


# ---------------------------------------------------------------------------
# The check


def fetch_latest(*, timeout: float = 2.0) -> str | None:
    """The newest released version, off the `releases/latest` redirect. None when it does not.

    A 200, a redirect without a release tag in it, or a tag that is not shaped like a version
    means GitHub answered something other than the release page. That is not an error worth
    reporting on an unrelated command, and a header is not trusted far enough to be pasted
    into a download URL unchecked (see :func:`valid_version`).
    """
    response = httpx.head(latest_url(), follow_redirects=False, timeout=timeout)
    location = response.headers.get("location") or ""
    marker = "/releases/tag/"
    if marker not in location:
        return None
    tag = location.rsplit(marker, 1)[-1].strip().strip("/").lstrip("vV")
    return tag if valid_version(tag) else None


def _argv_output_format() -> str:
    """The output format without a resolved ``Settings``, for a bare :func:`suppressed` call.

    Both callers in the CLI pass the format they already resolved; this is what keeps
    ``suppressed()`` answerable without one, which is how the tests ask it and what any later
    caller outside the command tree gets. Same order ``Settings.resolve`` uses, minus the
    layers that need Click: a flag on argv, then the environment, then the `.env.zadctl`.
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
    # `zadctl upgrade` resolves the release itself and says what it did. The thread started
    # before it ran would otherwise land its notice *after* the green success line, naming
    # the command that had just finished, which reads as the upgrade having failed.
    if sys.argv[1:2] == ["upgrade"]:
        return "zadctl upgrade is running"
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
    next run tries again, which is cheaper than making every command wait for GitHub. A
    request that *did* answer stamps `checked_at` even when the answer named no release,
    because that is an answer and not a timeout: behind a captive portal that says 200 to
    everything, not stamping would mean a thread and a request on every single invocation.
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
        if pending.thread.is_alive() or pending.failed:
            return
        latest = pending.latest
        state = _read_state()
        state["checked_at"] = time.time()
        if not latest:
            _write_state(state)
            return
        state["latest"] = latest
        tell = is_newer(latest, __version__) and _stale(state.get("notified_at"), pending.interval)
        if tell:
            state["notified_at"] = time.time()
        _write_state(state)
        if tell:
            _notify(latest, mode=effective)
    # KeyboardInterrupt is in there on purpose: `prompt` mode reads a line from stdin, this
    # whole function runs in `main()`'s `finally`, and Ctrl-C at the question would otherwise
    # replace the exit status of a command that had already succeeded with a traceback.
    except (Exception, KeyboardInterrupt):  # noqa: BLE001 - a courtesy that throws is worse than a silent one
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
    except (OSError, ValueError, EOFError, KeyboardInterrupt):
        # Ctrl-C or Ctrl-D at the question is "no", not a traceback on top of a command that
        # has already done its work.
        return
    if answer not in ("y", "yes"):
        return
    try:
        result = run_upgrade(release_tag(latest), log=lambda line: print(line, file=sys.stderr))
    except UpgradeError as e:
        _warn(str(e))
        return
    except Exception as e:  # noqa: BLE001 - an upgrade that was asked for may not fail silently
        _warn(f"The upgrade did not finish: {e}")
        return
    _warn(f"Now running {result.get('version', latest)}.")


# ---------------------------------------------------------------------------
# Where this copy came from


def executable_path() -> Path | None:
    """The `zadctl` the shell just ran, through symlinks. None when it cannot be found.

    A bare `argv[0]` is skipped rather than resolved: the shell passes the word as typed, so
    `zadctl upgrade` can give `argv[0] == "zadctl"`, which resolves against the *current
    directory*. In a directory that happens to hold a file called `zadctl` (the build script
    in this repo makes one) the upgrade would then write the downloaded binary over that file
    and report success while the install on PATH was never touched.
    """
    candidates = [sys.argv[0] if sys.argv else "", shutil.which("zadctl") or ""]
    for candidate in candidates:
        if not candidate or candidate == os.path.basename(candidate):
            continue
        try:
            path = Path(candidate).resolve()
        except OSError:
            continue
        if path.is_file() and path.name.startswith("zad"):
            return path
    return None


def _source_checkout() -> bool:
    """Whether `zad_cli` is being imported from a git working copy of this repo."""
    module = Path(__file__).resolve()
    if module.parent.parent.name != "src":
        return False
    return (module.parent.parent.parent / ".git").exists()


def install_kind() -> str:
    """How this copy was installed: binary, uv-tool, pipx, pip, source or system.

    The binary test is Nuitka's own: it defines ``__compiled__`` in every module it
    compiles, so its presence here is the build saying what it is.

    A source checkout is recognised before pip, not after: a working copy installed in
    editable mode into its own venv matches both, and `git pull` is the honest answer there.

    `pip` is the fallback only inside a virtual environment. A zadctl that lives in the
    system interpreter is `system`, and nothing is upgraded for it: on an externally managed
    Python a `pip install --upgrade` is a PEP 668 error at best, and a write into a directory
    the package manager owns at worst. The four named kinds own their own install; a distro
    or Homebrew Python does not.
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
    return "pip" if sys.prefix != sys.base_prefix else "system"


def git_spec(tag: str | None = None) -> str:
    """What the package managers install from: this repo, at a tag when one is named."""
    spec = "git+https://github.com/RijksICTGilde/zad-cli.git"
    return f"{spec}@{release_tag(tag)}" if tag else spec


def python_upgrade_command(kind: str | None = None, *, tag: str | None = None) -> list[str]:
    """The command that upgrades a Python install. Empty for a binary, a working copy or system.

    With a `tag` the same package managers install that exact release, which is what makes
    ``--to`` able to go back as well as forward.
    """
    kind = kind or install_kind()
    spec = git_spec(tag)
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
    return f"{download_base()}/{release_tag(tag)}/{name}"


def checksums_url(tag: str) -> str:
    return f"{download_base()}/{release_tag(tag)}/SHA256SUMS"


def manual_install_hint() -> str:
    """The download line from the README, for when this cannot write the file itself.

    No fabricated label when nothing is built for this machine: a curl line for an archive
    that does not exist is worse than the sentence naming the release page.
    """
    label = platform_label()
    if label is None:
        return f"See {RELEASES_URL} for what is built."
    if label.startswith("windows"):
        return (
            f'Invoke-WebRequest -Uri "{LATEST_URL}/download/zadctl_{label}.zip" '
            '-OutFile "$env:TEMP\\zadctl.zip"; Expand-Archive -Force "$env:TEMP\\zadctl.zip" '
            "-DestinationPath <dir>"
        )
    return f"curl -fsSL {LATEST_URL}/download/zadctl_{label}.tar.gz | tar -xzf - -C ~/.local/bin zadctl"


def _fetch(url: str, *, timeout: float) -> bytes:
    """One release asset, over https and no larger than :data:`MAX_DOWNLOAD`.

    The scheme is checked *after* the redirects: this is the path that decides what gets
    executed next, and a 30x from https to http would downgrade the very connection that
    carries the checksums the verification rests on. Loopback is the exception: a test server
    on this machine has no certificate, and nothing in between to protect the bytes from.
    """
    with httpx.stream("GET", url, follow_redirects=True, timeout=timeout) as response:
        response.raise_for_status()
        if response.url.scheme != "https" and not _loopback(str(response.url)):
            raise UpgradeError(f"{url} redirected to {response.url.scheme}, which this will not download over.")
        chunks: list[bytes] = []
        size = 0
        for chunk in response.iter_bytes():
            size += len(chunk)
            if size > MAX_DOWNLOAD:
                raise UpgradeError(
                    f"{url} is larger than {MAX_DOWNLOAD // (1024 * 1024)} MB, so it is not one of our archives."
                )
            chunks.append(chunk)
    return b"".join(chunks)


def _digest_for(sums: str, name: str) -> str | None:
    """The sha256 `SHA256SUMS` lists for one filename. None when it lists none."""
    for line in sums.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[-1].lstrip("*") == name:
            return parts[0].strip().lower()
    return None


def _member(archive: bytes, name: str) -> bytes:
    """The binary inside the archive. One member, by the name this platform runs.

    Only that name: a `zadctl.exe` in a tar.gz is a wrongly built release, and installing it
    under the POSIX name would turn that into a binary that only fails when it is run.
    """
    import io
    import tarfile
    import zipfile

    wanted = binary_name()
    try:
        if name.endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
                for entry in bundle.namelist():
                    if Path(entry).name == wanted:
                        return bundle.read(entry)
        else:
            with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as bundle:
                for entry in bundle.getmembers():
                    if entry.isfile() and Path(entry.name).name == wanted:
                        extracted = bundle.extractfile(entry)
                        if extracted is not None:
                            return extracted.read()
    except (tarfile.TarError, zipfile.BadZipFile, OSError, EOFError) as e:
        raise UpgradeError(f"{name} could not be unpacked: {e}", transient=True) from e
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
        raise UpgradeError(
            f"SHA256SUMS lists no checksum for {name}; not installing an unverified binary.", transient=True
        )
    actual = hashlib.sha256(archive).hexdigest()
    if actual != expected:
        raise UpgradeError(
            f"{name} does not match its published checksum, so it was not installed.\n"
            f"  expected {expected}\n  received {actual}",
            transient=True,
        )

    payload = _member(archive, name)
    windows = os.name == "nt"
    # Windows cannot overwrite a running .exe, so the old one is moved aside first. A leftover
    # from an earlier upgrade is cleared here rather than at exit: the process that would have
    # cleaned it up is the one still holding it open. Only on Windows, because nothing else
    # here creates a `.old` and someone else's hand-made backup is not ours to delete.
    aside = target.with_name(target.name + ".old")
    if windows:
        with contextlib.suppress(OSError):
            aside.unlink(missing_ok=True)

    temporary: Path | None = None
    moved_aside = False
    try:
        # In the target's own directory, so the replace stays on one filesystem and is atomic.
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix=f".{target.name}.", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
        os.chmod(temporary, 0o755)
        if windows and target.exists():
            # os.replace, not Path.rename: a `.old` that could not be unlinked above would
            # make the rename itself fail instead of being overwritten.
            os.replace(target, aside)
            moved_aside = True
        os.replace(temporary, target)
        temporary = None
    except OSError as e:
        if moved_aside:
            # The old binary goes back: a failure between the two moves would otherwise leave
            # the machine with a `.old` and no zadctl at all.
            with contextlib.suppress(OSError):
                os.replace(aside, target)
        raise UpgradeError(f"Could not install {target}: {e}") from e
    finally:
        if temporary is not None:
            with contextlib.suppress(OSError):
                temporary.unlink(missing_ok=True)
    # No xattr call on macOS: this file was not downloaded by a browser, so it carries no
    # quarantine flag to remove.


def ask_version(command: list[str], *, timeout: float = 15.0) -> str | None:
    """The first line `command --version` prints, or None when it would not say.

    None rather than a sentence standing in for a version: the caller decides what a silent
    install means, and a string like "could not run ..." reads as a version to everything
    that formats one.
    """
    try:
        done = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)  # noqa: S603
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    reported = done.stdout.strip() or done.stderr.strip()
    return reported.splitlines()[0] if reported else None


def reported_version(kind: str) -> str | None:
    """What the upgraded install says it is, by asking it. None when it will not answer."""
    if kind == "pip":
        command = [sys.executable, "-m", "zad_cli", "--version"]
    else:
        located = shutil.which("zadctl")
        if not located:
            return None
        command = [located, "--version"]
    return ask_version(command)


def binary_version(target: Path) -> str | None:
    """What the binary at `target` reports, so the upgrade can be confirmed rather than assumed.

    None is the answer that matters: a wrong-architecture asset, a libc mismatch or a
    truncated download installs fine and then refuses to run, and that may not be reported as
    a successful upgrade.
    """
    return ask_version([str(target), "--version"])


def upgrade_binary(tag: str, *, target: Path, log: Callable[[str], None], timeout: float = 120.0) -> str | None:
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
        raise UpgradeError(f"Could not download {release_tag(tag)}: {e}", transient=True) from e
    log("Verifying its checksum")
    install_archive(archive, name=name, sums=sums, target=target)
    return binary_version(target)


def _run_package_manager(command: list[str], *, log: Callable[[str], None]) -> int:
    """Run the package manager and put every line it prints through `log`.

    Captured rather than inherited: `log` writes to stderr, and stdout belongs to the
    document this command renders there, so `zadctl upgrade -o json` stays parseable.
    """
    try:
        process = subprocess.Popen(  # noqa: S603 - the install's own package manager
            command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
        )
    except (OSError, subprocess.SubprocessError) as e:
        raise UpgradeError(f"Could not run {command[0]}: {e}") from e
    if process.stdout is not None:
        for line in process.stdout:
            log(line.rstrip())
    return process.wait()


def run_upgrade(tag: str | None = None, *, log: Callable[[str], None], timeout: float = 120.0) -> dict[str, str]:
    """Upgrade this copy, however it was installed. Raises :class:`UpgradeError` when it cannot.

    `tag` is a specific release, which is what lets this go back as well as forward. Without
    one a Python install runs its package manager's plain upgrade, and the binary resolves
    the newest release first so it can say afterwards what it installed.

    The returned `version` is what the upgraded install answered when asked. It is absent when
    it would not answer, which the caller has to treat as a failure: the file is already
    replaced at that point, and a binary that cannot run is not an upgrade.
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
                raise UpgradeError(f"Could not reach {latest_url()}: {e}", transient=True) from e
            if not latest:
                raise UpgradeError(f"{latest_url()} did not name a release; see {RELEASES_URL}.", transient=True)
            tag = latest
        version = upgrade_binary(tag, target=target, log=log, timeout=timeout)
        result = {"install": kind, "tag": release_tag(tag), "target": str(target)}
        if version:
            result["version"] = version
        return result

    command = python_upgrade_command(kind, tag=tag)
    if not command:
        if kind == "system":
            raise UpgradeError(
                f"zadctl lives in the system Python at {sys.executable}, which this command does not write to.\n"
                f"  Upgrade it the way it was installed, or install your own copy:\n"
                f"  {sys.executable} -m pip install --user --upgrade {git_spec(tag)}"
            )
        raise UpgradeError(f"Nothing here knows how to upgrade a {kind} install.")
    if command[0] != sys.executable and shutil.which(command[0]) is None:
        raise UpgradeError(
            f"{command[0]} is not on PATH, so this cannot run the upgrade for you. Run it yourself:\n"
            f"  {' '.join(command)}"
        )
    log(f"Running {' '.join(command)}")
    returncode = _run_package_manager(command, log=log)
    if returncode != 0:
        raise UpgradeError(f"{command[0]} exited with {returncode}; nothing was changed by this command.")
    result = {"install": kind, "command": " ".join(command)}
    version = reported_version(kind)
    if version:
        result["version"] = version
    return result
