"""Manifests, --set overrides, skeletons and the local schema check."""

from __future__ import annotations

from pathlib import Path

import pytest

from zad_cli.manifest import (
    ManifestError,
    apply_sets,
    coerce_scalar,
    load_payload_file,
    render_skeleton,
    resolve_value_reference,
    validate_against_schema,
)

# --- --set ---


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("true", True),
        ("false", False),
        ("yes", True),
        ("null", None),
        ("42", 42),
        ("1.5", 1.5),
        ("shared", "shared"),
        ('"1.0"', "1.0"),  # quoted stays a string, so a version is not a float
        ("'true'", "true"),
    ],
)
def test_scalar_coercion(raw: str, expected: object) -> None:
    assert coerce_scalar(raw) == expected


def test_set_builds_nested_objects():
    assert apply_sets({}, ["a.b.c=1"]) == {"a": {"b": {"c": 1}}}


def test_set_supports_list_indices_in_both_spellings():
    assert apply_sets({}, ["s[0].postfix=x"]) == {"s": [{"postfix": "x"}]}
    assert apply_sets({}, ["s.0.postfix=x"]) == {"s": [{"postfix": "x"}]}


def test_set_fills_gaps_in_a_list():
    assert apply_sets({}, ["s[1].k=v"]) == {"s": [None, {"k": "v"}]}


def test_later_set_wins():
    assert apply_sets({}, ["scope=shared", "scope=project"]) == {"scope": "project"}


def test_set_overrides_the_file_body():
    """Helm's model: the flag you just typed beats the file."""
    assert apply_sets({"scope": "shared", "storage": "1Gi"}, ["scope=project"]) == {
        "scope": "project",
        "storage": "1Gi",
    }


def test_set_without_an_equals_is_rejected():
    with pytest.raises(ManifestError):
        apply_sets({}, ["scope"])


def test_set_value_can_come_from_a_file(tmp_path: Path):
    secret = tmp_path / "token.txt"
    secret.write_text("s3cr3t")
    assert apply_sets({}, [f"password=@{secret}"]) == {"password": "s3cr3t"}


def test_value_reference_leaves_plain_values_alone():
    assert resolve_value_reference("plain") == "plain"


def test_value_reference_reports_a_missing_file():
    with pytest.raises(ManifestError):
        resolve_value_reference("@/nope/not/here.txt")


# --- Manifest files ---


def test_yaml_manifest(tmp_path: Path):
    path = tmp_path / "config.yaml"
    path.write_text("scope: project\nstorage: 256Mi\n")
    assert load_payload_file(str(path)) == {"scope": "project", "storage": "256Mi"}


def test_json_is_a_yaml_subset(tmp_path: Path):
    path = tmp_path / "config.json"
    path.write_text('{"scope": "project"}')
    assert load_payload_file(str(path)) == {"scope": "project"}


def test_unparseable_manifest_names_the_file(tmp_path: Path):
    path = tmp_path / "broken.yaml"
    path.write_text("a: [1, 2\n")
    with pytest.raises(ManifestError) as excinfo:
        load_payload_file(str(path))
    assert "broken.yaml" in str(excinfo.value)


def test_missing_manifest_is_rejected():
    with pytest.raises(ManifestError):
        load_payload_file("/nope/not/here.yaml")


# --- Skeletons ---


def test_skeleton_uses_the_schemas_own_example():
    schema = {"type": "object", "properties": {"postfix": {"type": "string", "examples": ["reporting"]}}}
    assert render_skeleton(schema) == {"postfix": "reporting"}


def test_skeleton_uses_defaults_and_enums():
    schema = {
        "type": "object",
        "properties": {
            "scope": {"type": "string", "enum": ["shared", "project"]},
            "instances": {"type": "integer", "default": 1},
        },
    }
    assert render_skeleton(schema) == {"scope": "shared", "instances": 1}


def test_skeleton_picks_a_branch_of_a_union():
    schema = {"oneOf": [{"type": "object", "properties": {"a": {"type": "string"}}}, {"type": "null"}]}
    assert render_skeleton(schema) == {"a": ""}


def test_skeleton_survives_a_recursive_schema():
    """The spec resolver marks recursion; the skeleton must not loop on it."""
    schema = {"type": "object", "properties": {"child": {"description": "(recursive reference to Node)"}}}
    assert render_skeleton(schema) == {"child": None}


# --- Validation ---

_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["scope"],
    "properties": {
        "scope": {"type": "string", "enum": ["shared", "project"]},
        "instances": {"type": "integer"},
        "name": {"type": "string", "maxLength": 4},
        "schemas": {
            "type": "array",
            "items": {"type": "object", "required": ["postfix"], "properties": {"postfix": {"type": "string"}}},
        },
    },
}


def test_a_valid_body_passes():
    validate_against_schema({"scope": "project", "instances": 2}, _SCHEMA, what="test")


def test_missing_required_field_names_it():
    with pytest.raises(ManifestError) as excinfo:
        validate_against_schema({"instances": 1}, _SCHEMA, what="test")
    assert "scope" in str(excinfo.value)


def test_wrong_type_names_the_field_path():
    with pytest.raises(ManifestError) as excinfo:
        validate_against_schema({"scope": "project", "instances": "two"}, _SCHEMA, what="test")
    assert "instances" in str(excinfo.value)


def test_value_outside_the_enum_lists_the_options():
    with pytest.raises(ManifestError) as excinfo:
        validate_against_schema({"scope": "namespace"}, _SCHEMA, what="test")
    message = str(excinfo.value)
    assert "shared" in message and "project" in message


def test_unknown_field_is_caught_when_the_schema_is_closed():
    with pytest.raises(ManifestError) as excinfo:
        validate_against_schema({"scope": "project", "sccope": 1}, _SCHEMA, what="test")
    assert "sccope" in str(excinfo.value)


def test_error_inside_a_list_carries_the_index():
    with pytest.raises(ManifestError) as excinfo:
        validate_against_schema({"scope": "project", "schemas": [{"postfix": "a"}, {}]}, _SCHEMA, what="test")
    assert "schemas[1]" in str(excinfo.value)


def test_maxlength_is_enforced():
    with pytest.raises(ManifestError) as excinfo:
        validate_against_schema({"scope": "project", "name": "toolong"}, _SCHEMA, what="test")
    assert "4 characters" in str(excinfo.value)


def test_booleans_are_not_integers():
    """JSON says true is not 1; a schema that wants an integer must say so."""
    with pytest.raises(ManifestError):
        validate_against_schema({"scope": "project", "instances": True}, _SCHEMA, what="test")


def test_a_union_accepts_either_branch():
    schema = {"oneOf": [{"type": "string"}, {"type": "integer"}]}
    validate_against_schema("x", schema, what="test")
    validate_against_schema(3, schema, what="test")
    with pytest.raises(ManifestError):
        validate_against_schema([], schema, what="test")


def test_an_empty_schema_accepts_anything():
    validate_against_schema({"whatever": True}, {}, what="test")
