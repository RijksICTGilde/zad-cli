"""Tests for API client retry logic and task polling."""

import json

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
    respx.get("https://api.example.com/v1/backup/status").mock(
        return_value=httpx.Response(200, json={"status": "healthy"})
    )
    result = client.backup_status()
    assert result["status"] == "healthy"


@respx.mock
def test_retry_on_500(client):
    route = respx.get("https://api.example.com/v1/backup/status")
    route.side_effect = [
        httpx.Response(500, text="Internal Server Error"),
        httpx.Response(200, json={"status": "healthy"}),
    ]
    result = client.backup_status()
    assert result["status"] == "healthy"
    assert route.call_count == 2


@respx.mock
def test_retry_exhausted_raises(client):
    respx.get("https://api.example.com/v1/backup/status").mock(
        return_value=httpx.Response(503, text="Service Unavailable")
    )
    with pytest.raises(ZadApiError) as exc_info:
        client.backup_status()
    assert exc_info.value.status_code == 503


@respx.mock
def test_no_retry_on_401(client):
    route = respx.get("https://api.example.com/v1/backup/status")
    route.mock(return_value=httpx.Response(401, text="Unauthorized"))
    with pytest.raises(ZadApiError) as exc_info:
        client.backup_status()
    assert exc_info.value.status_code == 401
    assert route.call_count == 1


@respx.mock
def test_no_retry_on_404(client):
    route = respx.get("https://api.example.com/v1/backup/status")
    route.mock(return_value=httpx.Response(404, json={"message": "Not found"}))
    with pytest.raises(ZadApiError) as exc_info:
        client.backup_status()
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
def test_v2_async_poll_waiting_for_blocking_task(client):
    """A pending task can carry `waiting_for`, naming the task blocking it -- polling must
    keep going (not choke on the unknown field) until the blocker clears and this one completes."""
    respx.post("https://api.example.com/v2/projects/my-project/:upsert-deployment").mock(
        return_value=httpx.Response(202, json={"task_id": "abc", "status": "accepted"})
    )
    respx.get("https://api.example.com/tasks/abc").mock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    "status": "pending",
                    "waiting_for": {"task_id": "other", "task_type": "refresh_project", "reason": "running"},
                },
            ),
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


@respx.mock
def test_http_error_carries_auth_diagnosis(client):
    respx.get("https://api.example.com/v1/backup/status").mock(return_value=httpx.Response(401, text="Unauthorized"))
    with pytest.raises(ZadApiError) as exc_info:
        client.backup_status()
    diag = exc_info.value.diagnosis
    assert diag is not None
    assert diag.fault.value == "Auth"
    assert diag.exit_code == 1


@respx.mock
def test_http_422_diagnosis_has_field_paths(client):
    body = {"detail": [{"loc": ["body", "deploymentName"], "msg": "field required", "type": "missing"}]}
    respx.post("https://api.example.com/v2/projects/my-project/:upsert-deployment").mock(
        return_value=httpx.Response(422, json=body)
    )
    with pytest.raises(ZadApiError) as exc_info:
        client.upsert_deployment("my-project", {})
    diag = exc_info.value.diagnosis
    assert diag.fault.value == "UserInput"
    assert "deploymentName: field required" in diag.details


@respx.mock
def test_500_diagnosis_is_platform_and_retryable(client):
    respx.get("https://api.example.com/v1/backup/status").mock(return_value=httpx.Response(503, text="down"))
    with pytest.raises(ZadApiError) as exc_info:
        client.backup_status()
    diag = exc_info.value.diagnosis
    assert diag.fault.value == "Platform"
    assert diag.exit_code == 2  # CI/CD: safe to retry


