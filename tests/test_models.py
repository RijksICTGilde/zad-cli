"""Tests for API models and validation."""

import pytest
from pydantic import ValidationError

from zad_cli.api.models import (
    Component,
    ComponentFailureInfo,
    DeploymentDetail,
    DeploymentStatus,
    ErrorCategory,
    StatusError,
    TaskStatus,
    UpsertDeploymentRequest,
)


def test_valid_component():
    c = Component(name="web", image="ghcr.io/org/app:latest")
    assert c.name == "web"
    assert c.image == "ghcr.io/org/app:latest"


def test_invalid_component_name():
    with pytest.raises(ValidationError):
        Component(name="bad name!", image="ghcr.io/org/app:latest")


def test_component_name_with_dots_and_dashes():
    c = Component(name="my-app.v2", image="ghcr.io/org/app:latest")
    assert c.name == "my-app.v2"


def test_upsert_deployment_request():
    req = UpsertDeploymentRequest(
        deployment_name="pr-42",
        components=[Component(name="web", image="ghcr.io/org/app:pr-42")],
    )
    payload = req.to_api_payload()
    assert payload["deploymentName"] == "pr-42"
    assert len(payload["components"]) == 1
    assert payload["components"][0]["reference"] == "web"
    assert "cloneFrom" not in payload


def test_upsert_deployment_with_clone():
    req = UpsertDeploymentRequest(
        deployment_name="pr-42",
        components=[Component(name="web", image="ghcr.io/org/app:pr-42")],
        clone_from="production",
        force_clone=True,
    )
    payload = req.to_api_payload()
    assert payload["cloneFrom"] == "production"
    assert payload["forceClone"] is True


def test_upsert_deployment_with_domain():
    req = UpsertDeploymentRequest(
        deployment_name="pr-42",
        components=[Component(name="web", image="ghcr.io/org/app:pr-42")],
        domain_format="{component}-{deployment}",
        subdomain="my-app",
        base_domain="example.com",
    )
    payload = req.to_api_payload()
    assert payload["domain_format"] == "{component}-{deployment}"
    assert payload["subdomain"] == "my-app"
    assert payload["base_domain"] == "example.com"


def test_invalid_deployment_name():
    with pytest.raises(ValidationError):
        UpsertDeploymentRequest(
            deployment_name="bad name!",
            components=[Component(name="web", image="test")],
        )


def test_status_error_coerces_unknown_category():
    """An ErrorCategory value not yet in our enum degrades to UNKNOWN, not a validation error."""
    err = StatusError.model_validate({"resource": "Pod/foo", "message": "boom", "category": "ResourceQuotaExceeded"})
    assert err.category == ErrorCategory.UNKNOWN


def test_status_error_keeps_known_category():
    err = StatusError.model_validate({"resource": "Pod/foo", "message": "boom", "category": "ImagePull"})
    assert err.category == ErrorCategory.IMAGE_PULL


def test_deployment_detail_coerces_unknown_status():
    """An unknown DeploymentStatus value degrades to UNKNOWN, keeping list_deployments resilient."""
    detail = DeploymentDetail.model_validate(
        {
            "name": "staging",
            "project": "p",
            "cluster": "c",
            "namespace": "ns",
            "status": "Reconciling",
        }
    )
    assert detail.status == DeploymentStatus.UNKNOWN


def test_deployment_detail_carries_deviations():
    """A deviation explains an OutOfSync/Progressing status without being an application
    problem (that's `errors`); dropping it silently was the fate of `pending_rollout` and
    `approvals` before it."""
    detail = DeploymentDetail.model_validate(
        {
            "name": "staging",
            "project": "p",
            "cluster": "c",
            "namespace": "ns",
            "status": "OutOfSync",
            "deviations": [{"resource": "Job/staging-web-migrate-171", "kind": "Job", "reason": "Deletion pending."}],
        }
    )
    assert detail.deviations[0].kind == "Job"
    assert detail.deviations[0].reason == "Deletion pending."


def test_component_failure_info_carries_title_and_suggestion():
    """`title`/`suggestion` are the translated form of the raw `message`."""
    failure = ComponentFailureInfo.model_validate(
        {
            "component": "web",
            "failure_type": "ImagePull",
            "message": "raw kubelet text",
            "title": "Image could not be pulled",
            "suggestion": "Check the image tag and registry credentials.",
            "container": "web",
            "image": "ghcr.io/org/web:bad",
            "severity": "error",
        }
    )
    assert failure.title == "Image could not be pulled"
    assert failure.suggestion == "Check the image tag and registry credentials."
    assert failure.container == "web"
    assert failure.image == "ghcr.io/org/web:bad"
    assert failure.severity == "error"


def test_task_status_carries_superseded_by():
    status = TaskStatus.model_validate(
        {
            "status": "completed",
            "superseded_by": {"task_id": "t-2", "task_type": "refresh_project", "project_name": "p"},
        }
    )
    assert status.superseded_by["task_id"] == "t-2"
