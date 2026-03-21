"""Tests for API client retry logic and task polling."""

import httpx
import pytest
import respx

from zad_cli.api.client import TaskFailedError, TaskTimeoutError, ZadApiError, ZadClient


@pytest.fixture
def client():
    return ZadClient(
        api_url="https://api.example.com",
        api_key="test-key",
        max_retries=2,
        retry_delay=0,  # No delay in tests
        task_timeout=5,
        task_poll_interval=0,  # No delay in tests
    )


@respx.mock
def test_successful_request(client):
    respx.get("https://api.example.com/metrics/health").mock(
        return_value=httpx.Response(200, json={"status": "healthy"})
    )
    result = client.health()
    assert result["status"] == "healthy"


@respx.mock
def test_retry_on_500(client):
    route = respx.get("https://api.example.com/metrics/health")
    route.side_effect = [
        httpx.Response(500, text="Internal Server Error"),
        httpx.Response(200, json={"status": "healthy"}),
    ]
    result = client.health()
    assert result["status"] == "healthy"
    assert route.call_count == 2


@respx.mock
def test_retry_exhausted_raises(client):
    respx.get("https://api.example.com/metrics/health").mock(
        return_value=httpx.Response(503, text="Service Unavailable")
    )
    with pytest.raises(ZadApiError) as exc_info:
        client.health()
    assert exc_info.value.status_code == 503


@respx.mock
def test_no_retry_on_401(client):
    route = respx.get("https://api.example.com/metrics/health")
    route.mock(return_value=httpx.Response(401, text="Unauthorized"))
    with pytest.raises(ZadApiError) as exc_info:
        client.health()
    assert exc_info.value.status_code == 401
    assert route.call_count == 1


@respx.mock
def test_no_retry_on_404(client):
    route = respx.get("https://api.example.com/metrics/health")
    route.mock(return_value=httpx.Response(404, json={"message": "Not found"}))
    with pytest.raises(ZadApiError) as exc_info:
        client.health()
    assert exc_info.value.status_code == 404
    assert route.call_count == 1


@respx.mock
def test_poll_task_completed(client):
    respx.post("https://api.example.com/projects/my-project/:upsert-deployment").mock(
        return_value=httpx.Response(200, json={"task_id": "abc", "poll_url": "/tasks/abc"})
    )
    respx.get("https://api.example.com/tasks/abc").mock(
        side_effect=[
            httpx.Response(200, json={"status": "pending"}),
            httpx.Response(200, json={"status": "running", "current_step": "Deploying..."}),
            httpx.Response(200, json={"status": "completed", "result": {"urls": {"web": "https://example.com"}}}),
        ]
    )
    result = client.upsert_deployment("my-project", {"deploymentName": "test", "components": []})
    assert result["urls"]["web"] == "https://example.com"


@respx.mock
def test_poll_task_failed(client):
    respx.post("https://api.example.com/projects/my-project/:upsert-deployment").mock(
        return_value=httpx.Response(200, json={"task_id": "abc", "poll_url": "/tasks/abc"})
    )
    respx.get("https://api.example.com/tasks/abc").mock(
        return_value=httpx.Response(200, json={"status": "failed", "error_message": "Deployment failed"})
    )
    with pytest.raises(TaskFailedError, match="Deployment failed"):
        client.upsert_deployment("my-project", {"deploymentName": "test", "components": []})


@respx.mock
def test_poll_task_timeout(client):
    # Client has 5s timeout and 0s poll interval, so it will timeout quickly
    client.task_timeout = 0  # Immediate timeout
    respx.post("https://api.example.com/projects/my-project/:upsert-deployment").mock(
        return_value=httpx.Response(200, json={"task_id": "abc", "poll_url": "/tasks/abc"})
    )
    respx.get("https://api.example.com/tasks/abc").mock(return_value=httpx.Response(200, json={"status": "running"}))
    with pytest.raises(TaskTimeoutError):
        client.upsert_deployment("my-project", {"deploymentName": "test", "components": []})


def test_build_poll_url_relative(client):
    assert client._build_poll_url("/tasks/abc").endswith("/tasks/abc")
    assert client._build_poll_url("/tasks/abc").startswith("https://")


def test_build_poll_url_absolute(client):
    url = "https://other.example.com/tasks/abc"
    assert client._build_poll_url(url) == url


@respx.mock
def test_api_key_header(client):
    route = respx.get("https://api.example.com/metrics/health").mock(
        return_value=httpx.Response(200, json={"status": "healthy"})
    )
    client.health()
    assert route.calls[0].request.headers["X-API-Key"] == "test-key"
