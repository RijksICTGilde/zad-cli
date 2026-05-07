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
    """Legacy fallback: when both v2 endpoints 404, describe must narrow /tasks server-side."""
    respx.get("https://api.example.com/v2/projects/my-project/deployments/staging").mock(
        return_value=httpx.Response(404, json={"detail": "not found"})
    )
    respx.get("https://api.example.com/v2/projects/my-project/deployments").mock(
        return_value=httpx.Response(404, json={"detail": "not found"})
    )
    respx.get("https://api.example.com/projects").mock(return_value=httpx.Response(200, json=[{"name": "my-project"}]))
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
    respx.get("https://api.example.com/v2/projects/my-project/deployments").mock(
        return_value=httpx.Response(404, json={"detail": "not found"})
    )
    respx.get("https://api.example.com/projects").mock(return_value=httpx.Response(200, json=[{"name": "my-project"}]))
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
def test_describe_deployment_propagates_404_when_v2_endpoint_exists(client):
    """When the v2 list endpoint works but the get endpoint 404s, the deployment is genuinely missing."""
    respx.get("https://api.example.com/v2/projects/my-project/deployments/missing").mock(
        return_value=httpx.Response(404, json={"detail": "not found"})
    )
    respx.get("https://api.example.com/v2/projects/my-project/deployments").mock(
        return_value=httpx.Response(
            200,
            json={"project": "my-project", "cluster": "odcn-test", "deployments": []},
        )
    )

    with pytest.raises(ZadApiError) as exc_info:
        client.describe_deployment("my-project", "missing")

    assert exc_info.value.status_code == 404
    assert "missing" in str(exc_info.value)


@respx.mock
def test_describe_deployment_falls_back_on_old_upstream(client):
    """When both v2 endpoints 404 and the project exists, the upstream lacks read endpoints; use legacy."""
    respx.get("https://api.example.com/v2/projects/my-project/deployments/staging").mock(
        return_value=httpx.Response(404, json={"detail": "not found"})
    )
    respx.get("https://api.example.com/v2/projects/my-project/deployments").mock(
        return_value=httpx.Response(404, json={"detail": "not found"})
    )
    respx.get("https://api.example.com/projects").mock(return_value=httpx.Response(200, json=[{"name": "my-project"}]))
    respx.get("https://api.example.com/logs/my-project").mock(
        return_value=httpx.Response(
            200,
            json={"results": [{"component": "web", "deployment": "staging", "namespace": "ns-staging"}]},
        )
    )
    respx.get("https://api.example.com/tasks").mock(return_value=httpx.Response(200, json={"tasks": []}))

    result = client.describe_deployment("my-project", "staging")

    assert result["deployment"] == "staging"
    assert result["namespace"] == "ns-staging"


@respx.mock
def test_describe_deployment_propagates_404_when_project_missing(client):
    """v2 endpoints 404 and the project is not in list_projects: surface 'Project not found'."""
    respx.get("https://api.example.com/v2/projects/missing-project/deployments/staging").mock(
        return_value=httpx.Response(404, json={"detail": "not found"})
    )
    respx.get("https://api.example.com/v2/projects/missing-project/deployments").mock(
        return_value=httpx.Response(404, json={"detail": "not found"})
    )
    respx.get("https://api.example.com/projects").mock(
        return_value=httpx.Response(200, json=[{"name": "other-project"}])
    )

    with pytest.raises(ZadApiError) as exc_info:
        client.describe_deployment("missing-project", "staging")

    assert exc_info.value.status_code == 404
    assert "missing-project" in str(exc_info.value)


@respx.mock
def test_list_deployments_falls_back_on_old_upstream(client):
    """v2 endpoint 404s but the project exists: upstream is old, use legacy fusion."""
    respx.get("https://api.example.com/v2/projects/my-project/deployments").mock(
        return_value=httpx.Response(404, json={"detail": "not found"})
    )
    respx.get("https://api.example.com/projects").mock(
        return_value=httpx.Response(200, json=[{"name": "my-project"}, {"name": "other"}])
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


@respx.mock
def test_project_status_preserves_v2_urls_when_no_recent_tasks(client):
    """project_status must not clobber v2-supplied URLs with empty dicts when tasks have nothing to add."""
    respx.get("https://api.example.com/v2/projects/my-project/deployments").mock(
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
                    }
                ],
            },
        )
    )
    respx.get("https://api.example.com/subdomains").mock(return_value=httpx.Response(200, json={"items": []}))
    respx.get("https://api.example.com/tasks").mock(return_value=httpx.Response(200, json={"tasks": []}))

    result = client.project_status("my-project")

    assert result["deployments"][0]["urls"] == {"web": "https://staging.example.com"}