@respx.mock
def test_task_failure_carries_app_diagnosis(client):
    respx.post("https://api.example.com/v2/projects/my-project/:upsert-deployment").mock(
        return_value=httpx.Response(202, json={"task_id": "abc", "status": "accepted"})
    )
    respx.get("https://api.example.com/tasks/abc").mock(
        return_value=httpx.Response(
            200,
            json={
                "status": "failed",
                "error_message": "deployment failed",
                "result": {
                    "status": "failed",
                    "processing": {
                        "status": "failed",
                        "component_failures": [
                            {"component": "web", "failure_type": "ImagePull", "message": "back-off pulling"}
                        ],
                    },
                },
            },
        )
    )
    with pytest.raises(TaskFailedError) as exc_info:
        client.upsert_deployment("my-project", {"deploymentName": "test", "components": []})
    diag = exc_info.value.diagnosis
    assert diag is not None
    assert diag.fault.value == "UserApp"
    assert any("web (ImagePull)" in line for line in diag.details)


@respx.mock
def test_completed_task_carries_superseded_by_into_result(client):
    """`superseded_by` sits next to `status` on the task, not inside `result` -- a superseded
    task's own result carries no outcome of its own, so it has to be merged in for the
    hand-over note to be able to name which task took over."""
    respx.post("https://api.example.com/v2/projects/my-project/:refresh").mock(
        return_value=httpx.Response(202, json={"task_id": "t-1", "status": "accepted"})
    )
    respx.get("https://api.example.com/tasks/t-1").mock(
        return_value=httpx.Response(
            200,
            json={
                "status": "completed",
                "result": {"status": "superseded"},
                "superseded_by": {"task_id": "t-2", "task_type": "refresh_project", "project_name": "my-project"},
            },
        )
    )
    result = client.refresh_project("my-project")
    assert result["superseded_by"]["task_id"] == "t-2"


def test_build_poll_url_relative(client):
    assert client._build_poll_url("/tasks/abc").endswith("/tasks/abc")
    assert client._build_poll_url("/tasks/abc").startswith("https://")


def test_build_poll_url_absolute(client):
    url = "https://other.example.com/tasks/abc"
    assert client._build_poll_url(url) == url


@pytest.mark.parametrize(
    ("base", "poll_url", "expected"),
    [
        # The real deployment: base ends in /api and the API's own poll_url repeats it.
        # Joining these naively gave /api/api/tasks/abc and a 404 on every project create.
        ("https://zad.example.dev/api", "/api/tasks/abc", "https://zad.example.dev/api/tasks/abc"),
        # The form _async_request builds itself, against the same base.
        ("https://zad.example.dev/api", "/tasks/abc", "https://zad.example.dev/api/tasks/abc"),
        # A base without a path prefix: nothing to strip, and nothing to add either.
        ("https://api.example.com", "/api/tasks/abc", "https://api.example.com/api/tasks/abc"),
        ("https://api.example.com", "/tasks/abc", "https://api.example.com/tasks/abc"),
        # A trailing slash on the base must not double either.
        ("https://zad.example.dev/api/", "/api/tasks/abc", "https://zad.example.dev/api/tasks/abc"),
        # A prefix that only looks like one: /apifoo is not /api.
        ("https://zad.example.dev/api", "/apifoo/tasks/abc", "https://zad.example.dev/api/apifoo/tasks/abc"),
    ],
)
def test_build_poll_url_never_doubles_the_api_prefix(base, poll_url, expected):
    c = ZadClient(api_url=base, api_key="k")
    try:
        assert c._build_poll_url(poll_url) == expected
    finally:
        c.close()


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
    route = respx.get("https://api.example.com/v1/backup/status").mock(
        return_value=httpx.Response(200, json={"status": "healthy"})
    )
    client.backup_status()
    assert route.calls[0].request.headers["X-API-Key"] == "test-key"


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
def test_describe_deployment_propagates_404(client):
    """A 404 from the v2 endpoint surfaces directly."""
    respx.get("https://api.example.com/v2/projects/my-project/deployments/missing").mock(
        return_value=httpx.Response(404, json={"detail": "not found"})
    )

    with pytest.raises(ZadApiError) as exc_info:
        client.describe_deployment("my-project", "missing")

    assert exc_info.value.status_code == 404


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
def test_list_admin_marked_passes_project_filter(client):
    route = respx.get("https://api.example.com/v2/admin/marked-for-deletion").mock(
        return_value=httpx.Response(200, json={"marks": []})
    )

    result = client.list_admin_marked(project_name="my-project")

    assert result == {"marks": []}
    assert route.calls.last.request.url.params["project_name"] == "my-project"


