"""`zad login`, `zad project list|create|use`: the token path and secret handling."""

from __future__ import annotations

import json

import httpx
import pytest
import respx
from typer.testing import CliRunner

from zad_cli import credentials
from zad_cli.cli import app

API = "https://api.example.com"
KEY = "Xk3mQ9vP2rT7wY1bN5cL8hJ4gF6dS0aZ"

runner = CliRunner()


@pytest.fixture(autouse=True)
def _environment(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ZAD_API_URL", API)
    monkeypatch.delenv("ZAD_API_KEY", raising=False)
    monkeypatch.delenv("ZAD_PROJECT_ID", raising=False)
    yield


def run(*args: str):
    return runner.invoke(app, list(args))


# --- Signing in ---


def test_project_list_without_a_token_says_how_to_get_one():
    result = run("project", "list")
    assert result.exit_code == 1
    assert "zad login" in result.output


def test_login_can_store_a_token_you_already_have():
    result = run("login", "--token", "tok-123")
    assert result.exit_code == 0, result.output
    assert credentials.get_token() == "tok-123"


def test_logout_forgets_everything():
    credentials.store_token("tok-123")
    credentials.store_api_key("p", KEY)
    result = run("logout")
    assert result.exit_code == 0, result.output
    assert credentials.get_token() is None
    assert credentials.get_api_key("p") is None


# --- Listing ---


@respx.mock
def test_project_list_sends_the_bearer_token():
    credentials.store_token("tok-123")
    route = respx.get(f"{API}/v2/projects").mock(
        return_value=httpx.Response(200, json={"projects": [{"name": "p", "role": "admin", "api_key": KEY}]})
    )
    result = run("project", "list")
    assert result.exit_code == 0, result.output
    assert route.calls[0].request.headers["authorization"] == "Bearer tok-123"


@respx.mock
def test_returned_keys_are_masked_by_default():
    credentials.store_token("tok-123")
    respx.get(f"{API}/v2/projects").mock(
        return_value=httpx.Response(200, json={"projects": [{"name": "p", "role": "admin", "api_key": KEY}]})
    )
    result = run("-o", "json", "project", "list")
    assert result.exit_code == 0, result.output
    assert KEY not in result.stdout


@respx.mock
def test_show_keys_prints_them_when_asked():
    credentials.store_token("tok-123")
    respx.get(f"{API}/v2/projects").mock(
        return_value=httpx.Response(200, json={"projects": [{"name": "p", "role": "admin", "api_key": KEY}]})
    )
    result = run("-o", "json", "project", "list", "--show-keys")
    assert json.loads(result.stdout)[0]["api_key"] == KEY


@respx.mock
def test_listing_projects_stores_nothing():
    """One directory holds one project, so listing many must not pick one for you."""
    credentials.store_token("tok-123")
    respx.get(f"{API}/v2/projects").mock(
        return_value=httpx.Response(
            200, json={"projects": [{"name": "een", "api_key": KEY}, {"name": "twee", "api_key": "sleutel-2"}]}
        )
    )
    run("project", "list")
    assert credentials.get_active_project() is None
    assert credentials.get_api_key() is None


@respx.mock
def test_a_developer_without_a_key_is_listed_all_the_same():
    """The API returns api_key=null below admin; that is a role, not an error."""
    credentials.store_token("tok-123")
    respx.get(f"{API}/v2/projects").mock(
        return_value=httpx.Response(200, json={"projects": [{"name": "p", "role": "developer", "api_key": None}]})
    )
    result = run("-o", "json", "project", "list")
    assert json.loads(result.stdout)[0]["name"] == "p"


# --- Creating ---


# The display name and the derived technical name are deliberately different in these
# tests: filing the key under the name that was typed is the mistake worth catching.
DERIVED = {"task_id": "t", "poll_url": "/api/tasks/t", "project_name": "mijn-project-a1b2", "api_key": KEY}


def mock_task(status: str = "completed", **extra):
    """The task behind the 202. Creating a project waits for it before returning.

    Without the wait the command hands back a key that answers 401 for the first few
    seconds, which is a failure that lands on whatever command runs next.
    """
    return respx.get(f"{API}/api/tasks/t").mock(
        return_value=httpx.Response(200, json={"task_id": "t", "status": status, **extra})
    )


@respx.mock
def test_create_stores_the_key_under_the_derived_name():
    credentials.store_token("tok-123")
    respx.post(f"{API}/v2/projects").mock(return_value=httpx.Response(202, json=DERIVED))
    mock_task()
    result = run("project", "create", "Mijn Project", "--description", "test", "-y")
    assert result.exit_code == 0, result.output
    assert credentials.get_api_key() == KEY
    assert credentials.get_active_project() == "mijn-project-a1b2"
    assert KEY not in result.stdout


@respx.mock
def test_create_makes_the_derived_project_active():
    credentials.store_token("tok-123")
    respx.post(f"{API}/v2/projects").mock(return_value=httpx.Response(202, json=DERIVED))
    mock_task()
    run("project", "create", "Mijn Project", "--description", "test", "-y")
    assert credentials.get_active_project() == "mijn-project-a1b2"


@respx.mock
def test_create_sends_the_display_name_and_no_technical_name():
    credentials.store_token("tok-123")
    route = respx.post(f"{API}/v2/projects").mock(return_value=httpx.Response(202, json=DERIVED))
    mock_task()
    run("project", "create", "Mijn Project", "--description", "test", "-y")
    sent = json.loads(route.calls.last.request.content)
    assert sent == {"display_name": "Mijn Project", "description": "test"}


@respx.mock
def test_create_without_a_project_name_in_the_response_is_an_error():
    """Storing the key somewhere wrong is worse than not storing it: say so and stop."""
    credentials.store_token("tok-123")
    respx.post(f"{API}/v2/projects").mock(
        return_value=httpx.Response(202, json={"task_id": "t", "poll_url": "/api/tasks/t", "api_key": KEY})
    )
    result = run("project", "create", "Mijn Project", "--description", "test", "-y")
    assert result.exit_code == 1
    assert credentials.get_active_project() is None


@respx.mock
def test_create_waits_with_the_bearer_token():
    """The new key is not accepted until the project exists, so the wait uses the token."""
    credentials.store_token("tok-123")
    respx.post(f"{API}/v2/projects").mock(return_value=httpx.Response(202, json=DERIVED))
    poll = mock_task()
    result = run("project", "create", "Mijn Project", "--description", "test", "-y")
    assert result.exit_code == 0, result.output
    assert poll.called
    assert poll.calls.last.request.headers["authorization"] == "Bearer tok-123"


@respx.mock
def test_no_wait_returns_without_polling():
    credentials.store_token("tok-123")
    respx.post(f"{API}/v2/projects").mock(return_value=httpx.Response(202, json=DERIVED))
    poll = mock_task()
    result = run("--no-wait", "project", "create", "Mijn Project", "--description", "test", "-y")
    assert result.exit_code == 0, result.output
    assert not poll.called
    assert credentials.get_api_key() == KEY


@respx.mock
def test_a_failed_setup_still_leaves_you_the_key_and_the_name():
    """The key comes back once. Losing it to a failure is the worst outcome available."""
    credentials.store_token("tok-123")
    respx.post(f"{API}/v2/projects").mock(return_value=httpx.Response(202, json=DERIVED))
    mock_task("failed", error_message="Namespace aanmaken mislukt")
    result = run("project", "create", "Mijn Project", "--description", "test", "-y")
    assert result.exit_code != 0
    assert credentials.get_api_key() == KEY
    assert "mijn-project-a1b2" in result.output
    assert KEY not in result.output


def test_create_dry_run_needs_no_token():
    result = run("-o", "json", "project", "create", "Nieuw Project", "--description", "test", "--dry-run", "-y")
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)["payload"]
    assert payload["display_name"] == "Nieuw Project"
    # The technical name is derived server-side; sending one would be a guess.
    assert "name" not in payload


