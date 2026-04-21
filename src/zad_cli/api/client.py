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

    def __init__(self, message: str, task_id: str | None = None):
        self.task_id = task_id
        super().__init__(message)


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

            if self.verbose:
                print(f"<-- {response.status_code} ({response.elapsed.total_seconds():.2f}s)", file=sys.stderr)

            return response

        raise last_error or ZadApiError(0, "Request failed")

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
                    raise ZadApiError(response.status_code, data.get("detail", data.get("message", str(data))))

                status = TaskStatus(**data) if isinstance(data, dict) else TaskStatus(status="unknown")
                task_id = task_id or data.get("task_id")

                step = status.current_step or status.status
                pct = f" ({status.progress_percent}%)" if status.progress_percent is not None else ""
                spinner.update(f"{step}{pct}")

                if status.status == "completed":
                    return status.result or data
                if status.status == "failed":
                    raise TaskFailedError(status.error_message or "Task failed", details=status.result)
                if status.status == "cancelled":
                    raise TaskFailedError("Task was cancelled")

                time.sleep(self.task_poll_interval)

        raise TaskTimeoutError(f"Task did not complete within {self.task_timeout}s", task_id=task_id)

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

    # --- Project introspection (derived from logs + tasks + subdomains) ---

    def resolve_namespace(self, project: str, deployment: str) -> str:
        """Resolve a deployment name to its Kubernetes namespace."""
        deployments = self.list_deployments(project)
        for dep in deployments:
            if dep["deployment"] == deployment:
                return dep["namespace"]
        raise ZadApiError(404, f"Deployment '{deployment}' not found in project '{project}'")

    def list_deployments(self, project: str) -> list[dict]:
        """List all deployments and their components in a project.

        Uses the logs endpoint with limit=0 to discover active deployments,
        and tasks to determine deployment status.
        """
        response = self._request("GET", f"/logs/{project}", params={"limit": "0"})
        data = response.json()

        deployments: dict[str, dict] = {}
        for entry in data.get("results", []):
            dep_name = entry["deployment"]
            if dep_name not in deployments:
                deployments[dep_name] = {
                    "deployment": dep_name,
                    "project": entry.get("project", project),
                    "namespace": entry.get("namespace", ""),
                    "components": [],
                    "status": "Active",
                }
            deployments[dep_name]["components"].append(entry["component"])

        # Enrich with last known task status per deployment
        task_response = self._request("GET", "/tasks", params={"project_name": project})
        tasks = task_response.json().get("tasks", [])
        seen: set[str] = set()
        for task in tasks:
            dep_name = (task.get("result") or {}).get("deployment") or {}
            dep_name = dep_name.get("name", "") if isinstance(dep_name, dict) else ""
            if not dep_name or dep_name in seen or dep_name not in deployments:
                continue
            seen.add(dep_name)
            if task.get("status") == "failed":
                deployments[dep_name]["status"] = "Failed"
            elif task.get("status") in ("pending", "running"):
                deployments[dep_name]["status"] = "Deploying"

        return list(deployments.values())

    def describe_deployment(self, project: str, deployment: str) -> dict:
        """Get detailed info about a deployment by combining logs and task history."""
        # Get components from logs
        response = self._request("GET", f"/logs/{project}", params={"deployment": deployment, "limit": "0"})
        log_data = response.json()

        components = []
        namespace = ""
        for entry in log_data.get("results", []):
            namespace = entry.get("namespace", namespace)
            components.append(
                {
                    "name": entry["component"],
                    "k8s_deployment": entry.get("k8s_deployment", ""),
                }
            )

        # Upstream has no `GET /projects/{p}/deployments/{d}` endpoint, so URLs
        # and image refs are reconstructed from completed task history. Filter
        # server-side to avoid paging all project tasks.
        urls = {}
        images: dict[str, str] = {}
        task_response = self._request(
            "GET",
            "/tasks",
            params={"project_name": project, "deployment_name": deployment, "status": "completed"},
        )
        tasks = task_response.json().get("tasks", [])
        for task in tasks:
            result = task.get("result") or {}
            if not isinstance(result, dict):
                continue
            dep_info = result.get("deployment") or {}
            if not isinstance(dep_info, dict):
                continue
            # Get URLs (prefer most recent)
            urls_data = result.get("urls") or {}
            dep_data = urls_data.get(deployment) or {}
            dep_urls = dep_data.get("urls", {}) if isinstance(dep_data, dict) else {}
            if dep_urls and not urls:
                urls = dep_urls
            # Accumulate images from all tasks (most recent wins per component)
            for comp in dep_info.get("components", []):
                ref = comp.get("reference", "")
                if ref and ref not in images:
                    images[ref] = comp.get("image", "")

        # Merge image info into components
        for comp in components:
            comp["image"] = images.get(comp["name"], "")

        return {
            "deployment": deployment,
            "project": project,
            "namespace": namespace,
            "components": components,
            "urls": urls,
        }

    def project_status(self, project: str) -> dict:
        """Get a project overview: deployments, components, subdomains."""
        deployments = self.list_deployments(project)

        # Get subdomain info
        subdomain_response = self._request("GET", "/subdomains", params={"project_name": project})
        subdomains = subdomain_response.json().get("items", [])

        # Get URLs from recent tasks
        task_response = self._request("GET", "/tasks", params={"project_name": project})
        tasks = task_response.json().get("tasks", [])
        urls_by_deployment: dict[str, dict] = {}
        for task in tasks:
            if task.get("status") != "completed":
                continue
            result = task.get("result") or {}
            if not isinstance(result, dict):
                continue
            for dep_name, dep_urls in result.get("urls", {}).items():
                if not isinstance(dep_urls, dict):
                    continue
                if dep_name not in urls_by_deployment and dep_urls.get("urls"):
                    urls_by_deployment[dep_name] = dep_urls["urls"]

        # Enrich deployments with URLs
        for dep in deployments:
            dep["urls"] = urls_by_deployment.get(dep["deployment"], {})

        return {
            "project": project,
            "deployments": deployments,
            "subdomains": subdomains,
        }