@respx.mock
def test_list_admin_marked_omits_filter_when_none(client):
    route = respx.get("https://api.example.com/v2/admin/marked-for-deletion").mock(
        return_value=httpx.Response(200, json={"marks": []})
    )

    client.list_admin_marked()

    assert "project_name" not in route.calls.last.request.url.params


@respx.mock
def test_delete_admin_mark_polls_async_task(client):
    """delete_admin_mark hits a mutating v2 endpoint, so it must wait for the task."""
    respx.delete("https://api.example.com/v2/admin/marked-for-deletion/mark-1").mock(
        return_value=httpx.Response(202, json={"task_id": "abc", "status": "accepted"})
    )
    poll = respx.get("https://api.example.com/tasks/abc").mock(
        side_effect=[
            httpx.Response(200, json={"status": "running"}),
            httpx.Response(200, json={"status": "completed", "result": {"removed": True}}),
        ]
    )

    result = client.delete_admin_mark("mark-1")

    assert result["removed"] is True
    assert poll.call_count == 2


@respx.mock
def test_delete_admin_mark_handles_empty_body(client):
    """A non-task response (e.g. plain 200) returns as-is instead of crashing."""
    respx.delete("https://api.example.com/v2/admin/marked-for-deletion/mark-1").mock(
        return_value=httpx.Response(200, json={})
    )

    assert client.delete_admin_mark("mark-1") == {}


@respx.mock
def test_get_orphan_report_returns_json(client):
    """orphan-report is a read-only v1 GET that returns the sweep report as-is."""
    report = {"orphan_candidates": [{"type": "postgresql_database", "name": "regel_k4c_pr104"}]}
    route = respx.get("https://api.example.com/v2/admin/orphans/report").mock(
        return_value=httpx.Response(200, json=report)
    )

    result = client.get_orphan_report()

    assert result == report
    assert route.call_count == 1


@respx.mock
def test_confirm_orphans_sends_items_payload(client):
    route = respx.post("https://api.example.com/v2/admin/orphans/confirm").mock(
        return_value=httpx.Response(200, json={"marked": 1})
    )
    payload = {"items": [{"type": "postgresql_database", "name": "regel_k4c_pr104"}]}

    result = client.confirm_orphans(payload)

    assert result == {"marked": 1}
    assert json.loads(route.calls.last.request.content) == payload


@respx.mock
def test_restore_deployment_resource_sends_payload(client):
    route = respx.post("https://api.example.com/v1/restore/project/my-project/deployment/staging").mock(
        return_value=httpx.Response(200, json={"status": "restored"})
    )

    payload = {
        "resource_type": "database",
        "snapshot_id": "k1234abcd",
        "component_name": "backend",
        "reference_name": "staging-db",
        "update_deployment": True,
    }
    result = client.restore_deployment_resource("my-project", "staging", payload)

    assert result == {"status": "restored"}
    assert json.loads(route.calls.last.request.content) == payload


@respx.mock
def test_list_pvc_snapshots(client):
    respx.get("https://api.example.com/v1/restore/snapshots/local/ns/app-pvc").mock(
        return_value=httpx.Response(200, json={"snapshots": [{"id": "snap-1"}]})
    )

    result = client.list_pvc_snapshots("local", "ns", "app-pvc")

    assert result["snapshots"][0]["id"] == "snap-1"


# The restore endpoints authenticate the API key against a project_name query
# parameter and reject requests without it with 401. These tests pin that the
# client actually puts it on the wire -- omitting it silently broke every
# restore command until it was noticed against the live API.


