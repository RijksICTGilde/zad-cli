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


# Status codes that trigger a retry
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

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        """Make an HTTP request with retry logic."""
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
                raise ZadApiError(0, f"Connection failed after {self.max_retries + 1} attempts: {e}") from e

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

    def _build_poll_url(self, poll_url: str) -> str:
        """Build absolute poll URL from potentially relative path."""
        if poll_url.startswith("http"):
            return poll_url
        return urljoin(self.api_url + "/", poll_url.lstrip("/"))

    def _poll_task(
        self,
        poll_url: str,
        *,
        on_status: Any | None = None,
    ) -> dict:
        """Poll an async task until completion or timeout.

        Args:
            poll_url: URL to poll for task status.
            on_status: Optional callback(TaskStatus) for progress updates.

        Returns:
            The task result dict on success.

        Raises:
            TaskTimeoutError: If polling exceeds task_timeout.
            TaskFailedError: If the task reports failure.
        """
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

            if on_status:
                on_status(status)

            if status.status == "completed":
                return status.result or data
            if status.status == "failed":
                raise TaskFailedError(
                    status.error_message or "Task failed",
                    details=status.result,
                )
            if status.status == "cancelled":
                raise TaskFailedError("Task was cancelled")

            time.sleep(self.task_poll_interval)

        raise TaskTimeoutError(f"Task did not complete within {self.task_timeout}s")

    # --- Project endpoints ---

    def upsert_deployment(self, project_id: str, payload: dict) -> dict:
        """Create or update a deployment (async, polls for result)."""
        response = self._request("POST", f"/projects/{project_id}/:upsert-deployment", json=payload)
        data = response.json()
        if "poll_url" in data:
            return self._poll_task(data["poll_url"])
        return data

    def refresh_project(self, project_id: str, force_clone: bool = False) -> dict:
        """Refresh/retry a project."""
        params = {"force_clone": str(force_clone).lower()}
        response = self._request("GET", f"/projects/{project_id}/:refresh", params=params)
        return response.json()

    def delete_project(self, project_id: str, confirm: bool = True, force: bool = False) -> dict:
        """Delete a project."""
        payload = {"confirmDeletion": confirm, "force": force}
        response = self._request("DELETE", f"/projects/{project_id}", json=payload)
        data = response.json()
        if "poll_url" in data:
            return self._poll_task(data["poll_url"])
        return data

    def delete_deployment(self, project_id: str, deployment_name: str) -> dict:
        """Delete a single deployment."""
        response = self._request("DELETE", f"/projects/{project_id}/{deployment_name}")
        data = response.json()
        if "poll_url" in data:
            return self._poll_task(data["poll_url"])
        return data

    def update_image(
        self,
        project_id: str,
        deployment_name: str,
        component: str,
        image: str,
        services: dict | None = None,
    ) -> dict:
        """Update a deployment's container image."""
        payload: dict = {"componentName": component, "newImageUrl": image}
        if services:
            payload["services"] = services
        response = self._request("PUT", f"/projects/{project_id}/deployments/{deployment_name}/image", json=payload)
        return response.json()

    def validate_clone(self, project_id: str, deployment_name: str) -> dict:
        """Validate clone configuration without executing."""
        response = self._request("POST", f"/projects/{project_id}/deployments/{deployment_name}/:validate-clone")
        return response.json()

    # --- Subdomain endpoints ---

    def check_subdomain(self, project_id: str, subdomain: str, base_domain: str | None = None) -> dict:
        """Check subdomain availability."""
        params: dict[str, str] = {"subdomain": subdomain}
        if base_domain:
            params["base_domain"] = base_domain
        response = self._request("GET", f"/projects/{project_id}/:check-subdomain", params=params)
        return response.json()

    def list_subdomains(self, project_id: str) -> dict:
        """List project subdomains."""
        response = self._request("GET", f"/projects/{project_id}/:subdomains")
        return response.json()

    # --- Backup endpoints ---

    def backup_status(self) -> dict:
        response = self._request("GET", "/v1/backup/status")
        return response.json()

    def backup_project(self, project_name: str, deployment_name: str) -> dict:
        response = self._request("POST", f"/v1/backup/project/{project_name}/deployment/{deployment_name}")
        return response.json()

    def backup_namespace(self, namespace: str) -> dict:
        response = self._request("POST", f"/v1/backup/namespace/{namespace}")
        return response.json()

    def backup_database(self, namespace: str, reference_name: str) -> dict:
        response = self._request("POST", f"/v1/backup/database/{namespace}/{reference_name}")
        return response.json()

    def backup_bucket(self, namespace: str, reference_name: str) -> dict:
        response = self._request("POST", f"/v1/backup/bucket/{namespace}/{reference_name}")
        return response.json()

    def list_backup_runs(self, project_name: str, deployment_name: str) -> dict:
        response = self._request("GET", f"/v1/backup/runs/{project_name}/{deployment_name}")
        return response.json()

    def delete_snapshot(self, project_name: str, deployment_name: str, snapshot_id: str) -> dict:
        response = self._request("DELETE", f"/v1/backup/snapshot/{project_name}/{deployment_name}/{snapshot_id}")
        return response.json()

    # --- Restore endpoints ---

    def list_snapshots(self, cluster: str, namespace: str) -> dict:
        response = self._request("GET", f"/v1/restore/snapshots/{cluster}/{namespace}")
        return response.json()

    def restore_project(self, project_name: str) -> dict:
        response = self._request("POST", f"/v1/restore/project/{project_name}")
        return response.json()

    def restore_backup_run(self, project_name: str, deployment_name: str, backup_run_id: str) -> dict:
        response = self._request(
            "POST",
            f"/v1/restore/project/{project_name}/deployment/{deployment_name}/run/{backup_run_id}",
        )
        return response.json()

    def restore_pvc(self, cluster: str, namespace: str, pvc_name: str, payload: dict | None = None) -> dict:
        response = self._request("POST", f"/v1/restore/pvc/{cluster}/{namespace}/{pvc_name}", json=payload or {})
        return response.json()

    def restore_database(self, cluster: str, namespace: str, reference_name: str) -> dict:
        response = self._request("POST", f"/v1/restore/database/{cluster}/{namespace}/{reference_name}")
        return response.json()

    def restore_bucket(self, cluster: str, namespace: str, reference_name: str) -> dict:
        response = self._request("POST", f"/v1/restore/bucket/{cluster}/{namespace}/{reference_name}")
        return response.json()

    # --- Clone endpoints ---

    def clone_database(self, project_name: str, deployment_name: str, payload: dict) -> dict:
        response = self._request(
            "POST",
            f"/projects/{project_name}/deployments/{deployment_name}/:clone-database-from-external",
            json=payload,
        )
        return response.json()

    def clone_bucket(self, project_name: str, deployment_name: str, payload: dict) -> dict:
        response = self._request(
            "POST",
            f"/projects/{project_name}/deployments/{deployment_name}/:clone-bucket-from-external",
            json=payload,
        )
        return response.json()

    # --- Metrics endpoints ---

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

    # --- Log endpoints ---

    def get_logs(
        self,
        project_name: str,
        deployment: str | None = None,
        container: str | None = None,
        limit: int | None = None,
    ) -> str:
        params: dict[str, str] = {}
        if deployment:
            params["deployment"] = deployment
        if container:
            params["container"] = container
        if limit:
            params["limit"] = str(limit)
        response = self._request("GET", f"/logs/{project_name}", params=params)
        return response.text