@respx.mock
def test_project_status_v2_urls_win_over_stale_task_urls(client):
    """When both v2 and task history supply URLs, v2 is authoritative — stale task URLs must not win."""
    respx.get("https://api.example.com/v2/projects/my-project/deployments").mock(
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
                        "components": [{"reference": "web", "image": "ghcr.io/org/web:v2"}],
                        "urls": {"web": "https://current.example.com"},
                        "status": "Healthy",
                    }
                ],
            },
        )
    )
    respx.get("https://api.example.com/subdomains").mock(return_value=httpx.Response(200, json={"items": []}))
    respx.get("https://api.example.com/tasks").mock(
        return_value=httpx.Response(
            200,
            json={
                "tasks": [
                    {
                        "status": "completed",
                        "result": {"urls": {"staging": {"urls": {"web": "https://stale.example.com"}}}},
                    }
                ]
            },
        )
    )

    result = client.project_status("my-project")

    assert result["deployments"][0]["urls"] == {"web": "https://current.example.com"}


@respx.mock
def test_project_status_preserves_v2_empty_urls(client):
    """When v2 explicitly returns empty urls (no publish-on-web), don't surface stale task URLs."""
    respx.get("https://api.example.com/v2/projects/my-project/deployments").mock(
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
                        "components": [{"reference": "worker", "image": "ghcr.io/org/worker:v1"}],
                        "urls": {},
                        "status": "Healthy",
                    }
                ],
            },
        )
    )
    respx.get("https://api.example.com/subdomains").mock(return_value=httpx.Response(200, json={"items": []}))
    respx.get("https://api.example.com/tasks").mock(
        return_value=httpx.Response(
            200,
            json={
                "tasks": [
                    {
                        "status": "completed",
                        "result": {"urls": {"staging": {"urls": {"web": "https://stale.example.com"}}}},
                    }
                ]
            },
        )
    )

    result = client.project_status("my-project")

    assert result["deployments"][0]["urls"] == {}


@respx.mock
def test_describe_deployment_propagates_non_404_from_probe(client):
    """If the disambiguation probe returns 401/403/500, propagate the real cause."""
    respx.get("https://api.example.com/v2/projects/my-project/deployments/staging").mock(
        return_value=httpx.Response(404, json={"detail": "not found"})
    )
    respx.get("https://api.example.com/v2/projects/my-project/deployments").mock(
        return_value=httpx.Response(401, json={"detail": "Unauthorized"})
    )

    with pytest.raises(ZadApiError) as exc_info:
        client.describe_deployment("my-project", "staging")

    assert exc_info.value.status_code == 401


@respx.mock
def test_v2_validation_error_becomes_502(client):
    """An upstream response that fails pydantic validation surfaces as ZadApiError(502)."""
    respx.get("https://api.example.com/v2/projects/my-project/deployments").mock(
        return_value=httpx.Response(
            200,
            # Missing required `cluster` field; would crash without the wrapper.
            json={"project": "my-project", "deployments": []},
        )
    )

    with pytest.raises(ZadApiError) as exc_info:
        client.list_deployments_v2("my-project")

    assert exc_info.value.status_code == 502
    assert "DeploymentListResponse" in str(exc_info.value)


@respx.mock
def test_list_deployments_uses_legacy_when_projects_endpoint_also_404s(client):
    """Very old upstream where /projects itself doesn't exist: assume project exists, fall back to legacy."""
    respx.get("https://api.example.com/v2/projects/my-project/deployments").mock(
        return_value=httpx.Response(404, json={"detail": "not found"})
    )
    respx.get("https://api.example.com/projects").mock(return_value=httpx.Response(404, json={"detail": "not found"}))
    respx.get("https://api.example.com/logs/my-project").mock(
        return_value=httpx.Response(
            200, json={"results": [{"component": "web", "deployment": "staging", "namespace": "ns-staging"}]}
        )
    )
    respx.get("https://api.example.com/tasks").mock(return_value=httpx.Response(200, json={"tasks": []}))

    rows = client.list_deployments("my-project")

    assert len(rows) == 1
    assert rows[0]["deployment"] == "staging"


@respx.mock
def test_list_deployments_propagates_non_404_from_probe(client):
    """If list_projects returns 401/403/500, propagate the real error rather than masking it via legacy fallback."""
    respx.get("https://api.example.com/v2/projects/my-project/deployments").mock(
        return_value=httpx.Response(404, json={"detail": "not found"})
    )
    respx.get("https://api.example.com/projects").mock(
        return_value=httpx.Response(401, json={"detail": "Unauthorized"})
    )

    with pytest.raises(ZadApiError) as exc_info:
        client.list_deployments("my-project")

    assert exc_info.value.status_code == 401


@respx.mock
def test_list_deployments_propagates_404_when_project_missing(client):
    """v2 endpoint 404s and the project is not in list_projects: raise 404, don't silently fall back."""
    respx.get("https://api.example.com/v2/projects/my-project/deployments").mock(
        return_value=httpx.Response(404, json={"detail": "not found"})
    )
    respx.get("https://api.example.com/projects").mock(
        return_value=httpx.Response(200, json=[{"name": "other-project"}])
    )

    with pytest.raises(ZadApiError) as exc_info:
        client.list_deployments("my-project")

    assert exc_info.value.status_code == 404
    assert "my-project" in str(exc_info.value)
