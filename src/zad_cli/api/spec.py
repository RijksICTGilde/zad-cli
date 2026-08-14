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

import hashlib
import json
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

# Installed layout first (wheel force-include), then the repo checkout.
_CANDIDATE_PATHS = (
    Path(__file__).resolve().parent / "upstream-openapi.json",
    Path(__file__).resolve().parents[3] / "api" / "upstream-openapi.json",
)

# The spec is served from the host root, next to the API rather than under it, and needs no
# credentials -- the same as the service registry.
#
# An hour, not the catalog's day. A default changed under us on the afternoon this was
# written -- `wake-mode` went from `auto` to `manual` upstream -- and `--help` kept saying
# the old one. Staleness you cannot see is worse than a fetch you do not notice, and one
# request per hour per environment is not a cost anybody will measure.
#
# Keying on a version rather than on time would be better still, and is not possible yet:
# `info.version` has read `0.1.0` through every change so far, and the spec is served
# without an ETag or Last-Modified. Both are upstream asks.
LIVE_TTL_SECONDS = 60 * 60
CACHE_DIR = Path.home() / ".cache" / "zad"


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


def live_url(api_url: str) -> str:
    """Where this API publishes its own spec: the host root, not under ``/api``."""
    base = api_url.rstrip("/")
    if base.endswith("/api"):
        base = base[: -len("/api")]
    return f"{base}/openapi.json"


def live_cache_path(api_url: str) -> Path:
    """Cache file for one API URL: two environments never share a spec."""
    digest = hashlib.sha256(api_url.rstrip("/").encode()).hexdigest()[:12]
    return CACHE_DIR / f"openapi-{digest}.json"


@lru_cache(maxsize=8)
def load_live_spec(
    api_url: str, *, refresh: bool = False, ttl: int = LIVE_TTL_SECONDS, timeout: float = 15.0
) -> dict[str, Any] | None:
    """This API's own spec: cache, then the network, then nothing.

    The vendored copy is a snapshot of the day it was fetched, and what it is missing is
    exactly what a reader wants: the platform added `x-choices` to a dozen fields -- the
    values it will actually accept, with a label per value -- and a CLI that ships a spec
    from last month cannot show them. So the spec is read the way the service catalog
    already is: live where possible, cached for a day, and the bundled copy when the
    network says no.

    ``None`` rather than an exception on every failure: this feeds `describe`, which is the
    first command anyone runs and has to keep working on a train. The caller falls back.
    """
    from zad_cli.api import registry

    if registry.offline():
        return None

    path = live_cache_path(api_url)
    if not refresh:
        try:
            cached = json.loads(path.read_text())
            if time.time() - float(cached["fetched_at"]) <= ttl:
                return cached["payload"]
        except (OSError, ValueError, KeyError):
            pass

    import httpx

    try:
        response = httpx.get(live_url(api_url), timeout=timeout, follow_redirects=True)
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError):
        return None
    if not isinstance(payload, dict) or "paths" not in payload:
        return None

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"fetched_at": time.time(), "payload": payload}))
    except OSError:
        # A cache we cannot write is not a reason to lose the answer we just fetched.
        pass
    return payload


def active_spec(api_url: str | None = None, *, refresh: bool = False, timeout: float = 15.0) -> dict[str, Any]:
    """The spec to read: this API's own where it can be reached, else the vendored copy.

    ``timeout`` is how long a *first* fetch may take; once cached, a day of reads costs
    nothing. Help screens pass a short one -- `--help` that waits on a network is `--help`
    that hangs -- and accept the bundled copy when the API is slower than that.
    """
    if api_url:
        live = load_live_spec(api_url, refresh=refresh, timeout=timeout)
        if live is not None:
            return live
    return load_spec()


def is_live(api_url: str | None) -> bool:
    """Whether `active_spec` would answer from the API rather than from the bundled copy."""
    return bool(api_url) and load_live_spec(api_url) is not None


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


def _match_path(spec: dict[str, Any], path: str) -> str | None:
    spec_paths = spec.get("paths", {})
    candidate = normalize_path(path.split("?", 1)[0])
    if candidate in spec_paths:
        return candidate
    for template in spec_paths:
        if "{" in template and _segments_match(template, candidate):
            return template
    return None


@lru_cache(maxsize=512)
def match_path(path: str) -> str | None:
    """Find the spec path template a concrete request path belongs to."""
    return _match_path(load_spec(), path)


def operation(
    method: str, path: str, *, api_url: str | None = None, refresh: bool = False, timeout: float = 15.0
) -> dict[str, Any] | None:
    """Look up one operation object, or None when the spec does not document it."""
    spec = active_spec(api_url, refresh=refresh, timeout=timeout)
    template = _match_path(spec, path) if api_url else match_path(path)
    if template is None:
        return None
    return spec["paths"][template].get(method.lower())


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


def request_schema(
    method: str,
    path: str,
    content_type: str = "application/json",
    *,
    api_url: str | None = None,
    refresh: bool = False,
    timeout: float = 15.0,
) -> dict[str, Any] | None:
    """Resolved JSON Schema for an operation's request body.

    With ``api_url`` the schema comes from that API's own spec where it can be reached, so
    a field it constrains today is constrained here today -- not after the next release of
    this CLI.
    """
    op = operation(method, path, api_url=api_url, refresh=refresh, timeout=timeout)
    if not op:
        return None
    body = op.get("requestBody", {}).get("content", {}).get(content_type, {}).get("schema")
    if not body:
        return None
    schemas = active_spec(api_url, refresh=refresh, timeout=timeout).get("components", {}).get("schemas", {})
    return _resolve(body, schemas)


def resolve_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Inline every ``$ref`` in a schema fragment taken from the spec."""
    return _resolve(schema, load_spec().get("components", {}).get("schemas", {}))
