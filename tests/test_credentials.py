"""The credentials store: what it writes, how it is protected, and what it hides."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from zad_cli import credentials


@pytest.fixture(autouse=True)
def _isolated_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Never touch the developer's own ~/.config/zad, and ignore any real keyring."""
    monkeypatch.setattr(credentials, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(credentials, "CREDENTIALS_PATH", tmp_path / "credentials.toml")
    monkeypatch.setattr(credentials, "_keyring", lambda: None)
    monkeypatch.delenv("ZAD_SSO_TOKEN", raising=False)
    yield


def test_no_file_means_no_credentials():
    loaded = credentials.load()
    assert loaded.api_keys == {}
    assert loaded.token is None
    assert loaded.active_project is None


def test_api_key_round_trip():
    credentials.store_api_key("mijn-project", "Xk3mQ9vP2rT7wY1bN5cL8hJ4gF6dS0aZ")
    assert credentials.get_api_key("mijn-project") == "Xk3mQ9vP2rT7wY1bN5cL8hJ4gF6dS0aZ"


def test_keys_for_several_projects_coexist():
    credentials.store_api_key("a", "key-a")
    credentials.store_api_key("b", "key-b")
    assert credentials.get_api_key("a") == "key-a"
    assert credentials.get_api_key("b") == "key-b"


def test_token_and_active_project_survive_a_key_write():
    credentials.store_token("tok")
    credentials.set_active_project("a")
    credentials.store_api_key("a", "key-a")
    loaded = credentials.load()
    assert loaded.token == "tok"
    assert loaded.active_project == "a"
    assert loaded.api_keys["a"] == "key-a"


def test_the_file_is_owner_read_write_only():
    """It holds API keys; group- or world-readable is not acceptable."""
    path = credentials.store_api_key("a", "key-a")
    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == 0o600, f"expected 0600, got {oct(mode)}"


def test_a_value_with_quotes_survives_the_round_trip():
    credentials.store_api_key("a", 'we"ird\\key')
    assert credentials.get_api_key("a") == 'we"ird\\key'


def test_an_unreadable_file_is_treated_as_empty(tmp_path: Path):
    (tmp_path / "credentials.toml").write_text("this is not toml [[[")
    assert credentials.load().api_keys == {}


def test_env_token_wins_over_the_stored_one(monkeypatch: pytest.MonkeyPatch):
    """CI hands a token in through the environment; it must not need the file."""
    credentials.store_token("from-file")
    monkeypatch.setenv("ZAD_SSO_TOKEN", "from-env")
    assert credentials.get_token() == "from-env"


def test_clear_forgets_everything():
    credentials.store_token("tok")
    credentials.store_api_key("a", "key-a")
    credentials.set_active_project("a")
    credentials.clear()
    loaded = credentials.load()
    assert loaded.token is None
    assert loaded.api_keys == {}
    assert loaded.active_project is None


def test_no_temporary_file_is_left_behind(tmp_path: Path):
    credentials.store_api_key("a", "key-a")
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.parametrize(
    "value,expected_visible",
    [("Xk3mQ9vP2rT7wY1bN5cL8hJ4gF6dS0aZ", "Xk3m"), ("short", ""), ("", ""), (None, "")],
)
def test_redaction_never_shows_the_whole_secret(value: str | None, expected_visible: str) -> None:
    masked = credentials.redact(value)
    if value:
        assert value not in masked
    if expected_visible:
        assert masked.startswith(expected_visible)


def test_keyring_is_preferred_when_present(monkeypatch: pytest.MonkeyPatch):
    """With a keyring, the secret goes there and not into the file."""
    store: dict[tuple[str, str], str] = {}

    class _FakeKeyring:
        @staticmethod
        def set_password(service, name, value):
            store[(service, name)] = value

        @staticmethod
        def get_password(service, name):
            return store.get((service, name))

    monkeypatch.setattr(credentials, "_keyring", lambda: _FakeKeyring)
    path = credentials.store_api_key("a", "key-a")

    assert store[(credentials.KEYRING_SERVICE, "project:a")] == "key-a"
    assert "key-a" not in path.read_text()
    assert credentials.get_api_key("a") == "key-a"
