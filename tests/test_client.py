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
    """Legacy fallback: when the v2 endpoint 404s, describe must narrow /tasks server-side."""
    respx.get("https://api.example.com/v2/projects/my-project/deployments/staging").mock(
        return_value=httpx.Response(404, json={"detail": "not found"})
    )
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
    """Legacy fallback: if the server filter ever leaks a mismatched task, the client guard must drop it."""
    respx.get("https://api.example.com/v2/projects/my-project/deployments/staging").mock(
        return_value=httpx.Response(404, json={"detail": "not found"})
    )
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


@respx.mock
def test_describe_deployment_uses_v2_endpoint(client):
    """describe_deployment prefers the v2 read endpoint when available."""
    route = respx.get("https://api.example.com/v2/projects/my-project/deployments/staging").mock(
        return_value=httpx.Response(
            200,
            json={
                "name": "staging",
                "project": "my-project",
                "cluster": "odcn-test",
                "namespace": "ns-staging",
                "subdomain": None,
                "components": [{"reference": "web", "image": "ghcr.io/org/web:v2"}],
                "urls": {"web": "https://staging.example.com"},
                "status": "Healthy",
                "sync_revision": "abc123def456",
                "last_synced_at": "2026-05-07T09:00:00Z",
                "errors": [],
            },
        )
    )

    result = client.describe_deployment("my-project", "staging")

    assert route.called
    assert result["deployment"] == "staging"
    assert result["namespace"] == "ns-staging"
    assert result["status"] == "Healthy"
    assert result["sync_revision"] == "abc123def456"
    assert result["urls"] == {"web": "https://staging.example.com"}
    assert result["components"][0]["image"] == "ghcr.io/org/web:v2"


@respx.mock
def test_describe_deployment_surfaces_errors(client):
    """Degraded deployment: errors[] must come through with category and explanation."""
    respx.get("https://api.example.com/v2/projects/my-project/deployments/staging").mock(
        return_value=httpx.Response(
            200,
            json={
                "name": "staging",
                "project": "my-project",
                "cluster": "odcn-test",
                "namespace": "ns-staging",
                "components": [{"reference": "web", "image": "ghcr.io/org/web:bad"}],
                "urls": {},
                "status": "Degraded",
                "sync_revision": "deadbeefcafe",
                "last_synced_at": "2026-05-07T08:00:00Z",
                "errors": [
                    {
                        "resource": "Pod/web-7c9d8f-xxxxx",
                        "message": "Back-off pulling image ghcr.io/org/web:bad",
                        "category": "ImagePull",
                        "explanation": "Container image cannot be pulled. Check tag and registry credentials.",
                        "timestamp": "2026-05-07T08:05:00Z",
                    }
                ],
            },
        )
    )

    result = client.describe_deployment("my-project", "staging")

    assert result["status"] == "Degraded"
    assert len(result["errors"]) == 1
    assert result["errors"][0]["category"] == "ImagePull"


@respx.mock
def test_list_deployments_uses_v2_endpoint(client):
    """list_deployments prefers the v2 read endpoint and exposes the legacy shape."""
    route = respx.get("https://api.example.com/v2/projects/my-project/deployments").mock(
        return_value=httpx.Response(
            200,
            json={
                "project": "my-project",
                "cluster": "odcn-test",
                "deployments": [
                    {
                        "name": "staging",
                        "project": "my-project",
                        "cluster": "odcn-test",
                        "namespace": "ns-staging",
                        "components": [{"reference": "web", "image": "ghcr.io/org/web:v1"}],
                        "urls": {"web": "https://staging.example.com"},
                        "status": "Healthy",
                        "sync_revision": "abc",
                        "last_synced_at": "2026-05-07T09:00:00Z",
                        "errors": [],
                    },
                    {
                        "name": "production",
                        "project": "my-project",
                        "cluster": "odcn-test",
                        "namespace": "ns-prod",
                        "components": [
                            {"reference": "web", "image": "ghcr.io/org/web:v1"},
                            {"reference": "api", "image": "ghcr.io/org/api:v1"},
                        ],
                        "urls": {},
                        "status": "Degraded",
                        "errors": [],
                    },
                ],
            },
        )
    )

    rows = client.list_deployments("my-project")

    assert route.called
    assert len(rows) == 2
    assert rows[0]["deployment"] == "staging"
    assert rows[0]["components"] == ["web"]
    assert rows[0]["status"] == "Healthy"
    assert rows[1]["deployment"] == "production"
    assert rows[1]["components"] == ["web", "api"]
    assert rows[1]["status"] == "Degraded"


@respx.mock
def test_list_deployments_falls_back_on_404(client):
    """When the v2 endpoint 404s (older upstream), list_deployments uses the legacy fusion."""
    respx.get("https://api.example.com/v2/projects/my-project/deployments").mock(
        return_value=httpx.Response(404, json={"detail": "not found"})
    )
    respx.get("https://api.example.com/logs/my-project").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {"component": "web", "deployment": "staging", "namespace": "ns-staging"},
                ]
            },
        )
    )
    respx.get("https://api.example.com/tasks").mock(return_value=httpx.Response(200, json={"tasks": []}))

    rows = client.list_deployments("my-project")

    assert len(rows) == 1
    assert rows[0]["deployment"] == "staging"
    assert rows[0]["status"] == "Active"
