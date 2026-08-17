"""`zadctl service sleep-mode status` and `wake`.

The two endpoints the CLI deferred as "a separate feature" until a practice run turned
sleep-mode on and had no way to show that it worked.
"""

from __future__ import annotations

import httpx
import pytest
import respx
from typer.testing import CliRunner

from zad_cli.cli import app

API = "https://api.example.com"
runner = CliRunner()


@pytest.fixture(autouse=True)
def _credentials(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ZAD_API_KEY", "test-key")
    monkeypatch.setenv("ZAD_PROJECT_ID", "my-project")
    monkeypatch.setenv("ZAD_API_URL", API)
    yield


@respx.mock
def test_status_reads_the_platform_s_own_endpoint():
    respx.get(f"{API}/sleep-mode/my-project/productie/status").mock(
        return_value=httpx.Response(200, json={"state": "ready", "asleep": False})
    )
    result = runner.invoke(app, ["-o", "json", "service", "sleep-mode", "status", "productie"])
    assert result.exit_code == 0, result.output
    assert '"state": "ready"' in result.stdout


@respx.mock
def test_wake_posts_and_says_so():
    route = respx.post(f"{API}/sleep-mode/my-project/productie/wake").mock(
        return_value=httpx.Response(202, json={"status": "waking"})
    )
    result = runner.invoke(app, ["service", "sleep-mode", "wake", "productie"])
    assert result.exit_code == 0, result.output
    assert route.call_count == 1
    assert "woken" in result.output


@respx.mock
def test_the_wake_token_is_sent_as_the_header_the_platform_asks_for():
    """Measured against the sandbox: both endpoints answer 401 "X-Wake-Token header
    required" to a perfectly good project API key, and the spec documents neither the
    header nor where a token comes from."""
    route = respx.get(f"{API}/sleep-mode/my-project/productie/status").mock(
        return_value=httpx.Response(200, json={"state": "starting"})
    )
    result = runner.invoke(app, ["service", "sleep-mode", "status", "productie", "--wake-token", "abc123"])
    assert result.exit_code == 0, result.output
    assert route.calls[0].request.headers["X-Wake-Token"] == "abc123"


def test_wake_can_be_rehearsed():
    result = runner.invoke(app, ["-o", "json", "service", "sleep-mode", "wake", "productie", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "/sleep-mode/my-project/productie/wake" in result.stdout