# --- Choosing ---


def test_use_records_the_active_project():
    result = run("project", "use", "p")
    assert result.exit_code == 0, result.output
    assert credentials.get_active_project() == "p"


def test_use_export_prints_shell_exports():
    credentials.store_api_key("p", KEY)
    result = run("project", "use", "p", "--export")
    assert result.exit_code == 0, result.output
    assert "export ZAD_PROJECT_ID=p" in result.stdout
    assert f"export ZAD_API_KEY={KEY}" in result.stdout


def test_use_can_write_an_env_file(tmp_path):
    credentials.store_api_key("p", KEY)
    env_file = tmp_path / ".env"
    result = run("project", "use", "p", "--write-env", str(env_file))
    assert result.exit_code == 0, result.output
    assert f"ZAD_API_KEY={KEY}" in env_file.read_text()
    assert env_file.stat().st_mode & 0o777 == 0o600


@respx.mock
def test_the_stored_key_is_used_by_a_later_command():
    """`project use` is what makes the next command work without ZAD_API_KEY."""
    credentials.store_api_key("p", KEY)
    credentials.set_active_project("p")
    route = respx.get(f"{API}/v2/projects/p/pending-rollout").mock(
        return_value=httpx.Response(200, json={"project": "p", "count": 0})
    )
    result = run("project", "pending")
    assert result.exit_code == 0, result.output
    assert route.calls[0].request.headers["x-api-key"] == KEY


