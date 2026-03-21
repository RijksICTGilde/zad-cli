"""Tests for API models and validation."""

import pytest
from pydantic import ValidationError

from zad_cli.api.models import Component, UpsertDeploymentRequest


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
