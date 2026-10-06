"""The binary upgrade, run end to end: a real binary, a real archive, a real HTTP server.

These serve a release from `http.server` on 127.0.0.1 and let `dist/zadctl` upgrade itself to
version 99.0.0: real gzip bytes, a real digest, and the file the running process started from
replaced under it. The archive holds a small script rather than a second compiled build,
because what is under test is the download, the gate and the replacement. That the published
artifact runs once installed is what the release workflow's `verify-upgrade` job checks.

The suite does not build the binary, so these skip with a reason when it is absent. Build it
with `scripts/build-binary.sh`.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import subprocess
import tarfile
import threading
from collections.abc import Callable, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from zad_cli import __version__, update

BINARY = Path(__file__).resolve().parent.parent / "dist" / ("zadctl.exe" if os.name == "nt" else "zadctl")
TAG = "v99.0.0"
NEW_VERSION = "zadctl 99.0.0"

pytestmark = [
    pytest.mark.skipif(
        not BINARY.exists(),
        reason=f"no standalone binary at {BINARY} -- build one with scripts/build-binary.sh to run this",
    ),
    pytest.mark.skipif(
        os.name == "nt",
        reason="the stand-in asset is a shell script, which is not a Windows .exe; "
        "the release workflow's verify-upgrade job covers Windows against real assets",
    ),
]

#: What the archive installs: a file that answers `--version` and nothing else.
STAND_IN = b'#!/bin/sh\necho "zadctl 99.0.0"\n'


def _archive(payload: bytes = STAND_IN, *, member: str | None = None) -> bytes:
    """A real .tar.gz holding one executable member, the way the release packages one."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as bundle:
        info = tarfile.TarInfo(member or update.binary_name())
        info.size = len(payload)
        info.mode = 0o755
        bundle.addfile(info, io.BytesIO(payload))
    return buffer.getvalue()


class _Release:
    """A release served on loopback: the `latest` redirect, one archive, one SHA256SUMS."""

    def __init__(self, routes: dict[str, tuple[int, dict[str, str], bytes]]) -> None:
        self.routes = routes
        self.requested: list[str] = []
        release = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"

            def _answer(self, *, body: bool) -> None:
                release.requested.append(self.path)
                status, headers, payload = release.routes.get(self.path, (404, {}, b"no such asset"))
                self.send_response(status)
                for name, value in headers.items():
                    self.send_header(name, value)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                if body:
                    self.wfile.write(payload)

            def do_GET(self) -> None:  # noqa: N802 - http.server's own spelling
                self._answer(body=True)

            def do_HEAD(self) -> None:  # noqa: N802 - the release check asks with HEAD
                self._answer(body=False)

            def log_message(self, *_args: object) -> None:
                """Quiet: the test says what it asked for by reading `requested`."""

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def base(self) -> str:
        host, port = self.server.server_address[:2]
        return f"http://{host}:{port}"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


def _routes(archive: bytes, *, sums: bytes | None = None, name: str | None = None) -> dict:
    """The three paths `zadctl upgrade` asks for, under the names it builds itself."""
    asset = name or update.asset_name()
    assert asset is not None, "no release asset is built for this platform"
    digest = hashlib.sha256(archive).hexdigest()
    return {
        # Shaped like GitHub's: the check reads the tag out of the Location header.
        "/latest": (302, {"Location": f"https://github.com/RijksICTGilde/zad-cli/releases/tag/{TAG}"}, b""),
        f"/download/{TAG}/{asset}": (200, {"Content-Type": "application/gzip"}, archive),
        f"/download/{TAG}/SHA256SUMS": (200, {}, sums if sums is not None else f"{digest}  {asset}\n".encode()),
    }


@pytest.fixture
def release() -> Iterator[Callable]:
    """Serve a release, and shut the server down whatever the test did."""
    servers: list[_Release] = []

    def _serve(archive: bytes, **kwargs: object) -> _Release:
        served = _Release(_routes(archive, **kwargs))  # type: ignore[arg-type]
        servers.append(served)
        return served

    yield _serve
    for served in servers:
        served.close()


@pytest.fixture
def installed(tmp_path: Path) -> Path:
    """A copy of the built binary, so a test replaces that and not `dist/zadctl`."""
    target = tmp_path / update.binary_name()
    shutil.copy2(BINARY, target)
    return target


