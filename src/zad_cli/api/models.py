"""Pydantic models for API requests and responses."""

from __future__ import annotations

import re
from enum import StrEnum

from pydantic import BaseModel, field_validator

# Validation pattern from zad-actions
SAFE_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9._-]+$")


def _validate_safe_name(v: str, field_name: str) -> str:
    if not SAFE_NAME_PATTERN.match(v):
        msg = f"{field_name} must match ^[a-zA-Z0-9._-]+$, got: {v}"
        raise ValueError(msg)
    return v


class Component(BaseModel):
    """A deployment component (container reference + image)."""

    name: str
    image: str

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        return _validate_safe_name(v, "component name")


class UpsertDeploymentRequest(BaseModel):
    """Request body for upsert-deployment."""

    deployment_name: str
    components: list[Component]
    clone_from: str | None = None
    force_clone: bool = False
    domain_format: str | None = None
    subdomain: str | None = None
    base_domain: str | None = None

    @field_validator("deployment_name")
    @classmethod
    def validate_deployment_name(cls, v: str) -> str:
        return _validate_safe_name(v, "deployment_name")

    @field_validator("clone_from")
    @classmethod
    def validate_clone_from(cls, v: str | None) -> str | None:
        if v is not None:
            _validate_safe_name(v, "clone_from")
        return v

    @field_validator("subdomain")
    @classmethod
    def validate_subdomain(cls, v: str | None) -> str | None:
        if v is not None:
            _validate_safe_name(v, "subdomain")
        return v

    @field_validator("base_domain")
    @classmethod
    def validate_base_domain(cls, v: str | None) -> str | None:
        if v is not None:
            _validate_safe_name(v, "base_domain")
        return v

    def to_api_payload(self) -> dict:
        """Convert to API request payload."""
        payload: dict = {
            "deploymentName": self.deployment_name,
            "components": [{"reference": c.name, "image": c.image} for c in self.components],
        }
        if self.clone_from:
            payload["cloneFrom"] = self.clone_from
            payload["forceClone"] = self.force_clone
        if self.domain_format:
            payload["domain_format"] = self.domain_format
        if self.subdomain:
            payload["subdomain"] = self.subdomain
        if self.base_domain:
            payload["base_domain"] = self.base_domain
        return payload


class CloneDatabaseRequest(BaseModel):
    """Request body for cloning a database from an external source."""

    host: str
    port: int = 5432
    dbname: str
    schema_name: str = "public"
    username: str
    password: str
    tunnel: str | None = None
    force: bool = False

    def to_api_payload(self) -> dict:
        """Convert to API request payload."""
        payload: dict = {
            "sourceHost": self.host,
            "sourcePort": self.port,
            "sourceDatabase": self.dbname,
            "sourceSchema": self.schema_name,
            "sourceUsername": self.username,
            "sourcePassword": self.password,
            "forceClone": self.force,
        }
        if self.tunnel:
            payload["tunnel"] = self.tunnel
        return payload


class CloneBucketRequest(BaseModel):
    """Request body for cloning a bucket from an external source."""

    host: str
    port: int = 9000
    bucket_name: str
    access_key: str
    secret_key: str
    secure: bool = True
    tunnel: str | None = None
    force: bool = False

    def to_api_payload(self) -> dict:
        """Convert to API request payload."""
        payload: dict = {
            "sourceHost": self.host,
            "sourcePort": self.port,
            "sourceBucket": self.bucket_name,
            "sourceAccessKey": self.access_key,
            "sourceSecretKey": self.secret_key,
            "sourceSecure": self.secure,
            "forceClone": self.force,
        }
        if self.tunnel:
            payload["tunnel"] = self.tunnel
        return payload


class TaskResponse(BaseModel):
    """Response from an async API call."""

    task_id: str
    poll_url: str
    status: str = "pending"


class TaskStatus(BaseModel):
    """Status of a polled task."""

    status: str
    current_step: str | None = None
    progress_percent: int | None = None
    result: dict | None = None
    error_message: str | None = None


class DeploymentStatus(StrEnum):
    """Overall deployment state from GET /v2/.../deployments."""

    HEALTHY = "Healthy"
    DEGRADED = "Degraded"
    PROGRESSING = "Progressing"
    OUT_OF_SYNC = "OutOfSync"
    SUSPENDED = "Suspended"
    MISSING = "Missing"
    PENDING = "Pending"
    UNAVAILABLE = "Unavailable"
    UNKNOWN = "Unknown"


class ErrorCategory(StrEnum):
    """Programmatic category for a cluster error entry."""

    IMAGE_PULL = "ImagePull"
    CRASH_LOOP = "CrashLoop"
    OUT_OF_MEMORY = "OutOfMemory"
    HEALTH_CHECK = "HealthCheck"
    SYNC_FAILED = "SyncFailed"
    COMPARISON_ERROR = "ComparisonError"
    UNKNOWN = "Unknown"


def _coerce_unknown_category(v: object) -> object:
    """Map an unknown ErrorCategory string to UNKNOWN so additive upstream enum changes don't break clients."""
    if isinstance(v, str) and v not in {e.value for e in ErrorCategory}:
        return ErrorCategory.UNKNOWN
    return v


def _coerce_unknown_status(v: object) -> object:
    """Same pattern for DeploymentStatus: unknown values degrade to UNKNOWN rather than rejecting the whole payload."""
    if isinstance(v, str) and v not in {e.value for e in DeploymentStatus}:
        return DeploymentStatus.UNKNOWN
    return v


class StatusError(BaseModel):
    """A single cluster-side error or warning surfaced on a deployment."""

    resource: str
    message: str
    category: ErrorCategory
    explanation: str | None = None
    timestamp: str | None = None

    @field_validator("category", mode="before")
    @classmethod
    def _coerce_category(cls, v: object) -> object:
        return _coerce_unknown_category(v)


class DeploymentComponentDetail(BaseModel):
    """Component within a deployment as returned by the v2 read endpoints."""

    reference: str
    image: str


class DeploymentDetail(BaseModel):
    """Full deployment state from GET /v2/projects/{p}/deployments/{d}."""

    name: str
    project: str
    cluster: str
    namespace: str
    subdomain: str | None = None
    components: list[DeploymentComponentDetail] = []
    urls: dict[str, str] = {}
    status: DeploymentStatus
    sync_revision: str | None = None
    last_synced_at: str | None = None
    errors: list[StatusError] = []

    @field_validator("status", mode="before")
    @classmethod
    def _coerce_status(cls, v: object) -> object:
        return _coerce_unknown_status(v)


class DeploymentListResponse(BaseModel):
    """Response from GET /v2/projects/{p}/deployments."""

    project: str
    cluster: str
    deployments: list[DeploymentDetail] = []
