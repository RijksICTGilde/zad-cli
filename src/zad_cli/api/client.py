"""HTTP client for the ZAD Operations Manager API with retry and task polling."""

from __future__ import annotations

import sys
import time
from typing import Any
from urllib.parse import urljoin

import httpx

from zad_cli.api.models import TaskStatus


class ZadApiError(Exception):
    """Raised when the ZAD API returns an error."""

    def __init__(self, status_code: int, message: str, details: dict | None = None):
        self.status_code = status_code
        self.message = message
        self.details = details or {}
        super().__init__(f"HTTP {status_code}: {message}")


class TaskTimeoutError(Exception):
    """Raised when task polling exceeds the timeout."""


class TaskFailedError(Exception):
    """Raised when a polled task reports failure."""

    def __init__(self, message: str, details: dict | None = None):
        self.message = message
        self.details = details or {}
        super().__init__(message)


_RETRYABLE_CODES = {429, 500, 502, 503, 504}


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
        self._client = httpx.Client(
            base_url=self.api_url,
            headers={**self.auth_headers, "Content-Type": "application/json"},
            timeout=60.0,
        )

    def close(self) -> None:
        self._client.close()

    # --- Low-level ---

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        """HTTP request with retry on transient errors."""
        delay = self.retry_delay
        last_error: Exception | None = None

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
                raise ZadApiError(0, f"Connection failed: {e}") from e

            if response.status_code in _RETRYABLE_CODES and attempt < self.max_retries:
                print(f"HTTP {response.status_code}, retrying in {delay}s...", file=sys.stderr)
                time.sleep(delay)
                delay *= 2
                last_error = ZadApiError(response.status_code, response.text)
                continue

            if response.status_code >= 400:
                try:
                    body = response.json()
                    message = body.get("message", body.get("detail", response.text))
                except Exception:
                    message = response.text
                raise ZadApiError(response.status_code, message)

            return response

        raise last_error or ZadApiError(0, "Request failed")

    def _async_request(self, method: str, path: str, **kwargs: Any) -> dict:
        """Make a v2 async request: returns 202, then polls /api/tasks/{task_id}."""
        response = self._request(method, path, **kwargs)
        data = response.json()

        # V2 endpoints return 202 with task_id
        task_id = data.get("task_id")
        if task_id:
            return self._poll_task(f"/tasks/{task_id}")

        # V1 fallback: poll_url in response body
        poll_url = data.get("poll_url")
        if poll_url:
            return self._poll_task(poll_url)

        return data

    def _build_poll_url(self, poll_url: str) -> str:
        if poll_url.startswith("http"):
            return poll_url
        return urljoin(self.api_url + "/", poll_url.lstrip("/"))

    def _poll_task(self, poll_url: str) -> dict:
        """Poll task until completed, failed, or timeout."""
        absolute_url = self._build_poll_url(poll_url)
        deadline = time.time() + self.task_timeout

        while time.time() < deadline:
            try:
                response = self._client.get(absolute_url)
                data = response.json()
            except Exception:
                time.sleep(self.task_poll_interval)
                continue

            status = TaskStatus(**data) if isinstance(data, dict) else TaskStatus(status="unknown")

            if status.status == "completed":
                return status.result or data
            if status.status == "failed":
                raise TaskFailedError(status.error_message or "Task failed", details=status.result)
            if status.status == "cancelled":
                raise TaskFailedError("Task was cancelled")

            time.sleep(self.task_poll_interval)

        raise TaskTimeoutError(f"Task did not complete within {self.task_timeout}s")

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

    # --- V1 sync project operations ---

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

    def restore_project(self, project: str) -> dict:
        response = self._request("POST", f"/v1/restore/project/{project}")
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
        self, project: str, deployment: str | None = None, container: str | None = None, limit: int | None = None
    ) -> str:
        params: dict[str, str] = {}
        if deployment:
            params["deployment"] = deployment
        if container:
            params["container"] = container
        if limit:
            params["limit"] = str(limit)
        response = self._request("GET", f"/logs/{project}", params=params)
        return response.text
