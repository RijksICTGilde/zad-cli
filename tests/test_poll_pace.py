"""How fast the CLI asks whether a task is done.

It used to be a flat three seconds, with the sleep at the end of the loop, so a task the
platform finished in a second still cost three. Measured against the sandbox: `env add`
took 3.07s, of which 1.4s was the platform. A playbook with twenty mutating steps spent
over half a minute waiting for nothing.

Small first, growing to the same 3s ceiling: short tasks return at once, and a rollout that
runs for a minute still gets asked only every three seconds, which is where a gentle rate is
actually wanted.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from zad_cli.api.client import ZadClient

API = "https://api.example.test"


@pytest.fixture
def slept(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Every sleep the poller asks for, without taking the time to do it."""
    delays: list[float] = []
    monkeypatch.setattr("zad_cli.api.client.time.sleep", delays.append)
    return delays


def _client() -> ZadClient:
    client = ZadClient(api_url=API, api_key="k")
    client.wait = True
    return client


@respx.mock
def test_a_task_that_finishes_at_once_is_not_slept_on(slept):
    respx.get(f"{API}/tasks/t1").mock(return_value=httpx.Response(200, json={"status": "completed", "result": {}}))

    _client()._poll_task("/tasks/t1", progress=False)

    assert slept == [], "the first answer was already the final one"


@respx.mock
def test_the_first_wait_is_short(slept):
    answers = [
        httpx.Response(200, json={"status": "running"}),
        httpx.Response(200, json={"status": "completed", "result": {}}),
    ]
    respx.get(f"{API}/tasks/t2").mock(side_effect=answers)

    _client()._poll_task("/tasks/t2", progress=False)

    assert slept == [0.3], "a task that needs one more look must not cost three seconds"


@respx.mock
def test_a_long_task_settles_at_the_ceiling(slept):
    running = [httpx.Response(200, json={"status": "running"}) for _ in range(20)]
    respx.get(f"{API}/tasks/t3").mock(side_effect=[*running, httpx.Response(200, json={"status": "completed"})])

    client = _client()
    client._poll_task("/tasks/t3", progress=False)

    assert slept[0] < slept[1], "it grows"
    assert max(slept) == client.task_poll_interval, "and stops growing at the ceiling"
    assert slept[-1] == client.task_poll_interval
    # A rollout is minutes of polling; the point of the ceiling is that it stays gentle.
    assert sum(1 for d in slept if d == client.task_poll_interval) > len(slept) / 2
