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
    """A stderr that says it is a terminal, so the rules below it can be reached."""

    def isatty(self) -> bool:
        return True

    def write(self, text: str) -> int:
        return len(text)

    def flush(self) -> None:
        pass


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


def test_the_tests_themselves_run_from_a_working_copy() -> None:
    # If this ever fails the suite is not running from the repo, and the detection above
    # is being asserted against a shape nobody has.
    assert update._source_checkout() is True


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


def _archive(payload: bytes = b"#!/bin/sh\necho zadctl 99.0.0\n") -> bytes:
    """A real tar.gz holding one `zadctl`, so the verification runs against bytes."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as bundle:
        info = tarfile.TarInfo("zadctl")
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
