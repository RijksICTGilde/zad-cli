"""HTTP client for the ZAD Operations Manager API with retry and task polling."""

from __future__ import annotations

import sys
import time
from contextlib import contextmanager
from typing import Any
from urllib.parse import urlsplit

import httpx
from pydantic import ValidationError

from zad_cli.api.errors import Diagnosis, Fault, diagnose_http_error, diagnose_task_failure, result_failure
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


class _SilentSpinner:
    """Answers `update()` and does nothing, so the polling loop needs no branches."""

    def update(self, *_args: Any, **_kwargs: Any) -> None:
        return None


def spec_accepts_deferral(method: str, path: str) -> bool:
    """Whether this operation can be asked to save without rolling out."""
    from zad_cli.api import spec

    return spec.accepts_rollout(method, path, value=False)


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
                headline="ZAD returned a response this CLI couldn't read; likely a CLI/API version mismatch.",
                summary=f"Schema {model_cls.__name__} failed to validate.",
                next_steps=[
                    "Retry shortly (exit code 2 = transient).",
                    "If it persists, the CLI may be out of date; update it or report the mismatch.",
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
        first_poll_interval: float = 0.3,
    ):
        self.api_url = api_url.rstrip("/")
        self.auth_headers = {"X-API-Key": api_key}
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.task_timeout = task_timeout
        # The ceiling, not the rate. Polling started at a flat 3s, so a task the platform
        # finished in a second still cost three: measured against the sandbox, `env add`
        # took 3.07s of which 1.4s was the platform and the rest was this sleep. Twenty
        # mutating steps in a playbook made that half a minute of waiting for nothing.
        # Starting small and growing costs the platform a couple of extra requests on
        # short tasks and settles back to one every 3s on a rollout, which is where the
        # gentle rate is actually wanted.
        self.task_poll_interval = task_poll_interval
        self.first_poll_interval = first_poll_interval
        self.wait = True  # Set to False for --no-wait mode
        self.verbose = False  # Set to True for --verbose mode
        # None keeps the API's own default; False is --no-rollout, which saves the change
        # to the project file without reconciling the cluster. Applied only to operations
        # the spec says accept the parameter.
        self.rollout: bool | None = None
        # Counts requests this process actually sent with rollout=false, so the CLI can
        # say afterwards that something is now waiting instead of leaving it invisible.
        self.rollout_deferred = 0
        self._client = httpx.Client(
            base_url=self.api_url,
            # No default Content-Type: httpx sets application/json for json= bodies and
            # the multipart boundary for file uploads. A fixed default would break uploads.
            headers={**self.auth_headers},
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

        kwargs = self._with_rollout(method, path, kwargs)

        if self.verbose:
            # Method, path, body and params only. Headers are never printed: they carry
            # the API key and, for the two SSO endpoints, a bearer token.
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

    def _with_rollout(self, method: str, path: str, kwargs: dict[str, Any]) -> dict[str, Any]:
        """Add ``rollout`` to a request, but only where the API documents it.

        Saving and rolling out are two things: with ``rollout=false`` the change lands in
        the project file and the cluster is left alone until a refresh. Which operations
        accept the parameter is read from the vendored spec, never from a list here.
        """
        if self.rollout is None or "rollout" in (kwargs.get("params") or {}):
            return kwargs
        from zad_cli.api import spec

        if not spec.accepts_rollout(method, path, value=self.rollout):
            return kwargs
        params = dict(kwargs.get("params") or {})
        params["rollout"] = self.rollout
        if self.rollout is False:
            self.rollout_deferred += 1
        return {**kwargs, "params": params}

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
        # Read back which credential actually went out, rather than threading that through
        # every call site: the response knows its own request.
        sent = response.request.headers if response.request is not None else {}
        auth = "bearer" if str(sent.get("Authorization", "")).lower().startswith("bearer ") else "api-key"
        return ZadApiError(
            response.status_code,
            message,
            diagnosis=diagnose_http_error(response.status_code, body, auth=auth),
        )

    def _async_request(self, method: str, path: str, **kwargs: Any) -> dict:
        """Make a v2 async request. Polls for result unless self.wait is False."""
        response = self._request(method, path, **kwargs)
        data = response.json()

        task_id = data.get("task_id")
        if task_id and not self.wait:
            return {"task_id": task_id, "status": "accepted", "poll": f"zadctl task status {task_id}"}

        # A deferred change writes the project file and stops; only a real rollout takes
        # long enough to be worth watching.
        rolling_out = not (self.rollout is False and spec_accepts_deferral(method, path))

        if task_id:
            return self._poll_task(f"/tasks/{task_id}", progress=rolling_out)

        poll_url = data.get("poll_url")
        if poll_url and not self.wait:
            return data
        if poll_url:
            return self._poll_task(poll_url, progress=rolling_out)

        return data

    @staticmethod
    @contextmanager
    def _spinner(enabled: bool):
        """A Rich status line, or a silent stand-in that answers the same calls."""
        if not enabled:
            yield _SilentSpinner()
            return
        from rich.console import Console

        with Console(stderr=True).status("Waiting for task...", spinner="dots") as status:
            yield status

    def _build_poll_url(self, poll_url: str) -> str:
        """Absolute URL for a poll location, given either form the API hands out.

        The API's own ``poll_url`` is absolute from the host (``/api/tasks/<id>``) while
        ``_async_request`` builds a relative one (``/tasks/<id>``). The base already ends
        in ``/api`` in every real deployment, so joining the first form naively produced
        ``/api/api/tasks/<id>`` and a 404. That went unseen because nothing passed the
        server's own value through until project creation started waiting on it, and
        because a test base URL has no path to double.
        """
        if poll_url.startswith("http"):
            return poll_url

        base = self.api_url.rstrip("/")
        prefix = urlsplit(base).path.rstrip("/")
        path = "/" + poll_url.lstrip("/")
        if prefix and (path == prefix or path.startswith(prefix + "/")):
            path = path[len(prefix) :] or "/"
        return base + path

    def _poll_task(self, poll_url: str, *, progress: bool = True, headers: dict[str, str] | None = None) -> dict:
        """Poll task until completed, failed, or timeout.

        ``progress`` off still waits; it only leaves the spinner out. Saving a change
        without rolling it out takes about a second, so a progress display there is motion
        for its own sake: it appears and disappears before it has said anything.

        ``headers`` is for the one task that cannot be polled with an API key: creating a
        project, where the key does not work until the project it belongs to exists.
        """
        absolute_url = self._build_poll_url(poll_url)
        # Extract task ID from poll URL (e.g. /tasks/abc-123 -> abc-123)
        task_id = poll_url.rstrip("/").rsplit("/", 1)[-1] if "/" in poll_url else None
        deadline = time.time() + self.task_timeout
        delay = self.first_poll_interval

        with self._spinner(progress) as spinner:
            while time.time() < deadline:
                try:
                    response = self._client.get(absolute_url, headers=headers)
                    data = response.json()
                except (httpx.HTTPError, ValueError):
                    # ValueError catches JSONDecodeError from empty/invalid response bodies
                    time.sleep(delay)
                    delay = min(delay * 1.5, self.task_poll_interval)
                    continue

                if response.status_code >= 400:
                    raise self._http_error(response)

                status = TaskStatus(**data) if isinstance(data, dict) else TaskStatus(status="unknown")
                task_id = task_id or data.get("task_id")

                step = status.current_step or status.status
                pct = f" ({status.progress_percent}%)" if status.progress_percent is not None else ""
                spinner.update(f"{step}{pct}")

                if status.status == "completed":
                    result = status.result or data
                    refusal = result_failure(result)
                    if refusal:
                        raise TaskFailedError(
                            refusal,
                            details=result if isinstance(result, dict) else None,
                            diagnosis=diagnose_task_failure(refusal, result, task_id, data.get("subtasks")),
                        )
                    return result
                if status.status == "failed":
                    raise TaskFailedError(
                        status.error_message or "Task failed",
                        details=status.result,
                        diagnosis=diagnose_task_failure(
                            status.error_message, status.result, task_id, data.get("subtasks")
                        ),
                    )
                if status.status == "cancelled":
                    raise TaskFailedError(
                        "Task was cancelled",
                        diagnosis=Diagnosis(
                            fault=Fault.UNKNOWN,
                            headline="The task was cancelled before it finished.",
                            next_steps=["Re-run the command, or check `zadctl task list` for details."],
                        ),
                    )

                time.sleep(delay)
                delay = min(delay * 1.5, self.task_poll_interval)

        raise TaskTimeoutError(
            f"Task did not complete within {self.task_timeout}s",
            task_id=task_id,
            diagnosis=Diagnosis(
                fault=Fault.UNKNOWN,
                headline=f"Timed out after {self.task_timeout}s waiting for the task; it may still be running.",
                next_steps=["This is a wait limit, not a failure. Check `zadctl task status <id>`."],
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

    def update_component(self, project: str, component_name: str, payload: dict) -> dict:
        """Partially update an existing component (only provided fields change)."""
        return self._async_request("PATCH", f"/v2/projects/{project}/components/{component_name}", json=payload)

    def delete_component(self, project: str, component_name: str, *, confirm_in_use: bool = False) -> dict:
        """Delete a component from a project.

        ``confirm_in_use`` also removes the references to it. Off by default, because the
        409 it would otherwise skip past is the list of what still uses the component.
        """
        params = {"confirm_in_use": "true"} if confirm_in_use else None
        return self._async_request("DELETE", f"/v2/projects/{project}/components/{component_name}", params=params)

    # --- V2 service registry and per-service config ---

    def sleep_mode_status(self, project: str, deployment: str, wake_token: str | None = None) -> dict:
        """Whether a deployment is asleep right now. Served outside the /v2 tree.

        These two endpoints are the waker page's own, and the platform gates them on an
        `X-Wake-Token` header rather than on the project API key. The spec documents neither
        the header nor where a token comes from; until it does, the caller supplies one.
        """
        headers = {"X-Wake-Token": wake_token} if wake_token else None
        response = self._request("GET", f"/sleep-mode/{project}/{deployment}/status", headers=headers)
        return response.json()

    def wake_deployment(self, project: str, deployment: str, wake_token: str | None = None) -> dict:
        """Wake a sleeping deployment without waiting for a visitor to do it."""
        headers = {"X-Wake-Token": wake_token} if wake_token else None
        response = self._request("POST", f"/sleep-mode/{project}/{deployment}/wake", headers=headers)
        return response.json()

    def get_service_config(self, project: str, service_name: str) -> dict:
        """Read a service's current config across every target it is set on."""
        response = self._request("GET", f"/v2/projects/{project}/services/{service_name}/config")
        return response.json()

    def put_service_config(self, path: str, payload: Any) -> dict:
        """Write a service's config at one layer.

        Takes the path rather than (service, layer): the layer's endpoint comes from the
        service registry, so the client does not need a table of ~50 config endpoints.
        """
        return self._async_request("PUT", path, json=payload)

    def patch_service_config(self, path: str, payload: dict) -> dict:
        """Add, replace or remove single entries of a list-shaped config block.

        Only for the blocks whose config model is a list with a unique key. The PUT writes
        the block whole, so removing one entry meant resending every other one -- and an
        entry left out of a storage list takes its PVC and the data on it. This is the
        endpoint that answers that; see question 18 in RIG-Cluster's
        `plans/vragen-uit-zad-cli.md`.
        """
        return self._async_request("PATCH", path, json=payload)

    def delete_service_config(self, path: str) -> dict:
        """Clear a service's config at one layer."""
        return self._async_request("DELETE", path)

    def get_service_values(self, project: str, service_name: str) -> dict:
        """Read a service's key/value map (user-env-vars, aliases) across its layers."""
        return self.get_service_config(project, service_name)

    def read_service_values(self, path: str) -> dict:
        """Read the values stored at one layer.

        Synchronous, unlike the writes on the same path: this reads the project file, so
        there is no task to poll. Takes the path for the same reason the writers do — the
        layer's endpoint comes from the registry.
        """
        response = self._request("GET", path)
        return response.json()

    def add_service_values(self, path: str, values: dict[str, str]) -> dict:
        """Add values; keys that already exist are a conflict (POST semantics)."""
        return self._async_request("POST", path, json={"values": values})

    def change_service_values(self, path: str, values: dict[str, str]) -> dict:
        """Change values that already exist (PATCH semantics)."""
        return self._async_request("PATCH", path, json={"values": values})

    def clear_service_values(self, path: str) -> dict:
        """Remove every value at this layer."""
        return self._async_request("DELETE", path)

    def remove_service_values(self, path: str, keys: list[str]) -> dict:
        """Remove several named values in one call."""
        return self._async_request("POST", f"{path}/:delete", json={"keys": keys})

    def remove_service_value(self, path: str, key: str) -> dict:
        """Remove exactly one value."""
        return self._async_request("DELETE", f"{path}/{key}")

    # --- Attachments ---
    #
    # These are the only multipart endpoints in the API: the file goes up as an upload,
    # not as JSON, so they pass files=/data= instead of json=.

    @staticmethod
    def _form(fields: dict[str, str], *, filename: str | None = None, content: bytes | None = None) -> dict:
        """Build a multipart body from plain fields plus an optional upload.

        Every field goes through ``files`` as a ``(None, value)`` part. Passing them as
        ``data`` instead would make httpx fall back to ``application/x-www-form-urlencoded``
        whenever there is no file, and these endpoints declare ``multipart/form-data``.
        """
        parts: dict = {key: (None, value) for key, value in fields.items()}
        if content is not None:
            parts["file"] = (filename or "upload", content)
        return parts

    def create_attachment(self, project: str, attachment_id: str, filename: str, content: bytes) -> dict:
        """Put a file in the project's attachments catalog."""
        return self._async_request(
            "POST",
            f"/v2/projects/{project}/services/attachments/attachment",
            files=self._form({"attachment_id": attachment_id}, filename=filename, content=content),
        )

    def update_attachment(
        self, project: str, attachment_id: str, filename: str, content: bytes, *, upsert: bool = False
    ) -> dict:
        """Replace an attachment's content, leaving its couplings alone."""
        path = f"/v2/projects/{project}/services/attachments/attachment/{attachment_id}"
        return self._async_request(
            "PUT", path, files=self._form({}, filename=filename, content=content), params={"upsert": upsert}
        )

    def delete_attachment(self, project: str, attachment_id: str, *, confirm_in_use: bool = False) -> dict:
        """Remove an attachment from the catalog."""
        return self._async_request(
            "DELETE",
            f"/v2/projects/{project}/services/attachments/attachment/{attachment_id}",
            params={"confirm_in_use": confirm_in_use},
        )

    def assign_attachment(
        self,
        project: str,
        component: str,
        attachment_id: str,
        coupling: dict[str, str],
        *,
        filename: str | None = None,
        content: bytes | None = None,
        replace: bool = False,
        upsert: bool = False,
    ) -> dict:
        """Bind an attachment to a component, optionally uploading it in the same call.

        With ``content`` the file lands in the catalog and the coupling is written in one
        request; without it, ``attachment_id`` must already be in the catalog and only the
        coupling changes.
        """
        base = f"/v2/projects/{project}/services/attachments/component/{component}/attachment"
        fields: dict[str, str] = dict(coupling)
        if content is not None:
            fields["attachment_id"] = attachment_id
        elif not replace:
            # No file: name the catalog entry to couple, and leave its content alone.
            fields["reference"] = attachment_id
        files = self._form(fields, filename=filename or attachment_id, content=content)

        if replace:
            return self._async_request("PUT", f"{base}/{attachment_id}", files=files, params={"upsert": upsert})
        return self._async_request("POST", base, files=files)

    # --- Database schemas ---

    def list_database_schemas(self, project: str) -> dict:
        """The extra PostgreSQL schemas configured for a project."""
        response = self._request("GET", f"/v2/projects/{project}/services/postgresql-database/schemas")
        return response.json()

    def add_database_schema(self, project: str, payload: dict) -> dict:
        """Add an extra schema by postfix."""
        return self._async_request("POST", f"/v2/projects/{project}/services/postgresql-database/schemas", json=payload)

    def remove_database_schema(self, project: str, postfix: str, *, forget: bool = False) -> dict:
        """Remove an extra schema; ``forget`` drops it without cleaning the database up."""
        return self._async_request(
            "DELETE",
            f"/v2/projects/{project}/services/postgresql-database/schemas/{postfix}",
            params={"forget": forget},
        )

    # --- Registries ---

    def add_registry_by_credentials(self, project: str, payload: dict) -> dict:
        """Register a pull registry with a username and password."""
        response = self._request("POST", f"/projects/{project}/registries/by-credentials", json=payload)
        return response.json()

    def add_registry_by_secret(self, project: str, payload: dict) -> dict:
        """Register a pull registry that points at an existing Kubernetes secret."""
        response = self._request("POST", f"/projects/{project}/registries/by-secret", json=payload)
        return response.json()

    # --- Admin ---

    def trigger_cleanup(
        self, project: str | None, *, dry_run: bool = True, grace_period_days: int | None = None
    ) -> dict:
        """Purge resources that are marked for deletion and past the grace period."""
        params: dict[str, Any] = {"dry_run": dry_run}
        if project:
            params["project_name"] = project
        if grace_period_days is not None:
            params["grace_period_days"] = grace_period_days
        response = self._request("POST", "/v2/admin/cleanup/trigger", params=params)
        return response.json()

    def trigger_reconciliation(self, *, dry_run: bool = True, grace_period_days: int | None = None) -> dict:
        """Run a full reconciliation: unmark what reappeared, purge what expired."""
        params: dict[str, Any] = {"dry_run": dry_run}
        if grace_period_days is not None:
            params["grace_period_days"] = grace_period_days
        response = self._request("POST", "/v2/admin/reconciliation/trigger", params=params)
        return response.json()

    def reconcile_projects(self) -> dict:
        """Pull the projects repo into the store now instead of waiting for the poll."""
        response = self._request("POST", "/v2/admin/projects/:reconcile")
        return response.json()

    # --- Meta ---

    def server_version(self) -> dict:
        """The deployed Operations Manager's name, version, commit and branch.

        Served outside the ``/api`` prefix, so it does not go through ``_request``'s
        base URL; it also needs no key.
        """
        response = httpx.get(f"{self.web_url}/version", timeout=15.0, follow_redirects=True)
        response.raise_for_status()
        return response.json()

    # --- Rollout ---

    def project_detail(self, project: str) -> dict:
        """A whole project in one answer: services, components, deployments, pending work."""
        response = self._request("GET", f"/v2/projects/{project}")
        return response.json()

    def project_services(self, project: str) -> dict:
        """Which platform services this project uses, and on which layer."""
        response = self._request("GET", f"/v2/projects/{project}/services")
        return response.json()

    def project_components(self, project: str) -> dict:
        """The component definitions of a project."""
        response = self._request("GET", f"/v2/projects/{project}/components")
        return response.json()

    def pending_rollout(self, project: str) -> dict:
        """How far the project file runs ahead of the cluster."""
        response = self._request("GET", f"/v2/projects/{project}/pending-rollout")
        return response.json()

    # --- V1 sync project operations ---

    # --- SSO-authenticated project operations ---
    #
    # These two are the exception to X-API-Key: you need a project name before you can
    # have its key, so they take `Authorization: Bearer <SSO access token>`. Both
    # responses carry API keys, which is why nothing here is ever logged.

    def list_projects_sso(self, token: str) -> dict:
        """List the projects the token's identity may see, with keys where it administers."""
        response = self._request("GET", "/v2/projects", headers=self._bearer(token))
        return response.json()

    def create_project_sso(self, token: str, payload: dict) -> dict:
        """Create a project. The response carries its API key, once.

        Deliberately not routed through the async poller: the key is in the 202 body, and
        polling the task would return the task's result instead, losing it. Waiting for
        the task is a separate step, see ``wait_for_project``.
        """
        response = self._request("POST", "/v2/projects", json=payload, headers=self._bearer(token))
        return response.json()

    def wait_for_project(self, token: str, poll_url: str) -> dict:
        """Wait until a newly created project exists, using the token that created it.

        The 202 comes back before the project is usable: its API key returns 401 for the
        first few seconds. Polling takes the bearer token rather than that key, because
        the key is not accepted until the project it belongs to exists. The API matches
        the token's identity against the task's ``created_by``.
        """
        return self._poll_task(poll_url, headers=self._bearer(token))

    @staticmethod
    def _bearer(token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

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

    def list_backup_runs(self, project: str, deployment: str) -> dict:
        response = self._request("GET", f"/v1/backup/runs/{project}/{deployment}")
        return response.json()

    def delete_snapshot(self, project: str, deployment: str, snapshot_id: str) -> dict:
        response = self._request("DELETE", f"/v1/backup/snapshot/{project}/{deployment}/{snapshot_id}")
        return response.json()

    # --- Restore endpoints ---
    #
    # The snapshot-listing and cluster-level restore endpoints authenticate the
    # API key against a project_name query parameter and use it to pin the only
    # namespace the caller may address. Requests without it are rejected with
    # 401. It is keyword-optional here purely to keep these signatures
    # backwards compatible; callers should always pass it.

    def list_snapshots(self, cluster: str, namespace: str, project_name: str | None = None) -> dict:
        params = {"project_name": project_name} if project_name else {}
        response = self._request("GET", f"/v1/restore/snapshots/{cluster}/{namespace}", params=params)
        return response.json()

    def list_pvc_snapshots(self, cluster: str, namespace: str, pvc_name: str, project_name: str | None = None) -> dict:
        """List available Kopia snapshots for a specific PVC."""
        params = {"project_name": project_name} if project_name else {}
        response = self._request("GET", f"/v1/restore/snapshots/{cluster}/{namespace}/{pvc_name}", params=params)
        return response.json()

    def restore_project(self, project: str, payload: dict) -> dict:
        """Restore a storage volume in a project from a snapshot."""
        response = self._request("POST", f"/v1/restore/project/{project}", json=payload)
        return response.json()

    def restore_deployment_resource(self, project: str, deployment: str, payload: dict) -> dict:
        """Restore a resource (PVC, database, or bucket) for a deployment with versioning."""
        response = self._request("POST", f"/v1/restore/project/{project}/deployment/{deployment}", json=payload)
        return response.json()

    def restore_backup_run(self, project: str, deployment: str, backup_run_id: str) -> dict:
        response = self._request("POST", f"/v1/restore/project/{project}/deployment/{deployment}/run/{backup_run_id}")
        return response.json()

    def restore_pvc(self, cluster: str, namespace: str, pvc_name: str, project_name: str | None = None) -> dict:
        params = {"project_name": project_name} if project_name else {}
        response = self._request("POST", f"/v1/restore/pvc/{cluster}/{namespace}/{pvc_name}", params=params)
        return response.json()

    def restore_database(
        self, cluster: str, namespace: str, reference: str, payload: dict, project_name: str | None = None
    ) -> dict:
        """Restore a database snapshot into a target database."""
        params = {"project_name": project_name} if project_name else {}
        response = self._request(
            "POST", f"/v1/restore/database/{cluster}/{namespace}/{reference}", params=params, json=payload
        )
        return response.json()

    def restore_bucket(
        self, cluster: str, namespace: str, reference: str, payload: dict, project_name: str | None = None
    ) -> dict:
        """Restore a bucket snapshot into a target bucket."""
        params = {"project_name": project_name} if project_name else {}
        response = self._request(
            "POST", f"/v1/restore/bucket/{cluster}/{namespace}/{reference}", params=params, json=payload
        )
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

    def resolve_backup_target(self, project: str, deployment: str) -> tuple[str, str]:
        """The cluster and namespace the backup and restore endpoints expect.

        Deliberately not from the deployment. ``GET /v2/.../deployments/{d}`` reports
        ``namespace: "<project>"`` while the real namespace is ``rig-<project>``, and the
        restore endpoints answer 403 "Namespace does not belong to the authenticated
        project" for the first form. The backup-runs endpoint is the only one that
        publishes both names in the form those endpoints accept, and it belongs to the
        same family, so that is where this asks.

        The cluster used to be guessed from the namespace's first dash-separated part,
        which turned ``c1-ij8`` into ``c1`` and got a 400. There is no need to guess: both
        this endpoint and the deployment carry the real name.
        """
        data = self.list_backup_runs(project, deployment)
        return data["cluster"], data["namespace"]

    def resolve_namespace(self, project: str, deployment: str) -> str:
        """Resolve a deployment name to its Kubernetes namespace."""
        return self.resolve_backup_target(project, deployment)[1]

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
            # What is waiting, when the API says. `urls` and `components` describe the
            # project file (what you asked for); `status` and the rest describe the
            # cluster. A component saved with rollout=false has a URL immediately while
            # nothing serves it yet, and this is the field that says the two have drifted.
            "pending_rollout": dep.get("pending_rollout"),
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
