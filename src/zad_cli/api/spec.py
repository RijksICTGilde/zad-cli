"""Read-only access to the vendored upstream OpenAPI spec.

The spec is the CLI's map of the API: which operations exist, which of them accept
the ``rollout`` query parameter, and what request body each one expects. Commands ask
this module instead of hardcoding endpoint knowledge, which is what keeps the service
layer in :mod:`zad_cli.commands.service` free of service names.

The file itself lives at ``api/upstream-openapi.json`` in the repo (that is the path the
api-sync workflow writes to) and is force-included into the wheel next to this module,
so both a checkout and an installed package find exactly one copy.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

# Installed layout first (wheel force-include), then the repo checkout.
_CANDIDATE_PATHS = (
    Path(__file__).resolve().parent / "upstream-openapi.json",
    Path(__file__).resolve().parents[3] / "api" / "upstream-openapi.json",
)


class SpecNotFoundError(RuntimeError):
    """Raised when the vendored spec is missing from every known location."""


def spec_path() -> Path:
    """Locate the vendored spec, preferring the installed copy."""
    for candidate in _CANDIDATE_PATHS:
        if candidate.exists():
            return candidate
    raise SpecNotFoundError(
        "Vendored OpenAPI spec not found. Looked in: " + ", ".join(str(p) for p in _CANDIDATE_PATHS)
    )


@lru_cache(maxsize=1)
def load_spec() -> dict[str, Any]:
    """Parse the vendored spec once per process."""
    return json.loads(spec_path().read_text())


def normalize_path(path: str) -> str:
    """Bring a client-relative path into the spec's namespace.

    The client's ``base_url`` already ends in ``/api``, so it issues ``/v2/projects/...``
    while the spec documents ``/api/v2/projects/...``. ``/version`` is served outside the
    API prefix and is documented as-is.
    """
    if not path.startswith("/"):
        path = "/" + path
    if path.startswith("/api/") or path == "/version":
        return path
    return "/api" + path


def _segments_match(template: str, concrete: str) -> bool:
    t_parts = template.strip("/").split("/")
    c_parts = concrete.strip("/").split("/")
    if len(t_parts) != len(c_parts):
        return False
    return all(t.startswith("{") and t.endswith("}") or t == c for t, c in zip(t_parts, c_parts, strict=True))


@lru_cache(maxsize=512)
def match_path(path: str) -> str | None:
    """Find the spec path template a concrete request path belongs to."""
    spec_paths = load_spec().get("paths", {})
    candidate = normalize_path(path.split("?", 1)[0])
    if candidate in spec_paths:
        return candidate
    for template in spec_paths:
        if "{" in template and _segments_match(template, candidate):
            return template
    return None


def operation(method: str, path: str) -> dict[str, Any] | None:
    """Look up one operation object, or None when the spec does not document it."""
    template = match_path(path)
    if template is None:
        return None
    return load_spec()["paths"][template].get(method.lower())


@lru_cache(maxsize=512)
def accepts_rollout(method: str, path: str, *, value: bool = False) -> bool:
    """True when this operation takes ``rollout`` as ``value``.

    Read from the spec rather than a hand-kept list: most mutating operations accept the
    parameter today and that count moves with the API.

    Five of them accept it only as ``true``: refreshing and cloning *are* the rollout, so
    deferring one is a contradiction and the API answers 422. The spec says so in the
    parameter description, so that is where it is read from; a list here would go stale the
    moment a sixth operation joins them.
    """
    op = operation(method, path)
    if not op:
        return False
    for parameter in op.get("parameters", []):
        if parameter.get("name") != "rollout" or parameter.get("in") != "query":
            continue
        true_only = "only as true" in (parameter.get("description") or "").lower()
        return not (value is False and true_only)
    return False


def _resolve(node: Any, schemas: dict[str, Any], seen: tuple[str, ...] = ()) -> Any:
    """Inline ``$ref``s so a schema can be printed or validated on its own.

    Recursive schemas are cut at the point of recursion with a note instead of looping.
    """
    if isinstance(node, list):
        return [_resolve(item, schemas, seen) for item in node]
    if not isinstance(node, dict):
        return node
    ref = node.get("$ref")
    if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
        name = ref.rsplit("/", 1)[-1]
        if name in seen:
            return {"description": f"(recursive reference to {name})"}
        target = schemas.get(name)
        if target is None:
            return node
        resolved = _resolve(target, schemas, (*seen, name))
        rest = {k: v for k, v in node.items() if k != "$ref"}
        return {**resolved, **rest} if rest else resolved
    return {k: _resolve(v, schemas, seen) for k, v in node.items()}


def request_schema(method: str, path: str, content_type: str = "application/json") -> dict[str, Any] | None:
    """Resolved JSON Schema for an operation's request body."""
    op = operation(method, path)
    if not op:
        return None
    body = op.get("requestBody", {}).get("content", {}).get(content_type, {}).get("schema")
    if not body:
        return None
    return _resolve(body, load_spec().get("components", {}).get("schemas", {}))


def resolve_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Inline every ``$ref`` in a schema fragment taken from the spec."""
    return _resolve(schema, load_spec().get("components", {}).get("schemas", {}))