@respx.mock
@pytest.mark.parametrize(
    ("call", "url"),
    [
        (
            lambda c: c.list_snapshots("local", "rig-proj", project_name="proj"),
            "https://api.example.com/v1/restore/snapshots/local/rig-proj",
        ),
        (
            lambda c: c.list_pvc_snapshots("local", "rig-proj", "app-pvc", project_name="proj"),
            "https://api.example.com/v1/restore/snapshots/local/rig-proj/app-pvc",
        ),
    ],
)
def test_restore_list_endpoints_send_project_name(client, call, url):
    route = respx.get(url).mock(return_value=httpx.Response(200, json={"snapshots": []}))

    call(client)

    assert route.calls.last.request.url.params["project_name"] == "proj"


@respx.mock
@pytest.mark.parametrize(
    ("call", "url"),
    [
        (
            lambda c: c.restore_pvc("local", "rig-proj", "app-pvc", project_name="proj"),
            "https://api.example.com/v1/restore/pvc/local/rig-proj/app-pvc",
        ),
        (
            lambda c: c.restore_database("local", "rig-proj", "mydb", {"target_database_host": "db"}, "proj"),
            "https://api.example.com/v1/restore/database/local/rig-proj/mydb",
        ),
        (
            lambda c: c.restore_bucket("local", "rig-proj", "mybucket", {"target_bucket_name": "b"}, "proj"),
            "https://api.example.com/v1/restore/bucket/local/rig-proj/mybucket",
        ),
    ],
)
def test_restore_mutating_endpoints_send_project_name(client, call, url):
    route = respx.post(url).mock(return_value=httpx.Response(200, json={"success": True}))

    call(client)

    assert route.calls.last.request.url.params["project_name"] == "proj"


@respx.mock
def test_update_component_patches_and_polls_async_task(client):
    """update_component hits a mutating v2 endpoint, so it must wait for the task.

    The CLI tests for `component update` all use --dry-run, which returns before
    the client is reached: a wrong path or payload would go unnoticed there.
    """
    route = respx.patch("https://api.example.com/v2/projects/my-project/components/web").mock(
        return_value=httpx.Response(202, json={"task_id": "task-1", "status": "accepted"})
    )
    poll = respx.get("https://api.example.com/tasks/task-1").mock(
        side_effect=[
            httpx.Response(200, json={"status": "running"}),
            httpx.Response(200, json={"status": "completed", "result": {"updated": True}}),
        ]
    )

    result = client.update_component("my-project", "web", {"image": "ghcr.io/org/app:v2", "ports": [8080]})

    assert result["updated"] is True
    assert poll.call_count == 2
    assert json.loads(route.calls.last.request.content) == {"image": "ghcr.io/org/app:v2", "ports": [8080]}


@respx.mock
def test_update_component_can_clear_ports(client):
    """Clearing ports is an empty array on the wire, not an omitted key."""
    route = respx.patch("https://api.example.com/v2/projects/my-project/components/web").mock(
        return_value=httpx.Response(200, json={"updated": True})
    )

    client.update_component("my-project", "web", {"ports": []})

    assert json.loads(route.calls.last.request.content) == {"ports": []}


# --- 1.0: service config, values, attachments, rollout and SSO ---


@respx.mock
def test_service_config_get(client):
    respx.get("https://api.example.com/v2/projects/p/services/postgresql-database/config").mock(
        return_value=httpx.Response(200, json={"project": {"scope": "shared"}})
    )
    assert client.get_service_config("p", "postgresql-database") == {"project": {"scope": "shared"}}


@respx.mock
def test_put_service_config_takes_the_path_from_the_registry(client):
    """The client has no table of ~50 config endpoints; the caller passes the path."""
    route = respx.put("https://api.example.com/v2/projects/p/services/redis/config/project").mock(
        return_value=httpx.Response(200, json={"status": "ok"})
    )
    client.put_service_config("/v2/projects/p/services/redis/config/project", {"instances": 1})
    assert json.loads(route.calls[0].request.content) == {"instances": 1}


@respx.mock
def test_delete_service_config(client):
    respx.delete("https://api.example.com/v2/projects/p/services/redis/config/project").mock(
        return_value=httpx.Response(200, json={"status": "ok"})
    )
    assert client.delete_service_config("/v2/projects/p/services/redis/config/project") == {"status": "ok"}


