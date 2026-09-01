"""A task can finish cleanly and still carry a refusal.

The run was fine; the thing it was asked to do was not. Reading only the task status calls
that a success, renders the refusal as if it were data, and exits zero, which is what a
script then treats as "it worked".
"""

from __future__ import annotations

import httpx
import pytest
import respx
from typer.testing import CliRunner

from zad_cli.cli import app

runner = CliRunner()
API = "https://api.example.com"
KEY = "Xk3mQ9vP2rT7wY1bN5cL8hJ4gF6dS0aZ"
REFUSAL = {
    "error": "Component 'component1' already exists in project 'p'",
    "status": "failed",
    "error_type": "duplicate_component",
}


@pytest.fixture(autouse=True)
def _environment(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ZAD_API_URL", API)
    monkeypatch.setenv("ZAD_API_KEY", KEY)
    monkeypatch.setenv("ZAD_PROJECT_ID", "p")
    yield


def _mock_refused_task():
    respx.post(f"{API}/v2/projects/p/components").mock(
        return_value=httpx.Response(202, json={"task_id": "t-1", "status": "accepted"})
    )
    respx.get(f"{API}/tasks/t-1").mock(
        return_value=httpx.Response(200, json={"status": "completed", "result": REFUSAL})
    )


@respx.mock
def test_a_refusal_in_the_result_is_a_failure():
    _mock_refused_task()
    result = runner.invoke(app, ["component", "add", "component1"])
    assert result.exit_code != 0, result.output


@respx.mock
def test_the_reason_is_shown_not_the_generic_line():
    _mock_refused_task()
    result = runner.invoke(app, ["component", "add", "component1"])
    flat = " ".join(result.output.split())
    assert "already exists" in flat
    assert "duplicate_component" in flat


@respx.mock
def test_success_is_not_claimed_for_a_refusal():
    """The worst part of the original bug: 'added.' printed under the refusal."""
    _mock_refused_task()
    result = runner.invoke(app, ["component", "add", "component1"])
    assert "added" not in result.output


@respx.mock
def test_the_task_id_is_in_the_suggestion():
    """Telling someone to run `zadctl task status <id>` without the id is not a suggestion."""
    respx.post(f"{API}/v2/projects/p/components").mock(
        return_value=httpx.Response(202, json={"task_id": "t-42", "status": "accepted"})
    )
    respx.get(f"{API}/tasks/t-42").mock(
        return_value=httpx.Response(
            200, json={"status": "failed", "error_message": "Project processing failed", "result": {}}
        )
    )
    result = runner.invoke(app, ["component", "add", "c"])
    assert result.exit_code != 0
    assert "t-42" in " ".join(result.output.split())


@respx.mock
def test_a_clean_result_still_succeeds():
    """The check must not turn every result that mentions a status into a failure."""
    respx.post(f"{API}/v2/projects/p/components").mock(
        return_value=httpx.Response(202, json={"task_id": "t-2", "status": "accepted"})
    )
    respx.get(f"{API}/tasks/t-2").mock(
        return_value=httpx.Response(200, json={"status": "completed", "result": {"status": "ok", "name": "c"}})
    )
    result = runner.invoke(app, ["component", "add", "c"])
    assert result.exit_code == 0, result.output
    assert "added" in result.output


def test_a_superseded_task_reads_as_the_success_it_is():
    """The API completes such a task rather than failing it, with `status: superseded`.

    Its own comment says why: "the project file was already committed, and a newer task
    whose scope covers this one will reprocess from that state." Printed bare, that word
    reads like a failure -- a practice run reported it as one, twice, while every change had
    in fact been saved.
    """
    from zad_cli.api.errors import degraded_diagnoses, superseded_note

    result = {"status": "superseded", "message": "handed over to task abc-123"}

    note = superseded_note(result)
    assert note is not None
    assert "Saved" in note
    assert "not a failure" in note

    # Not a warning: a diagnosis becomes one, and --strict turns warnings into a non-zero
    # exit. Failing a build over a successful hand-over is worse than the confusing word.
    assert degraded_diagnoses(result) == []


def test_a_superseded_note_names_the_task_that_took_over():
    """`superseded_by` names the task that took over; the note should point at it directly
    instead of sending the reader to `project pending` to go find it themselves."""
    from zad_cli.api.errors import superseded_note

    result = {
        "status": "superseded",
        "superseded_by": {"task_id": "t-99", "task_type": "refresh_project", "project_name": "p"},
    }
    note = superseded_note(result)
    assert note is not None
    assert "zadctl task status t-99" in note


def test_a_result_that_is_not_superseded_says_nothing():
    from zad_cli.api.errors import superseded_note

    assert superseded_note({"status": "completed"}) is None
    assert superseded_note("not a dict") is None
