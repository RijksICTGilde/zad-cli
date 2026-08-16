"""Manifests, ``--set`` overrides and schema checks.

Three ways to build a request body, in one place so every mutating command offers the
same thing:

* ``-f manifest.yaml``: a whole body from a file (JSON is valid YAML), ``-`` for stdin.
* ``--set dotted.path=value``: repeatable, applied on top of the file. Helm's model:
  the flags win, because they are the more specific thing you just typed.
* ``@file`` / ``file://`` as a *value*: read one field from a file instead of the body.

The validation here is deliberately local: it catches the mistakes a schema can catch
(unknown field, wrong type, missing required, value outside an enum) and names the field
path, so a typo costs a millisecond instead of a round trip. The API stays the authority.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

import typer
import yaml

# 64 KB is the attachment ceiling upstream; a manifest that big is a mistake either way.
MAX_FILE_BYTES = 1024 * 1024

_SEGMENT_RE = re.compile(r"([^\[\]]+)|\[(\d+)\]")


class ManifestError(typer.BadParameter):
    """A manifest, --set expression or payload that cannot be used as given."""


def read_file_value(spec: str) -> str:
    """Read a value from disk for ``@path`` / ``file://path``; ``-`` reads stdin."""
    raw = spec[1:] if spec.startswith("@") else spec[len("file://") :]
    if raw == "-":
        return sys.stdin.read()
    path = Path(raw).expanduser()
    if not path.exists():
        raise ManifestError(f"File not found: {path}")
    size = path.stat().st_size
    if size > MAX_FILE_BYTES:
        raise ManifestError(f"File {path} is {size} bytes, over the {MAX_FILE_BYTES} byte limit.")
    return path.read_text()


def resolve_value_reference(value: str) -> str:
    """Expand ``@file`` / ``file://`` references; leave anything else alone."""
    if value.startswith("@") or value.startswith("file://"):
        return read_file_value(value)
    return value


def coerce_scalar(raw: str) -> Any:
    """Turn a command-line string into the JSON value it obviously means.

    ``true``/``false``/``null``, integers and floats become their typed selves; anything
    quoted stays a string, so ``--set version="1.0"`` is not silently a float.

    ``none`` is deliberately *not* null. YAML does not read it as one either, so treating
    it that way was our own invention, and an expensive one: "none" is an ordinary enum
    value ("no scheme", "no probe"), and turning it into null does not send "none", it
    sends nothing at all -- which the API reads as "use the default", the opposite of what
    was typed. ``null`` and ``~`` still mean null, because those say so.
    """
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
        return raw[1:-1]
    lowered = raw.lower()
    if lowered in ("true", "yes"):
        return True
    if lowered in ("false", "no"):
        return False
    if lowered in ("null", "~"):
        return None
    if raw[:1] in "{[" and raw.rstrip()[-1:] in "}]":
        # A whole object or list in one flag: `--set active={"key": ""}`. It is the first
        # thing people try when a field is not a scalar, and it used to land as the literal
        # string `{"key": ""}` -- which then failed validation with "does not match any of
        # the accepted shapes", pointing at the field rather than at the quoting. YAML
        # flow style is a superset of JSON, so both spellings parse.
        try:
            import yaml

            parsed = yaml.safe_load(raw)
        except yaml.YAMLError as e:
            raise ManifestError(f"--set value looks like an object or a list but does not parse: {raw}") from e
        if isinstance(parsed, dict | list):
            return parsed
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        pass
    return raw


def _split_path(path: str) -> list[str | int]:
    """``a.b[0].c`` and ``a.b.0.c`` both address the same place."""
    parts: list[str | int] = []
    for segment in path.split("."):
        if not segment:
            raise ManifestError(f"Empty path segment in '{path}'.")
        for name, index in _SEGMENT_RE.findall(segment):
            if index:
                parts.append(int(index))
            elif name.isdigit():
                parts.append(int(name))
            else:
                parts.append(name)
    return parts


