"""Spec-conformance tests: keep the CLI's error vocabulary in lockstep with the API.

These assert the CLI's hand-written enums/mappings match the vendored OpenAPI spec
(api/upstream-openapi.json). When the daily api-sync workflow refreshes the spec and
the upstream adds/changes an ErrorCategory, these tests fail loudly with a clear
instruction, turning a silent drift into an actionable PR. This is the *strict* half
of the coupling; runtime parsing (category_of / _coerce_unknown_*) is the *loose* half.

The vendored spec is part of the repo, so a missing file is a hard failure, not a
skip: skipping would let the whole conformance check pass silently if the file is ever
moved or renamed.
"""

import json
from pathlib import Path

import pytest

from zad_cli.api.errors import CATEGORY_FAULT, CATEGORY_HINT
from zad_cli.api.models import ErrorCategory

_SPEC_PATH = Path(__file__).resolve().parent.parent / "api" / "upstream-openapi.json"


def _spec_schemas() -> dict:
    if not _SPEC_PATH.exists():
        pytest.fail(
            f"vendored spec not found at {_SPEC_PATH}. It is part of the repo and these "
            "conformance tests depend on it; if it moved, update _SPEC_PATH instead of skipping."
        )
    return json.loads(_SPEC_PATH.read_text())["components"]["schemas"]


def test_error_category_enum_matches_spec() -> None:
    """Our ErrorCategory must equal the spec's enum, value-for-value."""
    spec_values = set(_spec_schemas()["ErrorCategory"]["enum"])
    cli_values = {c.value for c in ErrorCategory}
    assert cli_values == spec_values, (
        "ErrorCategory drifted from the API spec. Update zad_cli.api.models.ErrorCategory "
        f"and the CATEGORY_FAULT/CATEGORY_HINT maps. spec-only={spec_values - cli_values}, "
        f"cli-only={cli_values - spec_values}"
    )


def test_every_category_has_a_fault_and_hint() -> None:
    """A new category must not silently fall through the diagnosis layer."""
    for cat in ErrorCategory:
        assert cat in CATEGORY_FAULT, f"{cat} missing from CATEGORY_FAULT"
        assert cat in CATEGORY_HINT, f"{cat} missing from CATEGORY_HINT"


@pytest.mark.parametrize(
    "schema_name,model_path",
    [
        ("ComponentFailureInfo", "zad_cli.api.models:ComponentFailureInfo"),
        ("SubtaskStatus", "zad_cli.api.models:SubtaskStatus"),
    ],
)
def test_models_cover_spec_required_fields(schema_name: str, model_path: str) -> None:
    """Our pydantic models must declare every field the spec marks required."""
    import importlib

    module_name, cls_name = model_path.split(":")
    model = getattr(importlib.import_module(module_name), cls_name)
    spec_required = set(_spec_schemas()[schema_name].get("required", []))
    model_fields = set(model.model_fields)
    missing = spec_required - model_fields
    assert not missing, f"{cls_name} is missing spec-required fields: {missing}"