def _run(target: Path, *args: str, base: str | None = None, home: Path | None = None) -> subprocess.CompletedProcess:
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(home or target.parent),
        "ZAD_CATALOG_OFFLINE": "1",
        "ZAD_VERSION_CHECK": "off",
        "NO_COLOR": "1",
        # Wide, because Rich wraps at 80 in a pipe and a wrapped
        # message is a different string to an assertion.
        "COLUMNS": "200",
    }
    if base is not None:
        environment[update.RELEASES_BASE_ENV] = base
    return subprocess.run(  # noqa: S603
        [str(target), *args], capture_output=True, text=True, timeout=300, env=environment, check=False
    )


def _version_of(target: Path) -> str:
    return _run(target, "--version").stdout.strip()


# --- The path that replaces a running binary ---


def test_the_binary_upgrades_itself(installed: Path, release) -> None:  # noqa: ANN001
    """Download, checksum, replace, and then say what is running -- on a real binary."""
    assert _version_of(installed) == f"zadctl {__version__}"
    served = release(_archive())

    done = _run(installed, "upgrade", "--to", "99.0.0", "-o", "json", base=served.base)

    assert done.returncode == 0, done.stderr
    report = json.loads(done.stdout)
    assert report["install"] == "binary"
    assert report["tag"] == TAG
    assert report["version"] == NEW_VERSION
    # The file under the running process really changed, and it runs.
    assert installed.read_bytes() == STAND_IN
    assert os.access(installed, os.X_OK)
    assert _version_of(installed) == NEW_VERSION


def test_the_binary_resolves_the_release_itself(installed: Path, release) -> None:  # noqa: ANN001
    """The whole chain: the `latest` redirect, then the asset it names."""
    served = release(_archive())

    done = _run(installed, "upgrade", "-o", "json", base=served.base)

    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout)["version"] == NEW_VERSION
    assert "/latest" in served.requested
    assert any(path.endswith("SHA256SUMS") for path in served.requested)


# --- The gate ---


def test_a_tampered_archive_is_refused_and_nothing_is_replaced(installed: Path, release) -> None:  # noqa: ANN001
    """The reason this command is not a download-and-execute mechanism, measured."""
    honest = _archive()
    tampered = _archive(b'#!/bin/sh\necho "zadctl 99.0.0"\n# and whatever else\n')
    # The digest of the archive we promised, serving the one we did not.
    served = release(tampered, sums=f"{hashlib.sha256(honest).hexdigest()}  {update.asset_name()}\n".encode())

    done = _run(installed, "upgrade", "--to", "99.0.0", base=served.base)

    # 2, not 1: a mismatch is the download or the mirror, which is worth retrying.
    assert done.returncode == 2, done.stdout
    assert "does not match its published checksum" in done.stderr
    assert _version_of(installed) == f"zadctl {__version__}"


def test_an_archive_no_sha256sums_mentions_is_refused(installed: Path, release) -> None:  # noqa: ANN001
    served = release(_archive(), sums=b"0000  something-else.tar.gz\n")

    done = _run(installed, "upgrade", "--to", "99.0.0", base=served.base)

    assert done.returncode == 2, done.stdout
    assert "lists no checksum" in done.stderr
    assert _version_of(installed) == f"zadctl {__version__}"


def test_an_archive_without_the_binary_is_refused(installed: Path, release) -> None:  # noqa: ANN001
    """A `zadctl.exe` in a tar.gz is a wrongly built release, not a binary to install."""
    served = release(_archive(member="zadctl.exe"))

    done = _run(installed, "upgrade", "--to", "99.0.0", base=served.base)

    assert done.returncode == 1, done.stdout
    assert f"does not contain {update.binary_name()}" in done.stderr
    assert _version_of(installed) == f"zadctl {__version__}"


# --- The seam, as the compiled binary reads it ---


def test_the_compiled_binary_honours_a_loopback_base(installed: Path, release) -> None:  # noqa: ANN001
    """What makes this test possible at all: a Nuitka build has no constant to patch."""
    served = release(_archive())

    done = _run(installed, "upgrade", "--to", "99.0.0", "--dry-run", "-o", "json", base=served.base)

    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout)["asset"].startswith(served.base)


def test_the_compiled_binary_ignores_a_base_that_is_not_loopback(installed: Path) -> None:
    """The gate the seam rests on, measured inside the shipped artifact.

    `--dry-run`, so no request is made: what is under test is which host the binary would
    download from.
    """
    done = _run(installed, "upgrade", "--to", "99.0.0", "--dry-run", "-o", "json", base="https://mirror.example")

    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout)["asset"].startswith(update.DOWNLOAD_BASE)
    assert update.RELEASES_BASE_ENV in done.stderr