@respx.mock
def test_values_verbs_map_to_four_distinct_endpoints(client):
    """add/set/unset/clear are not synonyms; each has its own method and path."""
    base = "https://api.example.com/v2/projects/p/services/user-env-vars/values/component/web"
    path = "/v2/projects/p/services/user-env-vars/values/component/web"
    add = respx.post(base).mock(return_value=httpx.Response(200, json={"status": "ok"}))
    change = respx.patch(base).mock(return_value=httpx.Response(200, json={"status": "ok"}))
    clear = respx.delete(base).mock(return_value=httpx.Response(200, json={"status": "ok"}))
    remove_many = respx.post(f"{base}/:delete").mock(return_value=httpx.Response(200, json={"status": "ok"}))
    remove_one = respx.delete(f"{base}/FEATURE_X").mock(return_value=httpx.Response(200, json={"status": "ok"}))

    client.add_service_values(path, {"A": "1"})
    client.change_service_values(path, {"A": "2"})
    client.remove_service_values(path, ["A", "B"])
    client.remove_service_value(path, "FEATURE_X")
    client.clear_service_values(path)

    assert json.loads(add.calls[0].request.content) == {"values": {"A": "1"}}
    assert json.loads(change.calls[0].request.content) == {"values": {"A": "2"}}
    assert json.loads(remove_many.calls[0].request.content) == {"keys": ["A", "B"]}
    assert remove_one.call_count == 1
    assert clear.call_count == 1


@respx.mock
def test_pending_rollout(client):
    respx.get("https://api.example.com/v2/projects/p/pending-rollout").mock(
        return_value=httpx.Response(200, json={"project": "p", "count": 3})
    )
    assert client.pending_rollout("p")["count"] == 3


@respx.mock
def test_no_rollout_is_sent_only_where_the_spec_allows_it(client):
    """Endpoints that accept `rollout` get it; the rest are left alone."""
    client.rollout = False
    accepts = respx.put("https://api.example.com/v2/projects/p/services/redis/config/project").mock(
        return_value=httpx.Response(200, json={"status": "ok"})
    )
    does_not = respx.get("https://api.example.com/v2/projects/p/pending-rollout").mock(
        return_value=httpx.Response(200, json={"project": "p", "count": 0})
    )

    client.put_service_config("/v2/projects/p/services/redis/config/project", {})
    client.pending_rollout("p")

    assert accepts.calls[0].request.url.params["rollout"] == "false"
    assert "rollout" not in does_not.calls[0].request.url.params


@respx.mock
def test_deferred_rollouts_are_counted_so_the_cli_can_warn(client):
    client.rollout = False
    respx.put("https://api.example.com/v2/projects/p/services/redis/config/project").mock(
        return_value=httpx.Response(200, json={"status": "ok"})
    )
    client.put_service_config("/v2/projects/p/services/redis/config/project", {})
    assert client.rollout_deferred == 1


@respx.mock
def test_rollout_default_sends_nothing(client):
    """Without --no-rollout the API's own default decides; we do not pin it."""
    route = respx.put("https://api.example.com/v2/projects/p/services/redis/config/project").mock(
        return_value=httpx.Response(200, json={"status": "ok"})
    )
    client.put_service_config("/v2/projects/p/services/redis/config/project", {})
    assert "rollout" not in route.calls[0].request.url.params


@respx.mock
def test_create_attachment_uploads_multipart(client):
    """The attachment endpoints are the only multipart ones; a JSON body would be wrong."""
    route = respx.post("https://api.example.com/v2/projects/p/services/attachments/attachment").mock(
        return_value=httpx.Response(200, json={"status": "ok"})
    )
    client.create_attachment("p", "server-cert", "server.pem", b"---cert---")
    request = route.calls[0].request
    assert request.headers["content-type"].startswith("multipart/form-data")
    assert b"server-cert" in request.content
    assert b"---cert---" in request.content


