"""The daily release check, and `zadctl upgrade`.

Three things are worth pinning here. The check must be *invisible* when it cannot help: no
request when it asked today, nothing printed when GitHub is unreachable, nothing at all in a
pipeline. The notice must appear at most once an interval, because a courtesy repeated on
every command is noise. And the binary upgrade must refuse an archive whose sha256 does not
match the published one, since without that step the command is a download-and-execute
mechanism.

No test reaches github.com: `respx` answers the redirect and the downloads, and `conftest.py`
points `update.CACHE_DIR` at a temporary home so no stamp survives a test.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import stat
import sys
import tarfile
import time
import types
from pathlib import Path

import httpx
import pytest
import respx
from typer.testing import CliRunner

from zad_cli import __version__, update
from zad_cli.cli import app

runner = CliRunner()

TAG_BASE = "https://github.com/RijksICTGilde/zad-cli/releases/tag"


def _redirect(tag: str) -> httpx.Response:
    """What `releases/latest` answers: a 302 whose Location names the release."""
    return httpx.Response(302, headers={"location": f"{TAG_BASE}/{tag}"})


def _settings(**overrides: object) -> types.SimpleNamespace:
    resolved: dict[str, object] = {
        "version_check": "notify",
        "version_check_interval": update.DEFAULT_INTERVAL,
        "output_format": "table",
    }
    resolved.update(overrides)
    return types.SimpleNamespace(**resolved)


def _unsuppressed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pretend this is an interactive terminal, the one condition a test run never meets."""
    monkeypatch.setattr(update, "suppressed", lambda *_args, **_kwargs: None)


def _write_state(**fields: object) -> None:
    update.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (update.CACHE_DIR / update.STATE_FILE).write_text(json.dumps(fields))


def _state() -> dict:
    return json.loads((update.CACHE_DIR / update.STATE_FILE).read_text())


class _FakeTty:
    """A terminal that keeps what was written to it, and answers what it was given.

    Standing in for both stdin and stderr: a test run has neither, which is what every
    suppression rule correctly notices, so the paths below them are only reachable like this.
    """

    def __init__(self, answer: str = "") -> None:
        self.answer = answer
        self.written: list[str] = []

    def isatty(self) -> bool:
        return True

    def write(self, text: str) -> int:
        self.written.append(text)
        return len(text)

    def readline(self) -> str:
        return self.answer

    def flush(self) -> None:
        pass

    @property
    def text(self) -> str:
        return "".join(self.written)


# ---------------------------------------------------------------------------
# The version source


@respx.mock
def test_the_redirect_is_the_version() -> None:
    respx.head(update.LATEST_URL).mock(return_value=_redirect("v0.14.0"))

    assert update.fetch_latest() == "0.14.0"


@respx.mock
def test_a_200_names_no_release() -> None:
    respx.head(update.LATEST_URL).mock(return_value=httpx.Response(200))

    assert update.fetch_latest() is None


@respx.mock
def test_a_redirect_without_a_tag_names_no_release() -> None:
    respx.head(update.LATEST_URL).mock(
        return_value=httpx.Response(302, headers={"location": "https://github.com/login"})
    )

    assert update.fetch_latest() is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("0.13.4", (0, 13, 4)),
        ("v0.13.4", (0, 13, 4)),
        ("V1.0.0", (1, 0, 0)),
        ("0.14.0-rc1", (0, 14, 0)),
        ("0.14.0+build7", (0, 14, 0)),
        ("not-a-version", (0,)),
        ("1.x.3", (1, 0, 3)),
    ],
)
def test_parse_version(raw: str, expected: tuple[int, ...]) -> None:
    assert update.parse_version(raw) == expected


@pytest.mark.parametrize(
    ("latest", "current", "newer"),
    [
        ("0.14.0", "0.13.4", True),
        ("v0.14.0", "0.13.4", True),
        ("0.13.4", "0.13.4", False),
        ("0.13.4", "v0.13.4", False),
        ("0.13.2", "0.13.4", False),
        ("0.14", "0.14.0", False),
        # A pre-release of a version you already have is not an upgrade.
        ("0.13.4-rc1", "0.13.4", False),
        ("nonsense", "0.13.4", False),
    ],
)
def test_is_newer(latest: str, current: str, newer: bool) -> None:
    assert update.is_newer(latest, current) is newer


@pytest.mark.parametrize("raw", ["0.13.2", "v0.13.2"])
def test_release_tag_is_the_tag_either_way(raw: str) -> None:
    assert update.release_tag(raw) == "v0.13.2"


# ---------------------------------------------------------------------------
# When it asks, and when it does not