def _assign(container: Any, path: list[str | int], value: Any) -> Any:
    """Set ``value`` at ``path``, creating dicts and lists on the way."""
    key = path[0]
    if isinstance(key, int):
        if not isinstance(container, list):
            container = []
        while len(container) <= key:
            container.append(None)
        if len(path) == 1:
            container[key] = value
        else:
            container[key] = _assign(container[key], path[1:], value)
        return container
    if not isinstance(container, dict):
        container = {}
    if len(path) == 1:
        container[key] = value
    else:
        container[key] = _assign(container.get(key), path[1:], value)
    return container


def apply_sets(base: Any, expressions: list[str]) -> Any:
    """Apply ``dotted.path=value`` expressions on top of a body."""
    result = base
    for expr in expressions:
        if "=" not in expr:
            raise ManifestError(f"--set expects 'path=value', got '{expr}'.")
        path, raw = expr.split("=", 1)
        value = coerce_scalar(resolve_value_reference(raw)) if raw.startswith(("@", "file://")) else coerce_scalar(raw)
        result = _assign(result, _split_path(path.strip()), value)
    return result


def load_payload_file(path: str) -> Any:
    """Load a YAML or JSON manifest; ``-`` reads stdin."""
    if path == "-":
        text = sys.stdin.read()
    else:
        file_path = Path(path).expanduser()
        if not file_path.exists():
            raise ManifestError(f"File not found: {file_path}")
        size = file_path.stat().st_size
        if size > MAX_FILE_BYTES:
            raise ManifestError(f"File {file_path} is {size} bytes, over the {MAX_FILE_BYTES} byte limit.")
        text = file_path.read_text()
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise ManifestError(f"Could not parse {path} as YAML/JSON: {e}") from e


# --- Skeletons ---

_TYPE_EXAMPLE: dict[str, Any] = {
    "string": "",
    "integer": 0,
    "number": 0,
    "boolean": False,
    "array": [],
    "object": {},
}


def render_skeleton(schema: dict[str, Any], _depth: int = 0) -> Any:
    """Build an example body from a JSON Schema.

    Uses the schema's own ``examples``/``default`` where it has them, so the skeleton is
    a starting point rather than a shape.
    """
    if _depth > 6 or not isinstance(schema, dict):
        return None
    if "default" in schema:
        return schema["default"]
    examples = schema.get("examples")
    if isinstance(examples, list) and examples:
        return examples[0]
    if "enum" in schema and schema["enum"]:
        return schema["enum"][0]
    for key in ("oneOf", "anyOf", "allOf"):
        options = schema.get(key)
        if isinstance(options, list) and options:
            non_null = [o for o in options if isinstance(o, dict) and o.get("type") != "null"] or options
            return render_skeleton(non_null[0], _depth + 1)

    schema_type = schema.get("type")
    if schema_type == "object" or "properties" in schema:
        required = set(schema.get("required", []))
        out: dict[str, Any] = {}
        for name, sub in (schema.get("properties") or {}).items():
            if required and name not in required and _depth > 0:
                continue
            out[name] = render_skeleton(sub, _depth + 1)
        return out
    if schema_type == "array":
        item = schema.get("items")
        return [render_skeleton(item, _depth + 1)] if isinstance(item, dict) else []
    if isinstance(schema_type, list):
        schema_type = next((t for t in schema_type if t != "null"), "string")
    return _TYPE_EXAMPLE.get(schema_type)


# --- Validation ---

_JSON_TYPES: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
    "array": (list,),
    "object": (dict,),
    "null": (type(None),),
}


def _type_ok(value: Any, expected: str) -> bool:
    if expected == "integer" and isinstance(value, bool):
        return False
    if expected == "number" and isinstance(value, bool):
        return False
    return isinstance(value, _JSON_TYPES.get(str(expected), (object,)))