def test_explicit_flags_still_win_over_the_stored_project(monkeypatch: pytest.MonkeyPatch):
    """A script that sets ZAD_PROJECT_ID must keep behaving the same."""
    credentials.set_active_project("stored")
    monkeypatch.setenv("ZAD_PROJECT_ID", "from-env")
    from zad_cli.settings import Settings

    assert Settings.resolve().project_id == "from-env"
    assert Settings.resolve(project_id="from-flag").project_id == "from-flag"


def _payload(result):
    return json.loads(result.stdout)["payload"]


def test_the_display_name_may_be_spelled_out():
    """Explicit for scripts and agents, positional for hands. Same value either way."""
    positional = run("-o", "json", "project", "create", "Mijn Project", "--description", "d", "--dry-run", "-y")
    explicit = run(
        "-o", "json", "project", "create", "--display-name", "Mijn Project", "--description", "d", "--dry-run", "-y"
    )
    assert _payload(positional) == _payload(explicit)
    assert _payload(explicit)["display_name"] == "Mijn Project"


def test_both_spellings_agreeing_is_fine():
    result = run("-o", "json", "project", "create", "X", "--display-name", "X", "--description", "d", "--dry-run", "-y")
    assert result.exit_code == 0, result.output
    assert _payload(result)["display_name"] == "X"


def test_both_spellings_disagreeing_is_refused():
    """One of the two silently winning is how you create a project under the wrong name."""
    result = run("project", "create", "X", "--display-name", "Y", "--description", "d", "--dry-run", "-y")
    assert result.exit_code != 0
    assert "disagree" in result.output


def test_a_missing_display_name_names_both_ways_to_give_it():
    result = run("project", "create", "--description", "d", "--dry-run", "-y")
    assert result.exit_code != 0
    assert "--display-name" in result.output


@respx.mock
def test_a_401_on_an_sso_call_points_at_login_not_the_api_key():
    """Two credentials reach this API; naming the wrong one sends people to check
    a key that had nothing to do with the call."""
    credentials.store_token("verlopen")
    respx.post(f"{API}/v2/projects").mock(
        return_value=httpx.Response(401, json={"detail": "Authentication required - provide a valid Bearer token"})
    )
    result = run("project", "create", "Mijn Project", "--description", "d", "-y")
    assert result.exit_code != 0
    assert "zad login" in result.output
    assert "ZAD_API_KEY" not in result.output


@respx.mock
def test_a_401_on_a_project_call_still_points_at_the_api_key():
    credentials.store_api_key("p", KEY)
    credentials.set_active_project("p")
    respx.get(f"{API}/v2/projects/p/deployments").mock(
        return_value=httpx.Response(401, json={"detail": "Invalid API key"})
    )
    result = run("deployment", "list")
    assert result.exit_code != 0
    assert "ZAD_API_KEY" in result.output
    assert "zad login" not in result.output
