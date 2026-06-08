"""HTTP client for the ZAD Operations Manager API with retry and task polling."""

from __future__ import annotations

import sys
import time
from typing import Any
from urllib.parse import urljoin

import httpx
from pydantic import ValidationError

from zad_cli.api.errors import Diagnosis, Fault, diagnose_http_error, diagnose_task_failure
from zad_cli.api.models import DeploymentDetail, DeploymentListResponse, TaskStatus


class ZadApiError(Exception):
    """Raised when the ZAD API returns an error.

    Carries a :class:`~zad_cli.api.errors.Diagnosis` so the CLI can render an
    honest, source-labelled message instead of a bare ``HTTP <code>``.
    """

    def __init__(self, status_code: int, message: str, details: dict | None = None, diagnosis: Diagnosis | None = None):
        self.status_code = status_code
        self.message = message
        self.details = details or {}
        self.diagnosis = diagnosis
        super().__init__(f"HTTP {status_code}: {message}")


class TaskTimeoutError(Exception):
    """Raised when task polling exceeds the timeout."""

    def __init__(self, message: str, task_id: str | None = None, diagnosis: Diagnosis | None = None):
        self.task_id = task_id
        self.diagnosis = diagnosis
        super().__init__(message)


class TaskFailedError(Exception):
    """Raised when a polled task reports failure."""

    def __init__(self, message: str, details: dict | None = None, diagnosis: Diagnosis | None = None):
        self.message = message
        self.details = details or {}
        self.diagnosis = diagnosis
        super().__init__(message)


_RETRYABLE_CODES = {429, 500, 502, 503, 504}


def _parse_v2_response(model_cls: type, payload: Any) -> dict:
    """Validate a v2 response and re-emit as dict, translating ValidationError to ZadApiError(502)."""
    try:
        return model_cls.model_validate(payload).model_dump(mode="json")
    except ValidationError as e:
        raise ZadApiError(
            502,
            f"Unexpected API response shape for {model_cls.__name__}: {e}",
            diagnosis=Diagnosis(
                fault=Fault.PLATFORM,
                headline="ZAD returned a response this CLI couldn't read — likely a CLI/API version mismatch.",
                summary=f"Schema {model_cls.__name__} failed to validate.",
                next_steps=[
                    "Retry shortly (exit code 2 = transient).",
                    "If it persists, the CLI may be out of date — update it or report the mismatch.",
                ],
                status_code=502,
            ),
        ) from e