def _union_error(value: Any, schema: dict[str, Any], branches: list[dict[str, Any]], where: str) -> str:
    """Explain a failed union in terms of its discriminator, when it has one.

    "does not match any of the accepted shapes" is true but useless; a discriminated
    union fails because one field picks the wrong branch, and naming that field with its
    valid values is the difference between a fix and a guess.
    """
    field = (schema.get("discriminator") or {}).get("propertyName")
    if not field:
        # No explicit discriminator: look for a property every branch pins with `const`.
        pinned = [
            name
            for name in (branches[0].get("properties") or {})
            if all("const" in ((b.get("properties") or {}).get(name) or {}) for b in branches)
        ]
        field = pinned[0] if pinned else None

    if field:
        allowed = [
            (b.get("properties") or {}).get(field, {}).get("const")
            for b in branches
            if "const" in ((b.get("properties") or {}).get(field) or {})
        ]
        allowed = [a for a in allowed if a is not None]
        if allowed:
            given = value.get(field, "(absent)") if isinstance(value, dict) else value
            return f"{where}: '{field}' is '{given}', which is not one of {', '.join(str(a) for a in allowed)}."

    return f"{where}: does not match any of the accepted shapes for this field."


def _errors(value: Any, schema: dict[str, Any], path: str) -> list[str]:
    """Collect human-readable problems, each naming the field path it is about."""
    if not isinstance(schema, dict) or not schema:
        return []
    where = path or "(root)"

    for key in ("oneOf", "anyOf"):
        options = schema.get(key)
        if isinstance(options, list) and options:
            branches = [option for option in options if isinstance(option, dict)]
            if any(not _errors(value, option, path) for option in branches):
                break
            return [_union_error(value, schema, branches, where)]

    for option in schema.get("allOf", []) or []:
        found = _errors(value, option, path)
        if found:
            return found

    expected = schema.get("type")
    types = [expected] if isinstance(expected, str) else list(expected or [])
    if types and not any(_type_ok(value, t) for t in types):
        got = type(value).__name__
        return [f"{where}: expected {' or '.join(types)}, got {got}."]

    enum = schema.get("enum")
    if enum is not None and value not in enum:
        return [f"{where}: '{value}' is not one of {', '.join(str(e) for e in enum)}."]

    # A discriminated union spells its discriminator as `const`, not `enum`; without this
    # every branch of the union accepts every value and the union check never fires.
    if "const" in schema and value != schema["const"]:
        return [f"{where}: '{value}' is not '{schema['const']}'."]

    if isinstance(value, str):
        max_length = schema.get("maxLength")
        if isinstance(max_length, int) and len(value) > max_length:
            return [f"{where}: at most {max_length} characters, got {len(value)}."]

    problems: list[str] = []
    if isinstance(value, dict):
        properties = schema.get("properties") or {}
        for name in schema.get("required", []) or []:
            if name not in value:
                problems.append(f"{path + '.' if path else ''}{name}: required field is missing.")
        if schema.get("additionalProperties") is False and properties:
            for name in value:
                if name not in properties:
                    problems.append(f"{where}: unknown field '{name}'. Known fields: {', '.join(sorted(properties))}.")
        for name, sub in properties.items():
            if name in value:
                problems.extend(_errors(value[name], sub, f"{path}.{name}" if path else name))

    if isinstance(value, list):
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                problems.extend(_errors(item, item_schema, f"{path}[{index}]"))

    return problems


def validate_against_schema(payload: Any, schema: dict[str, Any], *, what: str) -> None:
    """Fail before sending when the body clearly cannot be right."""
    problems = _errors(payload, schema, "")
    if not problems:
        return
    lines = "\n".join(f"  - {p}" for p in problems[:10])
    more = f"\n  ... and {len(problems) - 10} more" if len(problems) > 10 else ""
    raise ManifestError(
        f"This body is not valid for {what}:\n{lines}{more}\n"
        "Run the same command with --generate-skeleton for an example body."
    )


def to_json_text(data: Any) -> str:
    """Compact JSON, for embedding a payload in a message."""
    return json.dumps(data, ensure_ascii=False, default=str)
