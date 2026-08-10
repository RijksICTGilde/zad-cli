"""The vendored OpenAPI spec as a lookup table: path matching, rollout, request schemas."""

from __future__ import annotations

import pytest

from zad_cli.api import spec


def test_the_spec_ships_with_the_package():
    assert spec.spec_path().exists()
    assert spec.load_spec()["paths"]


@pytest.mark.parametrize(
    "given,expected",
    [
        ("/v2/projects/x/pending-rollout", "/api/v2/projects/{project_name}/pending-rollout"),
        ("/api/v2/services", "/api/v2/services"),
        ("/version", "/version"),
        (
            "/v2/projects/x/services/postgresql-database/config/project",
            "/api/v2/projects/{project_name}/services/postgresql-database/config/project",
        ),
    ],
)
def test_a_concrete_path_matches_its_template(given: str, expected: str) -> None:
    """The client issues /v2/... because its base URL ends in /api; the spec says /api/v2/..."""
    assert spec.match_path(given) == expected


def test_an_unknown_path_matches_nothing():
    assert spec.match_path("/v2/does/not/exist") is None


def test_a_path_with_the_wrong_number_of_segments_does_not_match():
    assert spec.match_path("/v2/projects/x/pending-rollout/extra") is None


def test_rollout_is_read_from_the_spec_not_a_list():
    assert spec.accepts_rollout("PUT", "/v2/projects/x/services/publish-on-web/config/component/web")
    assert spec.accepts_rollout("POST", "/v2/projects/x/services/user-env-vars/values/component/web")


def test_read_only_endpoints_do_not_accept_rollout():
    assert not spec.accepts_rollout("GET", "/v2/projects/x/pending-rollout")
    assert not spec.accepts_rollout("GET", "/v2/services")


def test_an_undocumented_endpoint_does_not_accept_rollout():
    assert not spec.accepts_rollout("POST", "/v2/does/not/exist")


def test_request_schema_is_resolved_into_a_standalone_document():
    schema = spec.request_schema("PUT", "/api/v2/projects/{project_name}/services/postgresql-database/config/project")
    assert schema is not None
    # A $ref would make the schema useless to print or validate against on its own.
    assert "$ref" not in str(schema)
    assert "scope" in str(schema)


def test_request_schema_is_none_when_there_is_no_body():
    assert spec.request_schema("GET", "/api/v2/services") is None


def test_the_spec_still_documents_what_the_error_layer_depends_on():
    """CATEGORY_FAULT is keyed by this enum; a rename upstream must be loud."""
    assert "ErrorCategory" in spec.load_spec()["components"]["schemas"]


# --- Operations that cannot defer their rollout ---


def test_refresh_does_not_accept_a_deferred_rollout():
    """Refreshing *is* the rollout, so deferring one is a contradiction the API 422s on."""
    assert spec.accepts_rollout("POST", "/v2/projects/{p}/deployments/{d}/:refresh", value=False) is False
    assert spec.accepts_rollout("POST", "/v2/projects/{p}/:refresh", value=False) is False


def test_those_operations_still_accept_rollout_true():
    """Only false is refused; true is the normal case and must keep being sent."""
    assert spec.accepts_rollout("POST", "/v2/projects/{p}/:refresh", value=True) is True


def test_an_ordinary_mutation_still_defers():
    assert spec.accepts_rollout("POST", "/v2/projects/{p}/components", value=False) is True


def test_the_rule_is_read_from_the_spec_not_a_list():
    """A sixth operation joining them must need no code change here."""
    from zad_cli.api.spec import load_spec

    declared = set()
    for path, ops in load_spec()["paths"].items():
        for method, op in ops.items():
            for parameter in op.get("parameters", []):
                if (
                    parameter.get("name") == "rollout"
                    and "only as true" in (parameter.get("description") or "").lower()
                ):
                    declared.add((method.upper(), path))
    assert declared, "the spec no longer marks any operation as rollout-true-only"