class ZadClient:
    """Synchronous HTTP client for the ZAD Operations Manager API."""

    def __init__(
        self,
        api_url: str,
        api_key: str,
        *,
        max_retries: int = 3,
        retry_delay: int = 2,
        task_timeout: int = 300,
        task_poll_interval: int = 3,
    ):
        self.api_url = api_url.rstrip("/")
        self.auth_headers = {"X-API-Key": api_key}
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.task_timeout = task_timeout
        self.task_poll_interval = task_poll_interval
        self.wait = True  # Set to False for --no-wait mode
        self.verbose = False  # Set to True for --verbose mode
        self._client = httpx.Client(
            base_url=self.api_url,
            headers={**self.auth_headers, "Content-Type": "application/json"},
            timeout=60.0,
        )

    @property
    def web_url(self) -> str:
        """Base URL for the web UI (strips /api suffix)."""
        url = self.api_url
        if url.endswith("/api"):
            url = url[:-4]
        return url.rstrip("/")

    def close(self) -> None:
        self._client.close()

    # --- Low-level ---

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        """HTTP request with retry on transient errors."""
        delay = self.retry_delay
        last_error: Exception | None = None

        if self.verbose:
            print(f"--> {method} {self.api_url}{path}", file=sys.stderr)
            if kwargs.get("json"):
                print(f"    Body: {kwargs['json']}", file=sys.stderr)
            if kwargs.get("params"):
                print(f"    Params: {kwargs['params']}", file=sys.stderr)

        for attempt in range(self.max_retries + 1):
            try:
                response = self._client.request(method, path, **kwargs)
            except httpx.ConnectError as e:
                last_error = e
                if attempt < self.max_retries:
                    print(f"Connection error, retrying in {delay}s...", file=sys.stderr)
                    time.sleep(delay)
                    delay *= 2
                    continue
                raise ZadApiError(0, f"Connection failed: {e}", diagnosis=diagnose_http_error(0, str(e))) from e

            if response.status_code in _RETRYABLE_CODES and attempt < self.max_retries:
                print(f"HTTP {response.status_code}, retrying in {delay}s...", file=sys.stderr)
                time.sleep(delay)
                delay *= 2
                last_error = self._http_error(response)
                continue

            if response.status_code >= 400:
                raise self._http_error(response)

            if self.verbose:
                print(f"<-- {response.status_code} ({response.elapsed.total_seconds():.2f}s)", file=sys.stderr)

            return response

        raise last_error or ZadApiError(0, "Request failed")

    @staticmethod
    def _http_error(response: httpx.Response) -> ZadApiError:
        """Build a diagnosed ZadApiError from a >=400 response."""
        try:
            body: Any = response.json()
        except Exception:
            body = response.text
        if isinstance(body, dict):
            message = body.get("message") or body.get("detail") or response.text
        else:
            message = response.text or str(body)
        if not isinstance(message, str):
            message = str(message)
        return ZadApiError(response.status_code, message, diagnosis=diagnose_http_error(response.status_code, body))

    def _async_request(self, method: str, path: str, **kwargs: Any) -> dict:
        """Make a v2 async request. Polls for result unless self.wait is False."""
        response = self._request(method, path, **kwargs)
        data = response.json()

        task_id = data.get("task_id")
        if task_id and not self.wait:
            return {"task_id": task_id, "status": "accepted", "poll": f"zad task status {task_id}"}

        if task_id:
            return self._poll_task(f"/tasks/{task_id}")

        poll_url = data.get("poll_url")
        if poll_url and not self.wait:
            return data
        if poll_url:
            return self._poll_task(poll_url)

        return data

    def _build_poll_url(self, poll_url: str) -> str:
        if poll_url.startswith("http"):
            return poll_url
        return urljoin(self.api_url + "/", poll_url.lstrip("/"))

    def _poll_task(self, poll_url: str) -> dict:
        """Poll task until completed, failed, or timeout."""
        from rich.console import Console

        absolute_url = self._build_poll_url(poll_url)
        # Extract task ID from poll URL (e.g. /tasks/abc-123 -> abc-123)
        task_id = poll_url.rstrip("/").rsplit("/", 1)[-1] if "/" in poll_url else None
        deadline = time.time() + self.task_timeout
        console = Console(stderr=True)

        with console.status("Waiting for task...", spinner="dots") as spinner:
            while time.time() < deadline:
                try:
                    response = self._client.get(absolute_url)
                    data = response.json()
                except (httpx.HTTPError, ValueError):
                    # ValueError catches JSONDecodeError from empty/invalid response bodies
                    time.sleep(self.task_poll_interval)
                    continue

                if response.status_code >= 400:
                    raise self._http_error(response)

                status = TaskStatus(**data) if isinstance(data, dict) else TaskStatus(status="unknown")
                task_id = task_id or data.get("task_id")

                step = status.current_step or status.status
                pct = f" ({status.progress_percent}%)" if status.progress_percent is not None else ""
                spinner.update(f"{step}{pct}")

                if status.status == "completed":
                    return status.result or data
                if status.status == "failed":
                    raise TaskFailedError(
                        status.error_message or "Task failed",
                        details=status.result,
                        diagnosis=diagnose_task_failure(status.error_message, status.result),
                    )
                if status.status == "cancelled":
                    raise TaskFailedError(
                        "Task was cancelled",
                        diagnosis=Diagnosis(
                            fault=Fault.UNKNOWN,
                            headline="The task was cancelled before it finished.",
                            next_steps=["Re-run the command, or check `zad task list` for details."],
                        ),
                    )

                time.sleep(self.task_poll_interval)

        raise TaskTimeoutError(
            f"Task did not complete within {self.task_timeout}s",
            task_id=task_id,
            diagnosis=Diagnosis(
                fault=Fault.UNKNOWN,
                headline=f"Timed out after {self.task_timeout}s waiting for the task — it may still be running.",
                next_steps=["This is a wait limit, not a failure. Check `zad task status <id>`."],
            ),
        )

    # --- V2 project/deployment operations (async, poll for result) ---

    def upsert_deployment(self, project: str, payload: dict) -> dict:
        """Create or update a deployment."""
        return self._async_request("POST", f"/v2/projects/{project}/:upsert-deployment", json=payload)

    def refresh_project(self, project: str, force_clone: bool = False) -> dict:
        """Refresh all deployments in a project from git."""
        return self._async_request("POST", f"/v2/projects/{project}/:refresh", params={"force_clone": force_clone})

    def refresh_deployment(self, project: str, deployment: str, force_clone: bool = False) -> dict:
        """Refresh a single deployment from git."""
        return self._async_request(
            "POST", f"/v2/projects/{project}/deployments/{deployment}/:refresh", params={"force_clone": force_clone}
        )

    def delete_deployment(self, project: str, deployment: str) -> dict:
        """Delete a deployment."""
        return self._async_request("DELETE", f"/v2/projects/{project}/{deployment}")

    def update_image(self, project: str, deployment: str, component: str, image: str, **kwargs: Any) -> dict:
        """Update a component's container image."""
        payload: dict = {"componentName": component, "newImageUrl": image}
        if kwargs.get("services"):
            payload["services"] = kwargs["services"]
        return self._async_request("PUT", f"/v2/projects/{project}/deployments/{deployment}/image", json=payload)

    def clone_database(self, project: str, deployment: str, payload: dict) -> dict:
        """Clone database from external source."""
        return self._async_request(
            "POST", f"/v2/projects/{project}/deployments/{deployment}/:clone-database", json=payload
        )

    def clone_bucket(self, project: str, deployment: str, payload: dict) -> dict:
        """Clone bucket from external source."""
        return self._async_request(
            "POST", f"/v2/projects/{project}/deployments/{deployment}/:clone-bucket", json=payload
        )

    # --- V2 component/service operations (async) ---

    def add_component(self, project: str, payload: dict) -> dict:
        """Add a new component to a project."""
        return self._async_request("POST", f"/v2/projects/{project}/components", json=payload)

    def add_component_to_deployment(self, project: str, deployment: str, payload: dict) -> dict:
        """Assign an existing component to a deployment."""
        return self._async_request("POST", f"/v2/projects/{project}/deployments/{deployment}/components", json=payload)

    def add_service(self, project: str, payload: dict) -> dict:
        """Add a service to a project."""
        return self._async_request("POST", f"/v2/projects/{project}/services", json=payload)

    def delete_component(self, project: str, component_name: str) -> dict:
        """Delete a component from a project."""
        return self._async_request("DELETE", f"/v2/projects/{project}/components/{component_name}")

    def remove_service(self, project: str, service_name: str) -> dict:
        """Remove a service from a project."""
        return self._async_request("DELETE", f"/v2/projects/{project}/services/{service_name}")

    # --- V1 sync project operations ---

    def list_projects(self) -> list[dict]:
        """List all projects the current API key has access to."""
        response = self._request("GET", "/projects")
        return response.json()

    def delete_project(self, project: str, confirm: bool = True, force: bool = False) -> dict:
        """Delete a project (sync, no task polling)."""
        payload = {"confirmDeletion": confirm, "force": force}
        response = self._request("DELETE", f"/projects/{project}", json=payload)
        return response.json()

    def validate_clone(self, project: str, deployment: str) -> dict:
        """Validate clone configuration without executing."""
        response = self._request("POST", f"/projects/{project}/deployments/{deployment}/:validate-clone")
        return response.json()

    # --- Subdomain endpoints ---

    def check_subdomain(self, subdomain: str, base_domain: str) -> dict:
        """Check subdomain availability."""
        response = self._request("GET", f"/subdomains/check/{subdomain}", params={"base_domain": base_domain})
        return response.json()

    def list_subdomains(self, project: str | None = None) -> dict:
        """List subdomain registrations."""
        params = {"project_name": project} if project else {}
        response = self._request("GET", "/subdomains", params=params)
        return response.json()

    # --- Resource tuning ---

    def tune_resources(self, project: str, deployment: str | None = None) -> dict:
        """Auto-tune CPU/memory from Prometheus usage data."""
        params = {"deployment": deployment} if deployment else {}
        response = self._request("POST", f"/resources/{project}/tune", params=params)
        return response.json()

    def sanitize(self, project: str, deployment: str | None = None) -> dict:
        """Detect and disable broken deployments."""
        params = {"deployment": deployment} if deployment else {}
        response = self._request("POST", f"/resources/{project}/sanitize", params=params)
        return response.json()

    # --- Task management ---

    def get_task(self, task_id: str) -> dict:
        """Get current status of an async task."""
        response = self._request("GET", f"/tasks/{task_id}")
        return response.json()

    def list_tasks(self, project: str | None = None, status: str | None = None) -> dict:
        """List async tasks."""
        params: dict[str, str] = {}
        if project:
            params["project_name"] = project
        if status:
            params["status"] = status
        response = self._request("GET", "/tasks", params=params)
        return response.json()

    def wait_for_task(self, task_id: str) -> dict:
        """Block until an async task completes, showing progress."""
        return self._poll_task(f"/tasks/{task_id}")

    def cancel_task(self, task_id: str) -> dict:
        """Cancel a running task."""
        response = self._request("POST", f"/tasks/{task_id}:cancel")
        return response.json()

    # --- Backup endpoints ---

    def backup_status(self) -> dict:
        response = self._request("GET", "/v1/backup/status")
        return response.json()

    def backup_project(self, project: str, deployment: str) -> dict:
        response = self._request("POST", f"/v1/backup/project/{project}/deployment/{deployment}")
        return response.json()

    def backup_namespace(self, namespace: str) -> dict:
        response = self._request("POST", f"/v1/backup/namespace/{namespace}")
        return response.json()

    def backup_database(self, namespace: str, reference: str) -> dict:
        response = self._request("POST", f"/v1/backup/database/{namespace}/{reference}")
        return response.json()

    def backup_bucket(self, namespace: str, reference: str) -> dict:
        response = self._request("POST", f"/v1/backup/bucket/{namespace}/{reference}")
        return response.json()

    def list_backup_runs(self, project: str, deployment: str) -> dict:
        response = self._request("GET", f"/v1/backup/runs/{project}/{deployment}")
        return response.json()

    def delete_snapshot(self, project: str, deployment: str, snapshot_id: str) -> dict:
        response = self._request("DELETE", f"/v1/backup/snapshot/{project}/{deployment}/{snapshot_id}")
        return response.json()

    # --- Restore endpoints ---

    def list_snapshots(self, cluster: str, namespace: str) -> dict:
        response = self._request("GET", f"/v1/restore/snapshots/{cluster}/{namespace}")
        return response.json()

    def list_pvc_snapshots(self, cluster: str, namespace: str, pvc_name: str) -> dict:
        """List available Kopia snapshots for a specific PVC."""
        response = self._request("GET", f"/v1/restore/snapshots/{cluster}/{namespace}/{pvc_name}")
        return response.json()

    def restore_project(self, project: str) -> dict:
        response = self._request("POST", f"/v1/restore/project/{project}")
        return response.json()

    def restore_deployment_resource(self, project: str, deployment: str, payload: dict) -> dict:
        """Restore a resource (PVC, database, or bucket) for a deployment with versioning."""
        response = self._request("POST", f"/v1/restore/project/{project}/deployment/{deployment}", json=payload)
        return response.json()

    def restore_backup_run(self, project: str, deployment: str, backup_run_id: str) -> dict:
        response = self._request("POST", f"/v1/restore/project/{project}/deployment/{deployment}/run/{backup_run_id}")
        return response.json()

    def restore_pvc(self, cluster: str, namespace: str, pvc_name: str) -> dict:
        response = self._request("POST", f"/v1/restore/pvc/{cluster}/{namespace}/{pvc_name}")
        return response.json()

    def restore_database(self, cluster: str, namespace: str, reference: str) -> dict:
        response = self._request("POST", f"/v1/restore/database/{cluster}/{namespace}/{reference}")
        return response.json()

    def restore_bucket(self, cluster: str, namespace: str, reference: str) -> dict:
        response = self._request("POST", f"/v1/restore/bucket/{cluster}/{namespace}/{reference}")
        return response.json()

    # --- Admin endpoints ---

    def list_admin_marked(self, project_name: str | None = None) -> dict:
        """List resources marked for deletion."""
        params = {"project_name": project_name} if project_name else {}
        response = self._request("GET", "/v2/admin/marked-for-deletion", params=params)
        return response.json()

    def delete_admin_mark(self, mark_id: str) -> dict:
        """Remove a specific deletion mark without purging the resource."""
        return self._async_request("DELETE", f"/v2/admin/marked-for-deletion/{mark_id}")

    def get_orphan_report(self) -> dict:
        """Run the orphan sweep and return the classification report."""
        response = self._request("GET", "/v2/admin/orphans/report")
        return response.json()

    def confirm_orphans(self, payload: dict) -> dict:
        """Mark confirmed orphan candidates for grace-period deletion."""
        response = self._request("POST", "/v2/admin/orphans/confirm", json=payload)
        return response.json()

    # --- Metrics ---

    def health(self) -> dict:
        response = self._request("GET", "/metrics/health")
        return response.json()

    def metrics_overview(self) -> dict:
        response = self._request("GET", "/metrics/overview")
        return response.json()

    def metrics_cpu(self, namespace: str | None = None) -> dict:
        params = {"namespace": namespace} if namespace else {}
        response = self._request("GET", "/metrics/cpu", params=params)
        return response.json()

    def metrics_memory(self, namespace: str | None = None) -> dict:
        params = {"namespace": namespace} if namespace else {}
        response = self._request("GET", "/metrics/memory", params=params)
        return response.json()

    def metrics_pods(self, namespace: str | None = None) -> dict:
        params = {"namespace": namespace} if namespace else {}
        response = self._request("GET", "/metrics/pods/count", params=params)
        return response.json()

    def metrics_network(self, namespace: str | None = None) -> dict:
        params = {"namespace": namespace} if namespace else {}
        response = self._request("GET", "/metrics/network", params=params)
        return response.json()

    def metrics_query(self, query: str) -> dict:
        response = self._request("GET", "/metrics/query", params={"query": query})
        return response.json()

    # --- Logs ---

    def get_logs(
        self,
        project: str,
        deployment: str | None = None,
        component: str | None = None,
        limit: int | None = None,
        since: str | None = None,
    ) -> dict:
        params: dict[str, str] = {}
        if deployment:
            params["deployment"] = deployment
        if component:
            params["component"] = component
        if limit:
            params["limit"] = str(limit)
        if since:
            params["since"] = since
        response = self._request("GET", f"/logs/{project}", params=params)
        return response.json()

    # --- V2 deployment read endpoints ---

    def list_deployments_v2(self, project: str) -> dict:
        """Read all deployments in a project from the v2 read endpoint."""
        response = self._request("GET", f"/v2/projects/{project}/deployments")
        return _parse_v2_response(DeploymentListResponse, response.json())

    def get_deployment_v2(self, project: str, deployment: str) -> dict:
        """Read a single deployment from the v2 read endpoint."""
        response = self._request("GET", f"/v2/projects/{project}/deployments/{deployment}")
        return _parse_v2_response(DeploymentDetail, response.json())

    # --- Project introspection ---

    def resolve_namespace(self, project: str, deployment: str) -> str:
        """Resolve a deployment name to its Kubernetes namespace."""
        return self.get_deployment_v2(project, deployment)["namespace"]

    def list_deployments(self, project: str) -> list[dict]:
        """List all deployments in a project."""
        data = self.list_deployments_v2(project)
        return [
            {
                "deployment": dep["name"],
                "project": dep["project"],
                "namespace": dep["namespace"],
                "components": [c["reference"] for c in dep["components"]],
                "status": dep["status"],
                "urls": dep["urls"],
                "sync_revision": dep["sync_revision"],
                "last_synced_at": dep["last_synced_at"],
                "errors": dep["errors"],
            }
            for dep in data["deployments"]
        ]

    def describe_deployment(self, project: str, deployment: str) -> dict:
        """Get a single deployment's detail."""
        dep = self.get_deployment_v2(project, deployment)
        return {
            "deployment": dep["name"],
            "project": dep["project"],
            "namespace": dep["namespace"],
            "components": [
                # k8s_deployment is a tombstone for backwards compatibility:
                # the v2 endpoint doesn't expose it, but consumers of the
                # legacy describe shape may still read the key.
                {"name": c["reference"], "image": c["image"], "k8s_deployment": ""}
                for c in dep["components"]
            ],
            "urls": dep["urls"],
            "status": dep["status"],
            "sync_revision": dep["sync_revision"],
            "last_synced_at": dep["last_synced_at"],
            "errors": dep["errors"],
        }

    def project_status(self, project: str) -> dict:
        """Get a project overview: deployments and subdomains."""
        deployments = self.list_deployments(project)
        subdomain_response = self._request("GET", "/subdomains", params={"project_name": project})
        subdomains = subdomain_response.json().get("items", [])
        return {
            "project": project,
            "deployments": deployments,
            "subdomains": subdomains,
        }