@respx.mock
def test_a_fresh_stamp_makes_no_request(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    _unsuppressed(monkeypatch)
    route = respx.head(update.LATEST_URL).mock(return_value=_redirect("v99.0.0"))
    _write_state(checked_at=time.time())

    update.start(_settings())
    update.finish(timeout=5.0)

    assert route.call_count == 0
    assert update._pending is None
    assert capsys.readouterr().err == ""


@respx.mock
def test_a_stale_stamp_fetches_stamps_and_says_so(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    _unsuppressed(monkeypatch)
    route = respx.head(update.LATEST_URL).mock(return_value=_redirect("v99.0.0"))
    _write_state(checked_at=time.time() - update.DEFAULT_INTERVAL - 1)

    update.start(_settings())
    update.finish(timeout=5.0)

    assert route.called
    state = _state()
    assert state["latest"] == "99.0.0"
    assert state["checked_at"] > time.time() - 60
    assert state["notified_at"] > time.time() - 60
    err = capsys.readouterr().err
    assert "zadctl 99.0.0 is available" in err
    assert "zadctl config set version_check off" in err


@respx.mock
def test_no_state_file_at_all_is_a_stale_one(monkeypatch: pytest.MonkeyPatch) -> None:
    _unsuppressed(monkeypatch)
    route = respx.head(update.LATEST_URL).mock(return_value=_redirect("v99.0.0"))

    update.start(_settings())
    update.finish(timeout=5.0)

    assert route.called
    assert update.cached_latest() == "99.0.0"


@respx.mock
def test_a_malformed_state_file_is_an_empty_one(monkeypatch: pytest.MonkeyPatch) -> None:
    _unsuppressed(monkeypatch)
    update.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (update.CACHE_DIR / update.STATE_FILE).write_text("{not json")
    route = respx.head(update.LATEST_URL).mock(return_value=_redirect("v99.0.0"))

    update.start(_settings())
    update.finish(timeout=5.0)

    assert route.called
    assert update.cached_latest() == "99.0.0"


@respx.mock
def test_an_unreachable_github_prints_nothing_and_fails_nothing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    _unsuppressed(monkeypatch)
    respx.head(update.LATEST_URL).mock(side_effect=httpx.ConnectError("down"))

    update.start(_settings())
    update.finish(timeout=5.0)

    assert capsys.readouterr().err == ""
    # Nothing stamped, so the next run tries again rather than waiting out the interval.
    assert not (update.CACHE_DIR / update.STATE_FILE).exists()


@respx.mock
def test_off_asks_nothing(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    _unsuppressed(monkeypatch)
    route = respx.head(update.LATEST_URL).mock(return_value=_redirect("v99.0.0"))

    update.start(_settings(version_check="off"))
    update.finish(timeout=5.0)

    assert route.call_count == 0
    assert update._pending is None
    assert capsys.readouterr().err == ""


@respx.mock
def test_the_notice_comes_at_most_once_an_interval(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    _unsuppressed(monkeypatch)
    respx.head(update.LATEST_URL).mock(return_value=_redirect("v99.0.0"))

    update.start(_settings())
    update.finish(timeout=5.0)
    assert "zadctl 99.0.0 is available" in capsys.readouterr().err

    # Second run, same day: nothing to say, and nothing asked either.
    update.start(_settings())
    update.finish(timeout=5.0)
    assert capsys.readouterr().err == ""


@respx.mock
def test_a_fresh_notice_stamp_keeps_the_notice_away_even_on_a_new_check(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    _unsuppressed(monkeypatch)
    respx.head(update.LATEST_URL).mock(return_value=_redirect("v99.0.0"))
    # Asked yesterday, told about it a minute ago: `checked_at` paces the request and
    # `notified_at` paces the message, so only the request is due.
    _write_state(checked_at=time.time() - update.DEFAULT_INTERVAL - 1, notified_at=time.time() - 60)

    update.start(_settings())
    update.finish(timeout=5.0)

    assert capsys.readouterr().err == ""
    assert _state()["latest"] == "99.0.0"


@respx.mock
def test_a_release_you_already_have_is_not_announced(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    _unsuppressed(monkeypatch)
    respx.head(update.LATEST_URL).mock(return_value=_redirect(update.release_tag(__version__)))

    update.start(_settings())
    update.finish(timeout=5.0)

    assert capsys.readouterr().err == ""
    assert "notified_at" not in _state()


# ---------------------------------------------------------------------------
# Suppression


def test_a_test_run_is_already_suppressed() -> None:
    # conftest sets ZAD_CATALOG_OFFLINE, which is one of the reasons.
    assert update.suppressed() is not None


def test_stderr_that_is_not_a_terminal_suppresses(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ZAD_CATALOG_OFFLINE", raising=False)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)

    assert update.suppressed() == "stderr is not a terminal"


@pytest.mark.parametrize("fmt", ["json", "yaml"])
def test_a_machine_readable_format_suppresses(monkeypatch: pytest.MonkeyPatch, fmt: str) -> None:
    monkeypatch.delenv("ZAD_CATALOG_OFFLINE", raising=False)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setattr(sys, "stderr", _FakeTty())

    assert update.suppressed(fmt) == f"output format is {fmt}"


def test_the_format_is_read_off_argv_when_nobody_passes_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ZAD_CATALOG_OFFLINE", raising=False)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setattr(sys, "stderr", _FakeTty())
    monkeypatch.setattr(sys, "argv", ["zadctl", "--json", "project", "list"])

    assert update.suppressed() == "output format is json"


@pytest.mark.parametrize("name", ["CI", "GITHUB_ACTIONS"])
def test_a_pipeline_suppresses(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    monkeypatch.delenv("ZAD_CATALOG_OFFLINE", raising=False)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setattr(sys, "stderr", _FakeTty())
    monkeypatch.setenv(name, "true")

    assert update.suppressed() == f"{name} is set"


@pytest.mark.parametrize("name", ["_ZAD_COMPLETE", "_ZADCTL_COMPLETE"])
def test_a_shell_completion_suppresses(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    monkeypatch.delenv("ZAD_CATALOG_OFFLINE", raising=False)
    monkeypatch.setattr(sys, "stderr", _FakeTty())
    monkeypatch.setenv(name, "zsh_complete")

    reason = update.suppressed()

    assert reason is not None
    assert name in reason


def test_catalog_offline_suppresses() -> None:
    assert update.suppressed() == "ZAD_CATALOG_OFFLINE is set"


@respx.mock
def test_suppression_means_no_request_at_all() -> None:
    route = respx.head(update.LATEST_URL).mock(return_value=_redirect("v99.0.0"))

    # Nothing stubbed here: this is what every other test in the suite runs under.
    update.start(_settings())
    update.finish(timeout=5.0)

    assert route.call_count == 0


# ---------------------------------------------------------------------------
# The setting


def test_config_set_refuses_an_unknown_mode() -> None:
    result = runner.invoke(app, ["config", "set", "version_check", "bogus"])

    assert result.exit_code == 1
    assert "version_check must be one of" in result.output


@pytest.mark.parametrize("mode", ["off", "notify", "prompt"])
def test_config_set_writes_a_known_mode(mode: str) -> None:
    result = runner.invoke(app, ["config", "set", "version_check", mode])

    assert result.exit_code == 0, result.output
    assert f"ZAD_VERSION_CHECK={mode}" in Path(".env.zadctl").read_text()


def test_an_unknown_mode_in_the_environment_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    from zad_cli.settings import InvalidSettingError, Settings

    monkeypatch.setenv("ZAD_VERSION_CHECK", "soms")

    # Refused where it is read, the way `output` is: a check that silently does nothing is
    # indistinguishable from one that found nothing.
    with pytest.raises(InvalidSettingError, match="version_check must be one of"):
        Settings.resolve()


@pytest.mark.parametrize(("mode", "source"), [("off", "env"), ("prompt", "env")])
def test_a_known_mode_in_the_environment_is_what_resolves(
    monkeypatch: pytest.MonkeyPatch, mode: str, source: str
) -> None:
    from zad_cli.settings import Settings

    monkeypatch.setenv("ZAD_VERSION_CHECK", mode)

    resolved = Settings.resolve()

    assert resolved.version_check == mode
    assert resolved.sources["version_check"] == source


def test_the_mode_defaults_to_notify(monkeypatch: pytest.MonkeyPatch) -> None:
    from zad_cli.settings import Settings

    monkeypatch.delenv("ZAD_VERSION_CHECK", raising=False)

    assert Settings.resolve().version_check == "notify"


# ---------------------------------------------------------------------------
# Where this copy came from


def test_a_nuitka_build_is_a_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    # Nuitka defines __compiled__ in every module it compiles, so its presence is the
    # build saying what it is.
    monkeypatch.setattr(update, "__compiled__", object(), raising=False)

    assert update.install_kind() == "binary"


def test_a_uv_tool_install_is_recognised(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(update, "executable_path", lambda: None)
    monkeypatch.setattr(sys, "executable", "/home/x/.local/share/uv/tools/zad-cli/bin/python")

    assert update.install_kind() == "uv-tool"
    assert update.python_upgrade_command("uv-tool") == ["uv", "tool", "upgrade", "zad-cli"]


def test_a_pipx_install_is_recognised(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(update, "executable_path", lambda: None)
    monkeypatch.setattr(sys, "executable", "/home/x/.local/pipx/venvs/zad-cli/bin/python")

    assert update.install_kind() == "pipx"
    assert update.python_upgrade_command("pipx") == ["pipx", "upgrade", "zad-cli"]


def test_a_working_copy_is_a_source_install(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(update, "executable_path", lambda: None)
    monkeypatch.setattr(sys, "executable", "/usr/bin/python3")
    monkeypatch.setattr(update, "_source_checkout", lambda: True)

    assert update.install_kind() == "source"
    assert update.python_upgrade_command("source") == []


@pytest.mark.parametrize(
    ("parent", "git", "expected"),
    [("src", True, True), ("src", False, False), ("site-packages", True, False)],
)
def test_a_working_copy_is_a_src_tree_with_a_git_above_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, parent: str, git: bool, expected: bool
) -> None:
    # Shaped in tmp_path rather than asserted about this checkout: `_source_checkout() is True`
    # is a statement about where pytest was started, and it is false for a wheel.
    module = tmp_path / parent / "zad_cli" / "update.py"
    module.parent.mkdir(parents=True)
    module.write_text("")
    if git:
        (tmp_path / ".git").mkdir()
    monkeypatch.setattr(update, "__file__", str(module))

    assert update._source_checkout() is expected


@pytest.mark.parametrize("tag", [None, "v0.13.2"])
def test_a_tagged_upgrade_can_go_back(tag: str | None) -> None:
    command = update.python_upgrade_command("uv-tool", tag=tag)

    if tag is None:
        assert command == ["uv", "tool", "upgrade", "zad-cli"]
    else:
        assert command == [
            "uv",
            "tool",
            "install",
            "--force",
            "git+https://github.com/RijksICTGilde/zad-cli.git@v0.13.2",
        ]


# ---------------------------------------------------------------------------
# Release assets


@pytest.mark.parametrize(
    ("system", "machine", "label"),
    [
        ("Linux", "x86_64", "linux_amd64"),
        ("Linux", "aarch64", "linux_arm64"),
        ("Darwin", "arm64", "darwin_arm64"),
        ("Windows", "AMD64", "windows_amd64"),
        ("Darwin", "ppc64", None),
        ("FreeBSD", "x86_64", None),
    ],
)
def test_platform_label(monkeypatch: pytest.MonkeyPatch, system: str, machine: str, label: str | None) -> None:
    monkeypatch.setattr("platform.system", lambda: system)
    monkeypatch.setattr("platform.machine", lambda: machine)

    assert update.platform_label() == label


def test_the_windows_asset_is_a_zip() -> None:
    assert update.asset_name("windows_amd64") == "zadctl_windows_amd64.zip"
    assert update.asset_name("linux_arm64") == "zadctl_linux_arm64.tar.gz"


def test_asset_urls_carry_the_tag() -> None:
    assert update.asset_url("0.13.2", "zadctl_linux_amd64.tar.gz") == (
        "https://github.com/RijksICTGilde/zad-cli/releases/download/v0.13.2/zadctl_linux_amd64.tar.gz"
    )
    assert update.checksums_url("v0.13.2") == (
        "https://github.com/RijksICTGilde/zad-cli/releases/download/v0.13.2/SHA256SUMS"
    )


# ---------------------------------------------------------------------------
# The binary upgrade


ASSET = "zadctl_linux_amd64.tar.gz"


def _archive(payload: bytes = b"#!/bin/sh\necho zadctl 99.0.0\n", *, member: str = "zadctl") -> bytes:
    """A real tar.gz holding one `zadctl`, so the verification runs against bytes."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as bundle:
        info = tarfile.TarInfo(member)
        info.size = len(payload)
        info.mode = 0o755
        bundle.addfile(info, io.BytesIO(payload))
    return buffer.getvalue()


def _sums(archive: bytes, *, name: str = ASSET) -> str:
    return f"{hashlib.sha256(archive).hexdigest()}  {name}\n"


def test_a_verified_archive_is_installed(tmp_path: Path) -> None:
    archive = _archive()
    target = tmp_path / "zadctl"
    target.write_bytes(b"the old one")

    update.install_archive(archive, name=ASSET, sums=_sums(archive), target=target)

    assert target.read_bytes() == b"#!/bin/sh\necho zadctl 99.0.0\n"
    assert stat.S_IMODE(target.stat().st_mode) & 0o111


def test_a_tampered_archive_is_refused_and_the_target_is_untouched(tmp_path: Path) -> None:
    archive = _archive()
    target = tmp_path / "zadctl"
    target.write_bytes(b"the old one")
    wrong = _sums(_archive(b"something else entirely"))

    with pytest.raises(update.UpgradeError, match="does not match its published checksum"):
        update.install_archive(archive, name=ASSET, sums=wrong, target=target)

    assert target.read_bytes() == b"the old one"
    # And nothing half-written next to it either.
    assert [p.name for p in tmp_path.iterdir()] == ["zadctl"]


def test_an_archive_the_checksums_do_not_mention_is_refused(tmp_path: Path) -> None:
    archive = _archive()
    target = tmp_path / "zadctl"
    target.write_bytes(b"the old one")

    with pytest.raises(update.UpgradeError, match="lists no checksum"):
        update.install_archive(
            archive, name=ASSET, sums=_sums(archive, name="zadctl_darwin_arm64.tar.gz"), target=target
        )

    assert target.read_bytes() == b"the old one"


@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="root may write a 0o500 directory")
def test_an_unwritable_directory_is_refused_with_the_manual_way(tmp_path: Path) -> None:
    directory = tmp_path / "ro"
    directory.mkdir()
    target = directory / "zadctl"
    target.write_bytes(b"the old one")
    os.chmod(directory, 0o500)
    try:
        with pytest.raises(update.UpgradeError, match="not writable"):
            update.ensure_writable(target)
    finally:
        os.chmod(directory, 0o700)


@respx.mock
def test_the_binary_upgrade_downloads_verifies_and_replaces(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(update, "platform_label", lambda: "linux_amd64")
    monkeypatch.setattr(update, "binary_version", lambda target: "zadctl 99.0.0")
    archive = _archive()
    respx.get(update.asset_url("v99.0.0", ASSET)).mock(return_value=httpx.Response(200, content=archive))
    respx.get(update.checksums_url("v99.0.0")).mock(return_value=httpx.Response(200, text=_sums(archive)))
    target = tmp_path / "zadctl"
    target.write_bytes(b"the old one")

    reported = update.upgrade_binary("v99.0.0", target=target, log=lambda _line: None)

    assert reported == "zadctl 99.0.0"
    assert target.read_bytes() == b"#!/bin/sh\necho zadctl 99.0.0\n"


# ---------------------------------------------------------------------------
# zadctl upgrade


@respx.mock
def test_check_exits_one_when_behind() -> None:
    respx.head(update.LATEST_URL).mock(return_value=_redirect("v99.0.0"))

    result = runner.invoke(app, ["upgrade", "--check"])

    assert result.exit_code == 1, result.output
    assert "99.0.0" in result.output
    assert "update_available: true" in result.output


@respx.mock
def test_check_exits_zero_when_current() -> None:
    respx.head(update.LATEST_URL).mock(return_value=_redirect(update.release_tag(__version__)))

    result = runner.invoke(app, ["upgrade", "--check"])

    assert result.exit_code == 0, result.output
    assert "update_available: false" in result.output


@respx.mock
def test_check_installs_nothing() -> None:
    respx.head(update.LATEST_URL).mock(return_value=_redirect("v99.0.0"))
    download = respx.get(url__startswith=update.DOWNLOAD_BASE).mock(return_value=httpx.Response(200, content=b""))

    runner.invoke(app, ["upgrade", "--check"])

    assert download.call_count == 0


@respx.mock
def test_an_unreachable_release_page_ends_the_command() -> None:
    respx.head(update.LATEST_URL).mock(side_effect=httpx.ConnectError("down"))

    result = runner.invoke(app, ["upgrade", "--check"])

    assert result.exit_code == 2, result.output


@respx.mock
def test_dry_run_names_the_asset_and_downloads_nothing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    target = tmp_path / "zadctl"
    target.write_bytes(b"the old one")
    monkeypatch.setattr(update, "install_kind", lambda: "binary")
    monkeypatch.setattr(update, "platform_label", lambda: "darwin_arm64")
    monkeypatch.setattr(update, "executable_path", lambda: target)
    respx.head(update.LATEST_URL).mock(return_value=_redirect("v99.0.0"))
    download = respx.get(url__startswith=update.DOWNLOAD_BASE).mock(return_value=httpx.Response(200, content=b""))

    result = runner.invoke(app, ["upgrade", "--dry-run"])

    assert result.exit_code == 0, result.output
    assert "releases/download/v99.0.0/zadctl_darwin_arm64.tar.gz" in result.output
    assert "SHA256SUMS" in result.output
    assert str(target) in result.output
    assert download.call_count == 0
    assert target.read_bytes() == b"the old one"


@respx.mock
def test_dry_run_on_a_package_manager_names_the_command(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(update, "install_kind", lambda: "uv-tool")
    respx.head(update.LATEST_URL).mock(return_value=_redirect("v99.0.0"))

    result = runner.invoke(app, ["upgrade", "--to", "0.13.2", "--dry-run"])

    assert result.exit_code == 0, result.output
    assert "uv tool install --force git+https://github.com/RijksICTGilde/zad-cli.git@v0.13.2" in result.output


@respx.mock
def test_a_working_copy_is_told_to_pull_and_nothing_is_fetched(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(update, "install_kind", lambda: "source")
    route = respx.head(update.LATEST_URL).mock(return_value=_redirect("v99.0.0"))

    result = runner.invoke(app, ["upgrade", "--dry-run"])

    assert result.exit_code == 0, result.output
    assert "git pull" in result.output
    assert route.call_count == 0


@respx.mock
def test_an_install_that_is_current_is_not_reinstalled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(update, "install_kind", lambda: "uv-tool")
    respx.head(update.LATEST_URL).mock(return_value=_redirect(update.release_tag(__version__)))
    ran: list[list[str]] = []
    monkeypatch.setattr(update.subprocess, "run", lambda command, **_kwargs: ran.append(command))

    result = runner.invoke(app, ["upgrade"])

    assert result.exit_code == 0, result.output
    assert "already the newest release" in result.output
    assert ran == []


# ---------------------------------------------------------------------------
# zadctl version


def test_version_reports_the_last_seen_release() -> None:
    _write_state(checked_at=time.time(), latest="99.0.0")

    result = runner.invoke(app, ["version", "--client-only"])

    assert result.exit_code == 0, result.output
    assert "latest_release: 99.0.0" in result.output
    assert "update_available: true" in result.output


def test_version_says_nothing_when_no_release_was_ever_seen() -> None:
    result = runner.invoke(app, ["version", "--client-only"])

    assert result.exit_code == 0, result.output
    assert "latest_release" not in result.output


# ---------------------------------------------------------------------------
# A tag is a version, and nothing else


@pytest.mark.parametrize(
    ("raw", "ok"),
    [
        ("0.13.4", True),
        ("v0.13.4", True),
        ("1", True),
        ("0.14.0-rc1", True),
        ("0.14.0+build7", True),
        ("v1.0.0/../../../evil", False),
        ("../../evil", False),
        ("0.13.4 && curl evil", False),
        ("[red]0.13.4[/red]", False),
        ("latest", False),
        ("", False),
    ],
)
def test_valid_version(raw: str, ok: bool) -> None:
    assert update.valid_version(raw) is ok


@respx.mock
@pytest.mark.parametrize("suffix", ["v1.0.0/../../../evil", "v1.0.0/../../../../../evil", "latest"])
def test_a_crafted_redirect_names_no_release(suffix: str) -> None:
    """The one gate the download has, standing in front of the one gate it has.

    httpx removes `..` segments, so a tag of `v1.0.0/../../../evil` would move *both* the
    archive and the SHA256SUMS that vouches for it to somewhere else, and the verification
    would then hold the attacker's bytes against the attacker's digest and pass.
    """
    respx.head(update.LATEST_URL).mock(return_value=httpx.Response(302, headers={"location": f"{TAG_BASE}/{suffix}"}))

    assert update.fetch_latest() is None


def test_a_tag_that_is_not_a_version_has_no_release_to_download() -> None:
    with pytest.raises(update.UpgradeError, match="is not a release version"):
        update.release_tag("v1.0.0/../../../evil")


def test_an_asset_url_cannot_leave_the_release_it_names() -> None:
    # Proof of the escape this refuses: httpx normalises the dots away, so the host survives
    # and the path does not.
    assert str(httpx.URL(f"{update.DOWNLOAD_BASE}/v1.0.0/../../../../../evil/x.tar.gz")) == (
        "https://github.com/evil/x.tar.gz"
    )
    with pytest.raises(update.UpgradeError):
        update.asset_url("v1.0.0/../../../../../evil", "x.tar.gz")


@respx.mock
def test_upgrade_refuses_a_to_that_is_not_a_version() -> None:
    download = respx.get(url__startswith=update.DOWNLOAD_BASE).mock(return_value=httpx.Response(200, content=b""))

    result = runner.invoke(app, ["upgrade", "--to", "v1.0.0/../../../evil"])

    assert result.exit_code == 1, result.output
    assert "is not a release version" in result.output
    assert download.call_count == 0


@respx.mock
def test_a_download_that_redirects_to_http_is_refused() -> None:
    url = update.asset_url("v99.0.0", ASSET)
    respx.get(url).mock(return_value=httpx.Response(302, headers={"location": "http://mirror.example/zadctl.tar.gz"}))
    respx.get("http://mirror.example/zadctl.tar.gz").mock(return_value=httpx.Response(200, content=_archive()))

    with pytest.raises(update.UpgradeError, match="will not download over"):
        update._fetch(url, timeout=5.0)


# ---------------------------------------------------------------------------
# Pacing


@respx.mock
def test_a_stamp_in_the_future_is_stale(monkeypatch: pytest.MonkeyPatch) -> None:
    # A container before NTP has run writes one. Treating it as fresh would switch the check
    # off until wall time caught up with it, with nothing saying so.
    _unsuppressed(monkeypatch)
    route = respx.head(update.LATEST_URL).mock(return_value=_redirect("v99.0.0"))
    _write_state(checked_at=time.time() + 7 * update.DEFAULT_INTERVAL)

    update.start(_settings())
    update.finish(timeout=5.0)

    assert route.called


@respx.mock
def test_an_answer_that_names_no_release_still_paces_the_next_one(monkeypatch: pytest.MonkeyPatch) -> None:
    # A captive portal answers 200 to everything. That is an answer, not a timeout, so the
    # next command may not ask again: `checked_at` is what keeps this to once a day.
    _unsuppressed(monkeypatch)
    respx.head(update.LATEST_URL).mock(return_value=httpx.Response(200))

    update.start(_settings())
    update.finish(timeout=5.0)

    state = _state()
    assert state["checked_at"] > time.time() - 60
    assert "latest" not in state


def test_the_interval_is_the_same_number_in_both_modules() -> None:
    from zad_cli.settings import DEFAULT_VERSION_CHECK_INTERVAL

    assert DEFAULT_VERSION_CHECK_INTERVAL == update.DEFAULT_INTERVAL


def test_the_upgrade_command_suppresses_its_own_notice(monkeypatch: pytest.MonkeyPatch) -> None:
    # The thread started before `upgrade` ran would otherwise print "a newer release is
    # available" underneath the line saying it was just installed.
    monkeypatch.delenv("ZAD_CATALOG_OFFLINE", raising=False)
    monkeypatch.setattr(sys, "stderr", _FakeTty())
    monkeypatch.setattr(sys, "argv", ["zadctl", "upgrade"])

    assert update.suppressed("table") == "zadctl upgrade is running"


# ---------------------------------------------------------------------------
# Prompt mode


@respx.mock
def test_prompt_mode_asks_and_upgrades_when_the_answer_is_yes(monkeypatch: pytest.MonkeyPatch) -> None:
    _unsuppressed(monkeypatch)
    respx.head(update.LATEST_URL).mock(return_value=_redirect("v99.0.0"))
    terminal = _FakeTty(answer="y\n")
    monkeypatch.setattr(sys, "stdin", terminal)
    monkeypatch.setattr(sys, "stderr", terminal)
    notices: list[str] = []
    monkeypatch.setattr(update, "_warn", notices.append)
    asked: list[str] = []

    def _fake_upgrade(tag: str | None = None, **_kwargs: object) -> dict[str, str]:
        asked.append(str(tag))
        return {"install": "binary", "version": "zadctl 99.0.0"}

    monkeypatch.setattr(update, "run_upgrade", _fake_upgrade)

    update.start(_settings(version_check="prompt"))
    update.finish(timeout=5.0)

    assert "Upgrade now?" in terminal.text
    assert asked == ["v99.0.0"]
    assert "Now running zadctl 99.0.0." in notices


@respx.mock
def test_prompt_mode_treats_no_answer_as_no(monkeypatch: pytest.MonkeyPatch) -> None:
    _unsuppressed(monkeypatch)
    respx.head(update.LATEST_URL).mock(return_value=_redirect("v99.0.0"))
    terminal = _FakeTty(answer="\n")
    monkeypatch.setattr(sys, "stdin", terminal)
    monkeypatch.setattr(sys, "stderr", terminal)
    monkeypatch.setattr(update, "_warn", lambda _message: None)
    monkeypatch.setattr(update, "run_upgrade", lambda *_a, **_k: pytest.fail("nothing was agreed to"))

    update.start(_settings(version_check="prompt"))
    update.finish(timeout=5.0)

    assert "Upgrade now?" in terminal.text


@respx.mock
def test_ctrl_c_at_the_question_is_no_and_not_a_traceback(monkeypatch: pytest.MonkeyPatch) -> None:
    """`finish` runs in `main()`'s `finally`, so an escape from here replaces the exit status.

    A KeyboardInterrupt is not an `Exception`, which is why the guard names it: Ctrl-C at the
    question used to end a command that had already succeeded in a traceback and exit 1.
    """
    _unsuppressed(monkeypatch)
    respx.head(update.LATEST_URL).mock(return_value=_redirect("v99.0.0"))

    class _Interrupting(_FakeTty):
        def readline(self) -> str:
            raise KeyboardInterrupt

    terminal = _Interrupting()
    monkeypatch.setattr(sys, "stdin", terminal)
    monkeypatch.setattr(sys, "stderr", terminal)
    monkeypatch.setattr(update, "_warn", lambda _message: None)
    monkeypatch.setattr(update, "run_upgrade", lambda *_a, **_k: pytest.fail("Ctrl-C is not yes"))

    update.start(_settings(version_check="prompt"))
    update.finish(timeout=5.0)


# ---------------------------------------------------------------------------
# Where this copy came from, continued


def test_a_system_python_is_not_something_this_upgrades(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(update, "executable_path", lambda: None)
    monkeypatch.setattr(update, "_source_checkout", lambda: False)
    monkeypatch.setattr(sys, "executable", "/usr/bin/python3")
    monkeypatch.setattr(sys, "prefix", "/usr")
    monkeypatch.setattr(sys, "base_prefix", "/usr")

    assert update.install_kind() == "system"
    assert update.python_upgrade_command("system") == []


def test_a_virtual_environment_is_a_pip_install(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(update, "executable_path", lambda: None)
    monkeypatch.setattr(update, "_source_checkout", lambda: False)
    monkeypatch.setattr(sys, "executable", "/home/x/.venv/bin/python")
    monkeypatch.setattr(sys, "prefix", "/home/x/.venv")
    monkeypatch.setattr(sys, "base_prefix", "/usr")

    assert update.install_kind() == "pip"


def test_a_system_install_is_told_what_to_run_instead(monkeypatch: pytest.MonkeyPatch) -> None:
    # No pip install --upgrade into a directory the distro's package manager owns: on an
    # externally managed Python that is a PEP 668 error, and where it is not it is worse.
    monkeypatch.setattr(update, "install_kind", lambda: "system")

    with pytest.raises(update.UpgradeError, match="system Python"):
        update.run_upgrade(None, log=lambda _line: None)


def test_a_bare_argv0_is_not_the_binary_to_replace(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """`zadctl upgrade` gives `argv[0] == "zadctl"`, which resolves against the current directory.

    This repo's own build script leaves a file called `zadctl` lying about, and writing the
    download over *that* while reporting success is a silent no-op upgrade.
    """
    decoy = tmp_path / "zadctl"
    decoy.write_bytes(b"something else entirely")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["zadctl", "upgrade"])
    monkeypatch.setattr("shutil.which", lambda _name: None)

    assert update.executable_path() is None
    assert decoy.read_bytes() == b"something else entirely"


def test_an_absolute_argv0_is_the_binary_to_replace(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    real = tmp_path / "zadctl"
    real.write_bytes(b"the old one")
    monkeypatch.setattr(sys, "argv", [str(real), "upgrade"])
    monkeypatch.setattr("shutil.which", lambda _name: None)

    assert update.executable_path() == real


# ---------------------------------------------------------------------------
# Asking an install what it is


@pytest.mark.skipif(os.name == "nt", reason="shell scripts and chmod")
def test_a_binary_that_answers_reports_its_version(tmp_path: Path) -> None:
    script = tmp_path / "zadctl"
    script.write_text("#!/bin/sh\necho 'zadctl 99.0.0'\n")
    os.chmod(script, 0o755)

    assert update.binary_version(script) == "zadctl 99.0.0"


@pytest.mark.skipif(os.name == "nt", reason="shell scripts and chmod")
def test_a_binary_that_cannot_run_reports_nothing(tmp_path: Path) -> None:
    # The wrong-architecture asset, the libc mismatch, the truncated download: installed
    # fine, refuses to run. None is what makes that a failure instead of a version string.
    broken = tmp_path / "zadctl"
    broken.write_bytes(b"\x00\x01not a program")
    os.chmod(broken, 0o755)

    assert update.binary_version(broken) is None


# ---------------------------------------------------------------------------
# The binary upgrade, continued


def test_the_manual_hint_names_the_release_page_when_nothing_is_built(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(update, "platform_label", lambda: None)

    assert update.manual_install_hint() == f"See {update.RELEASES_URL} for what is built."


@pytest.mark.skipif(os.name == "nt", reason="the .old dance is Windows-only")
def test_a_hand_made_old_backup_is_left_alone(tmp_path: Path) -> None:
    # Nothing on POSIX creates a `.old`, so nothing on POSIX may delete one.
    archive = _archive()
    target = tmp_path / "zadctl"
    target.write_bytes(b"the old one")
    backup = tmp_path / "zadctl.old"
    backup.write_bytes(b"someone else's backup")

    update.install_archive(archive, name=ASSET, sums=_sums(archive), target=target)

    assert backup.read_bytes() == b"someone else's backup"


def test_an_archive_holding_the_wrong_binary_is_refused(tmp_path: Path) -> None:
    archive = _archive(member="zadctl.exe")
    target = tmp_path / "zadctl"
    target.write_bytes(b"the old one")

    with pytest.raises(update.UpgradeError, match="does not contain"):
        update.install_archive(archive, name=ASSET, sums=_sums(archive), target=target)

    assert target.read_bytes() == b"the old one"


def test_an_archive_that_is_not_an_archive_is_an_upgrade_error(tmp_path: Path) -> None:
    # Not a tarfile.ReadError out of the command: `zadctl upgrade` has one failure shape.
    rubbish = b"not a tarball at all"
    target = tmp_path / "zadctl"
    target.write_bytes(b"the old one")

    with pytest.raises(update.UpgradeError, match="could not be unpacked"):
        update.install_archive(rubbish, name=ASSET, sums=_sums(rubbish), target=target)

    assert target.read_bytes() == b"the old one"


# ---------------------------------------------------------------------------
# zadctl upgrade, continued


@respx.mock
def test_check_and_to_together_are_refused() -> None:
    respx.head(update.LATEST_URL).mock(return_value=_redirect("v99.0.0"))

    result = runner.invoke(app, ["upgrade", "--check", "--to", "0.13.2"])

    assert result.exit_code == 1, result.output
    assert "--to" in result.output


@respx.mock
def test_dry_run_shows_the_plan_even_when_the_install_is_current(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Being up to date is when a rehearsal is free, so it is the worst time to show nothing."""
    target = tmp_path / "zadctl"
    target.write_bytes(b"the old one")
    monkeypatch.setattr(update, "install_kind", lambda: "binary")
    monkeypatch.setattr(update, "platform_label", lambda: "darwin_arm64")
    monkeypatch.setattr(update, "executable_path", lambda: target)
    respx.head(update.LATEST_URL).mock(return_value=_redirect(update.release_tag(__version__)))

    result = runner.invoke(app, ["upgrade", "--dry-run"])

    assert result.exit_code == 0, result.output
    assert f"releases/download/v{__version__}/zadctl_darwin_arm64.tar.gz" in result.output
    assert "SHA256SUMS" in result.output
    assert "update_available: false" in result.output


@respx.mock
def test_a_package_manager_upgrade_runs_the_command_and_keeps_stdout_clean(monkeypatch: pytest.MonkeyPatch) -> None:
    """The package manager's own progress is status, so it belongs on stderr with the rest.

    `zadctl upgrade -o json | jq` is the reason: pip and uv write pages of lines, and
    inherited stdout would put all of them in front of the document.
    """
    monkeypatch.setattr(update, "install_kind", lambda: "uv-tool")
    monkeypatch.setattr("shutil.which", lambda name: f"/usr/local/bin/{name}")
    monkeypatch.setattr(update, "reported_version", lambda _kind: "zadctl 99.0.0")
    respx.head(update.LATEST_URL).mock(return_value=_redirect("v99.0.0"))
    ran: list[list[str]] = []

    class _FakePopen:
        def __init__(self, command: list[str], **_kwargs: object) -> None:
            ran.append(command)
            self.stdout = io.StringIO("Resolved 1 package\nInstalled zad-cli 99.0.0\n")

        def wait(self) -> int:
            return 0

    monkeypatch.setattr(update.subprocess, "Popen", _FakePopen)

    result = runner.invoke(app, ["-o", "json", "upgrade"])

    assert result.exit_code == 0, result.output
    # The resolved release, not a bare `upgrade`: the command says which version it installed.
    spec = "git+https://github.com/RijksICTGilde/zad-cli.git@v99.0.0"
    assert ran == [["uv", "tool", "install", "--force", spec]]
    assert json.loads(result.stdout) == {
        "install": "uv-tool",
        "command": f"uv tool install --force {spec}",
        "version": "zadctl 99.0.0",
    }
    assert "Installed zad-cli 99.0.0" in result.stderr


@respx.mock
def test_a_package_manager_that_fails_is_not_a_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(update, "install_kind", lambda: "uv-tool")
    monkeypatch.setattr("shutil.which", lambda name: f"/usr/local/bin/{name}")
    respx.head(update.LATEST_URL).mock(return_value=_redirect("v99.0.0"))

    class _FakePopen:
        def __init__(self, _command: list[str], **_kwargs: object) -> None:
            self.stdout = io.StringIO("error: no such package\n")

        def wait(self) -> int:
            return 2

    monkeypatch.setattr(update.subprocess, "Popen", _FakePopen)

    result = runner.invoke(app, ["upgrade"])

    assert result.exit_code == 1, result.output
    assert "exited with 2" in result.output


@respx.mock
def test_an_install_that_will_not_say_its_version_is_not_reported_as_upgraded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Confirming by running `--version` and then ignoring the answer is worse than not asking.

    A pipeline that runs `zadctl upgrade && zadctl deployment create ...` would otherwise
    carry on with a binary that cannot start.
    """
    monkeypatch.setattr(update, "install_kind", lambda: "binary")
    respx.head(update.LATEST_URL).mock(return_value=_redirect("v99.0.0"))
    monkeypatch.setattr(
        update,
        "run_upgrade",
        lambda *_a, **_k: {"install": "binary", "tag": "v99.0.0", "target": "/opt/bin/zadctl"},
    )

    result = runner.invoke(app, ["upgrade"])

    assert result.exit_code == 1, result.output
    assert "would not say which version" in result.output


@respx.mock
def test_a_download_failure_exits_two_like_every_other_platform_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(update, "install_kind", lambda: "binary")
    respx.head(update.LATEST_URL).mock(return_value=_redirect("v99.0.0"))

    def _fails(*_args: object, **_kwargs: object) -> dict[str, str]:
        raise update.UpgradeError("Could not download v99.0.0: ConnectError", transient=True)

    monkeypatch.setattr(update, "run_upgrade", _fails)

    result = runner.invoke(app, ["upgrade"])

    # 1 is "your input or your install", 2 is "the platform, try again": the same split the
    # API errors publish, and `--check` already exits 2 for an unreachable release page.
    assert result.exit_code == 2, result.output
