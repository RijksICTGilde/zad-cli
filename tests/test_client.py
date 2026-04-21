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
        retry_delay=0,
        task_timeout=5,
        task_poll_interval=0,
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
def test_v2_async_poll_completed(client):
    # V2 endpoints return 202 with task_id
    respx.post("https://api.example.com/v2/projects/my-project/:upsert-deployment").mock(
        return_value=httpx.Response(202, json={"task_id": "abc", "status": "accepted"})
    )
    respx.get("https://api.example.com/tasks/abc").mock(
        side_effect=[
            httpx.Response(200, json={"status": "pending"}),
            httpx.Response(200, json={"status": "running"}),
            httpx.Response(200, json={"status": "completed", "result": {"urls": {"web": "https://example.com"}}}),
        ]
    )
    result = client.upsert_deployment("my-project", {"deploymentName": "test", "components": []})
    assert result["urls"]["web"] == "https://example.com"


@respx.mock
def test_v2_async_poll_failed(client):
    respx.post("https://api.example.com/v2/projects/my-project/:upsert-deployment").mock(
        return_value=httpx.Response(202, json={"task_id": "abc", "status": "accepted"})
    )
    respx.get("https://api.example.com/tasks/abc").mock(
        return_value=httpx.Response(200, json={"status": "failed", "error_message": "Deployment failed"})
    )
    with pytest.raises(TaskFailedError, match="Deployment failed"):
        client.upsert_deployment("my-project", {"deploymentName": "test", "components": []})


@respx.mock
def test_v2_async_poll_timeout(client):
    client.task_timeout = 0
    respx.post("https://api.example.com/v2/projects/my-project/:upsert-deployment").mock(
        return_value=httpx.Response(202, json={"task_id": "abc", "status": "accepted"})
    )
    respx.get("https://api.example.com/tasks/abc").mock(return_value=httpx.Response(200, json={"status": "running"}))
    with pytest.raises(TaskTimeoutError) as exc_info:
        client.upsert_deployment("my-project", {"deploymentName": "test", "components": []})
    assert exc_info.value.task_id == "abc"


def test_build_poll_url_relative(client):
    assert client._build_poll_url("/tasks/abc").endswith("/tasks/abc")
    assert client._build_poll_url("/tasks/abc").startswith("https://")


def test_build_poll_url_absolute(client):
    url = "https://other.example.com/tasks/abc"
    assert client._build_poll_url(url) == url


@respx.mock
def test_v2_async_poll_recovers_from_empty_response(client):
    """Poll should retry when ZAD API returns an empty body (JSONDecodeError)."""
    respx.post("https://api.example.com/v2/projects/my-project/:upsert-deployment").mock(
        return_value=httpx.Response(202, json={"task_id": "abc", "status": "accepted"})
    )
    respx.get("https://api.example.com/tasks/abc").mock(
        side_effect=[
            httpx.Response(200, text=""),  # empty body → JSONDecodeError
            httpx.Response(200, json={"status": "completed", "result": {"ok": True}}),
        ]
    )
    result = client.upsert_deployment("my-project", {"deploymentName": "test", "components": []})
    assert result["ok"] is True


@respx.mock
def test_api_key_header(client):
    route = respx.get("https://api.example.com/metrics/health").mock(
        return_value=httpx.Response(200, json={"status": "healthy"})
    )
    client.health()
    assert route.calls[0].request.headers["X-API-Key"] == "test-key"


@respx.mock
def test_describe_deployment_filters_tasks_server_side(client):
    """describe_deployment must narrow the /tasks query to the target deployment."""
    respx.get("https://api.example.com/logs/my-project").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {"component": "web", "deployment": "staging", "namespace": "ns-staging", "k8s_deployment": "web"},
                ]
            },
        )
    )
    tasks_route = respx.get("https://api.example.com/tasks").mock(
        return_value=httpx.Response(
            200,
            json={
                "tasks": [
                    {
                        "status": "completed",
                        "result": {
                            "deployment": {
                                "name": "staging",
                                "components": [{"reference": "web", "image": "ghcr.io/org/web:v1"}],
                            },
                            "urls": {"staging": {"urls": {"web": "https://staging.example.com"}}},
                        },
                    },
                ]
            },
        )
    )

    result = client.describe_deployment("my-project", "staging")

    assert tasks_route.called
    params = tasks_route.calls[0].request.url.params
    assert params["project_name"] == "my-project"
    assert params["deployment_name"] == "staging"
    assert params["status"] == "completed"

    assert result["urls"] == {"web": "https://staging.example.com"}
    assert result["components"][0]["image"] == "ghcr.io/org/web:v1"


@respx.mock
def test_describe_deployment_ignores_tasks_with_mismatched_name(client):
    """If the server filter ever leaks a mismatched task, the client guard must drop it."""
    respx.get("https://api.example.com/logs/my-project").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {"component": "web", "deployment": "staging", "namespace": "ns-staging", "k8s_deployment": "web"},
                ]
            },
        )
    )
    respx.get("https://api.example.com/tasks").mock(
        return_value=httpx.Response(
            200,
            json={
                "tasks": [
                    {
                        "status": "completed",
                        "result": {
                            "deployment": {
                                "name": "staging-prefix-leak",
                                "components": [{"reference": "web", "image": "ghcr.io/org/web:wrong"}],
                            },
                            "urls": {"staging-prefix-leak": {"urls": {"web": "https://wrong.example.com"}}},
                        },
                    },
                ]
            },
        )
    )

    result = client.describe_deployment("my-project", "staging")

    assert result["urls"] == {}
    assert result["components"][0]["image"] == ""