@respx.mock
def test_assign_attachment_by_reference_sends_no_file(client):
    route = respx.post("https://api.example.com/v2/projects/p/services/attachments/component/web/attachment").mock(
        return_value=httpx.Response(200, json={"status": "ok"})
    )
    client.assign_attachment("p", "web", "server-cert", {"provide-as": "file", "path": "/etc/x"})
    content = route.calls[0].request.content
    assert b"server-cert" in content
    assert b"reference" in content


@respx.mock
def test_list_projects_uses_a_bearer_token_not_the_api_key(client):
    """You need the project name before you can have its key, so this one takes SSO."""
    route = respx.get("https://api.example.com/v2/projects").mock(
        return_value=httpx.Response(200, json={"projects": [{"name": "p", "role": "admin"}]})
    )
    client.list_projects_sso("tok-123")
    assert route.calls[0].request.headers["authorization"] == "Bearer tok-123"


@respx.mock
def test_create_project_returns_the_key_without_polling(client):
    """The key is in the 202 body; polling the task would return the task result instead.

    Not polled at all: /tasks refuses the bearer token and the new key is not accepted
    until the project exists, so there is nothing here that can be waited on.
    """
    respx.post("https://api.example.com/v2/projects").mock(
        return_value=httpx.Response(
            202,
            json={
                "status": "accepted",
                "task_id": "t-1",
                "poll_url": "/api/tasks/t-1",
                "project_name": "p",
                "api_key": "Xk3mQ9vP2rT7wY1bN5cL8hJ4gF6dS0aZ",
            },
        )
    )
    result = client.create_project_sso("tok", {"name": "p", "description": "d"})
    assert result["api_key"] == "Xk3mQ9vP2rT7wY1bN5cL8hJ4gF6dS0aZ"


@respx.mock
def test_database_schema_endpoints(client):
    respx.get("https://api.example.com/v2/projects/p/services/postgresql-database/schemas").mock(
        return_value=httpx.Response(200, json={"schemas": [{"postfix": "reporting"}]})
    )
    add = respx.post("https://api.example.com/v2/projects/p/services/postgresql-database/schemas").mock(
        return_value=httpx.Response(200, json={"status": "ok"})
    )
    remove = respx.delete("https://api.example.com/v2/projects/p/services/postgresql-database/schemas/reporting").mock(
        return_value=httpx.Response(200, json={"status": "ok"})
    )

    assert client.list_database_schemas("p")["schemas"][0]["postfix"] == "reporting"
    client.add_database_schema("p", {"postfix": "reporting", "description": ""})
    client.remove_database_schema("p", "reporting", forget=True)

    assert json.loads(add.calls[0].request.content)["postfix"] == "reporting"
    assert remove.calls[0].request.url.params["forget"] == "true"


@respx.mock
def test_admin_cleanup_defaults_to_a_dry_run(client):
    route = respx.post("https://api.example.com/v2/admin/cleanup/trigger").mock(
        return_value=httpx.Response(200, json={"purged": 0})
    )
    client.trigger_cleanup("p")
    params = route.calls[0].request.url.params
    assert params["dry_run"] == "true"
    assert params["project_name"] == "p"


@respx.mock
def test_server_version_is_read_outside_the_api_prefix(client):
    """/version is served next to /api, not under it."""
    respx.get("https://api.example.com/version").mock(
        return_value=httpx.Response(200, json={"name": "ZAD", "version": "abc1234"})
    )
    assert client.server_version()["version"] == "abc1234"


@respx.mock
def test_version_reports_which_pod_answered(client):
    """During a rollout two pods serve one address, so the answer says which one it was.

    Two calls reporting two commits looked like a failed build twice, and both times it
    was a rollout in progress. The pod name is what tells those two apart.
    """
    respx.get("https://api.example.com/version").mock(
        return_value=httpx.Response(
            200,
            json={
                "name": "ZAD",
                "version": "8373c72e",
                "pod": "operations-manager-64884cd948-ngwjz",
                "image": "operations-manager:rc-77",
                "dirty": False,
            },
        )
    )

    server = client.server_version()

    assert server["pod"] == "operations-manager-64884cd948-ngwjz"
    assert server["image"] == "operations-manager:rc-77"
