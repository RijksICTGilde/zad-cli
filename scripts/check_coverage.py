#!/usr/bin/env python3
"""Compare upstream OpenAPI endpoints against ZadClient coverage.

Reads api/upstream-openapi.json and extracts all API paths.
Extracts URL patterns from src/zad_cli/api/client.py.
Reports which upstream endpoints are not covered by the CLI client.

The script distinguishes between:
- Current endpoints: v2, plus v1 endpoints without a v2 replacement
- Deprecated v1 with v2 replacement: skipped (the CLI uses v2)
- Non-API infrastructure: skipped (health, auth, web UI, docs)

Usage:
    python scripts/check_coverage.py
    python scripts/check_coverage.py --spec path/to/openapi.json
    python scripts/check_coverage.py --json  # machine-readable output
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# Tags in the upstream OpenAPI spec that mark deprecated v1 endpoints.
_DEPRECATED_TAGS = {"v1 (deprecated)"}

# Paths to skip entirely: infrastructure, not meaningful for CLI users.
SKIP_PATHS = {
    "/openapi.json",
    "/docs",
    "/docs/oauth2-redirect",
    "/redoc",
    "/api/metrics",
}

SKIP_PREFIXES = (
    "/auth/",
    "/invite/",
    "/health",
    "/readyz",
    "/forms/",
    "/static/",
)

# Endpoints the CLI reaches without a literal path in client.py.
#
# Since 1.0 the per-service config and values endpoints are built from the service
# registry (GET /api/v2/services), not from a table of ~50 paths: `zadctl service config
# set postgresql-database` composes the PUT from the layer the catalog reports. That is
# the point of the registry, so the regex below is what "covered" means for them.
#
# Each entry is (method-set, path regex, the command or module that covers it).
GENERIC_COVERAGE: list[tuple[set[str], str, str]] = [
    (
        {"PUT", "DELETE", "PATCH"},
        r"^/api/v2/projects/\{[^}]+\}/services/[a-z0-9-]+/config/"
        r"(project|component/\{[^}]+\}|deployment/\{[^}]+\})$",
        "zadctl service config set|clear|patch (registry-driven)",
    ),
    (
        {"GET", "POST", "PATCH", "DELETE"},
        r"^/api/v2/projects/\{[^}]+\}/services/[a-z0-9-]+/values/.*$",
        "zadctl env / zadctl alias (registry-driven)",
    ),
    (
        {"POST", "PUT"},
        r"^/api/v2/projects/\{[^}]+\}/services/attachments/(attachment|component)/.*$",
        "zadctl attachment add|assign|update (multipart)",
    ),
    ({"GET"}, r"^/api/v2/services(/\{[^}]+\})?$", "zadctl service list|describe (api/registry.py)"),
    ({"GET"}, r"^/version$", "zadctl version (client.server_version)"),
]

# Endpoints deliberately left out of 1.0, each with the reason. Listed rather than
# silently ignored: a reader should be able to tell "not built" from "forgotten".
DEFERRED: dict[tuple[str, str], str] = {
    ("GET", "/api/federation/health"): "federation is platform infrastructure, not a project operation",
    ("GET", "/api/federation/peers"): "federation is platform infrastructure, not a project operation",
    ("POST", "/api/tasks"): "creating a raw task by hand bypasses every command that owns one",
    ("POST", "/api/v1/projects/{project_name}/images/push"): (
        "pushing an image belongs with the build story, which the 1.0 plan puts out of scope"
    ),
}


# Paths the client calls that the spec does not have. Same principle as DEFERRED: a gap may
# stay, but only with a reason next to it. Without this list the check would be a wall of
# noise; with it, every dead path is a decision somebody wrote down.
#
# Two kinds live here. An *artefact* is a path the extractor mis-reads out of the source and
# that is not a real call. A *gap* is a real call to something the API does not offer, and
# every one of those is a bug waiting to be reported or removed.
KNOWN_DEAD: dict[tuple[str, str], str] = {
    ("DELETE", "{p}/{p}"): "artefact: the extractor reads an f-string variable as a path",
    ("POST", "{p}/:delete"): "artefact: the extractor reads an f-string variable as a path",
    ("PUT", "{p}/{p}"): "artefact: the extractor reads an f-string variable as a path",
}


def find_dead_client_paths(spec_path: Path, client_path: Path) -> list[tuple[str, str]]:
    """Paths the client calls that the spec does not document.

    The forward check asks "is every endpoint used?", which is why it reported 112 of 112
    while seven `zad metrics` commands pointed at nothing. Nothing that is absent from the
    spec can show up in a diff of it either: what was never there cannot be deleted. So the
    question has to be asked from the other side as well.
    """
    spec = json.loads(spec_path.read_text())
    documented = set()
    for path, operations in spec.get("paths", {}).items():
        for method in operations:
            if method.lower() not in ("get", "post", "put", "delete", "patch"):
                continue
            documented.add((method.upper(), _normalize_path(path)))

    dead = []
    for method, path in extract_client_paths(client_path):
        if (method, _normalize_path(path)) in documented:
            continue
        if (method, path) in KNOWN_DEAD:
            continue
        dead.append((method, path))
    return sorted(dead)


def find_calls_without_required_body(spec_path: Path, client_path: Path) -> list[tuple[str, str, list[str]]]:
    """Calls to an endpoint that requires a request body, made without one.

    The third question, and the one that let `zadctl restore database|bucket|project` return
    422 for months. The other two checks compare *paths*, and by that measure a call with
    no body looks like full coverage: the endpoint exists and something calls it. What is
    wrong is the shape of the call, which only the schema knows.

    Deliberately blunt about what counts as sending a body: any of `json=`, `payload`,
    `data=` or `files=` in the call. Whether the fields inside are the right ones is not
    something this can see, and pretending otherwise would make it a check people stop
    trusting. Missing entirely is the case worth catching, because it cannot ever work.
    """
    spec = json.loads(spec_path.read_text())
    required_bodies: dict[tuple[str, str], list[str]] = {}
    for path, operations in spec.get("paths", {}).items():
        for method, details in operations.items():
            if method.lower() not in ("post", "put", "patch"):
                continue
            body = details.get("requestBody")
            if not body or not body.get("required"):
                continue
            schema = body.get("content", {}).get("application/json", {}).get("schema", {})
            ref = schema.get("$ref", "")
            if ref:
                name = ref.rsplit("/", 1)[-1]
                fields = spec.get("components", {}).get("schemas", {}).get(name, {}).get("required", [])
            else:
                fields = schema.get("required", [])
            if fields:
                required_bodies[(method.upper(), _normalize_path(path))] = fields

    source = client_path.read_text()
    pattern = re.compile(r'self\._(?:async_)?request\(\s*"(\w+)"\s*,\s*f?"([^"]+)"([^)]*)\)', re.DOTALL)
    missing = []
    for match in pattern.finditer(source):
        method, path, rest = match.group(1), match.group(2), match.group(3)
        fields = required_bodies.get((method, _normalize_path(path)))
        if not fields:
            continue
        if any(marker in rest for marker in ("json=", "payload", "data=", "files=")):
            continue
        missing.append((method, path, fields))
    return sorted(missing)


def load_openapi_endpoints(spec_path: Path) -> list[dict]:
    """Extract endpoint info from an OpenAPI spec."""
    spec = json.loads(spec_path.read_text())
    endpoints = []
    for path, operations in spec.get("paths", {}).items():
        for method, details in operations.items():
            if method not in ("get", "post", "put", "delete", "patch"):
                continue
            endpoints.append(
                {
                    "method": method.upper(),
                    "path": path,
                    "tags": set(details.get("tags", [])),
                    "summary": details.get("summary", ""),
                    "deprecated": details.get("deprecated", False),
                }
            )
    return endpoints


def extract_client_paths(client_path: Path) -> set[tuple[str, str]]:
    """Extract (method, normalized_path) from ZadClient source code.

    Uses regex to find _request() and _async_request() calls with literal
    string arguments. Falls back gracefully but warns if the number of
    matches seems too low relative to public methods.
    """
    source = client_path.read_text()
    covered = set()
    # Match both single-line and multi-line calls (DOTALL not needed because
    # we match up to the closing quote, which is always on the same line as
    # the opening quote for method and path arguments)
    pattern = re.compile(
        r"self\._(?:async_)?request\(\s*"
        r'"(\w+)"\s*,\s*'  # method: "GET", "POST", etc.
        r'f?"([^"]+)"'  # path: f"/v2/..." or "/projects/..."
    )
    for match in pattern.finditer(source):
        covered.add((match.group(1), _normalize_path(match.group(2))))

    # Sanity check: count public methods on ZadClient that should have
    # _request calls. Methods like close(), resolve_namespace(),
    # wait_for_task(), list_deployments(), describe_deployment(),
    # project_status(), and web_url are derived/wrappers without direct
    # _request calls.
    method_pattern = re.compile(r"^\s{4}def (\w+)\(self", re.MULTILINE)
    public_methods = {m for m in method_pattern.findall(source) if not m.startswith("_")}
    wrapper_methods = {
        "close",
        "resolve_namespace",
        "wait_for_task",
        "list_deployments",
        "describe_deployment",
        "project_status",
        "web_url",
    }
    expected_min = len(public_methods - wrapper_methods)
    if len(covered) < expected_min * 0.8:
        print(
            f"Warning: regex found {len(covered)} endpoint calls but expected ~{expected_min}. "
            f"Client code may have been refactored in a way the regex doesn't match.",
            file=sys.stderr,
        )

    return covered


def _normalize_path(path: str) -> str:
    """Normalize a path for comparison.

    Strips /api prefix, normalizes parameter names, and normalizes
    action separators (both :action and /:action become /:action).
    """
    if path.startswith("/api"):
        path = path[4:]
    path = re.sub(r"\{[^}]+\}", "{p}", path)
    # Normalize :action to /:action (client uses /tasks/{p}:cancel, spec uses /:cancel)
    path = re.sub(r"(?<!/):([\w-]+)$", r"/:\1", path)
    return path


def _strip_version_prefix(path: str) -> str:
    """Strip /api and version prefix for semantic comparison.

    /api/v2/projects/{p}/:refresh -> /projects/{p}/:refresh
    /api/projects/{p}/:refresh    -> /projects/{p}/:refresh
    """
    if path.startswith("/api"):
        path = path[4:]
    path = re.sub(r"^/v[12]/", "/", path)
    return re.sub(r"\{[^}]+\}", "{p}", path)


def _generic_cover(method: str, path: str) -> str | None:
    """The registry-driven command that covers this endpoint, if any."""
    for methods, pattern, description in GENERIC_COVERAGE:
        if method in methods and re.match(pattern, path):
            return description
    return None


def _is_skippable(path: str) -> bool:
    """Check if a path should be skipped entirely (non-API infrastructure)."""
    if path in SKIP_PATHS:
        return True
    if any(path.startswith(prefix) for prefix in SKIP_PREFIXES):
        return True
    # Web UI routes: not under /api/
    return not path.startswith("/api/") and "/" in path[1:]


def main() -> None:
    parser = argparse.ArgumentParser(description="Check CLI coverage of upstream API")
    parser.add_argument("--spec", default="api/upstream-openapi.json", help="Path to OpenAPI spec")
    parser.add_argument("--client", default="src/zad_cli/api/client.py", help="Path to client source")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    spec_path = Path(args.spec)
    client_path = Path(args.client)

    if not spec_path.exists():
        print(f"Error: {spec_path} not found. Run scripts/fetch_openapi.py first.", file=sys.stderr)
        sys.exit(1)

    spec_data = json.loads(spec_path.read_text())
    if not spec_data.get("paths"):
        print("Warning: OpenAPI spec has no paths. Run scripts/fetch_openapi.py to populate it.", file=sys.stderr)
        sys.exit(0)

    all_endpoints = load_openapi_endpoints(spec_path)
    client_paths = extract_client_paths(client_path)
    dead = find_dead_client_paths(spec_path, client_path)
    bodyless = find_calls_without_required_body(spec_path, client_path)

    # Build set of v2 semantic paths to identify which v1 endpoints have v2 replacements
    v2_semantic = set()
    for ep in all_endpoints:
        if "/v2/" in ep["path"]:
            v2_semantic.add((ep["method"], _strip_version_prefix(ep["path"])))

    covered: list[dict] = []
    uncovered: list[dict] = []
    skipped: list[dict] = []
    deprecated_v1: list[dict] = []
    deferred: list[dict] = []

    for ep in all_endpoints:
        method, path = ep["method"], ep["path"]

        if _is_skippable(path):
            skipped.append(ep)
            continue

        is_deprecated = bool(ep["tags"] & _DEPRECATED_TAGS) or ep.get("deprecated", False)
        if is_deprecated:
            # Check if there's a v2 equivalent for this deprecated endpoint
            semantic = (method, _strip_version_prefix(path))
            # Special case: v1 uses GET for refresh, v2 uses POST
            has_v2 = semantic in v2_semantic
            if not has_v2 and method == "GET":
                has_v2 = ("POST", semantic[1]) in v2_semantic
            # Special case: v1 clone paths differ (clone-database-from-external vs clone-database)
            if not has_v2 and "clone-" in path and "-from-external" in path:
                alt_path = semantic[1].replace("-from-external", "")
                has_v2 = (method, alt_path) in v2_semantic
            # Special case: v1 DELETE uses different path structure
            if not has_v2 and method == "DELETE":
                has_v2 = ("DELETE", semantic[1]) in v2_semantic

            if has_v2:
                deprecated_v1.append(ep)
                continue
            # No v2 replacement: treat as a current endpoint (fall through)

        if (method, path) in DEFERRED:
            ep["reason"] = DEFERRED[(method, path)]
            deferred.append(ep)
            continue

        generic = _generic_cover(method, path)
        if generic:
            ep["via"] = generic
            covered.append(ep)
            continue

        normalized = (method, _normalize_path(path))
        if normalized in client_paths:
            covered.append(ep)
        else:
            uncovered.append(ep)

    if args.json:

        def _serialize(eps: list[dict]) -> list[dict]:
            return [{"method": e["method"], "path": e["path"], "summary": e["summary"]} for e in eps]

        print(
            json.dumps(
                {
                    "covered": _serialize(covered),
                    "uncovered": _serialize(uncovered),
                    "deferred": [
                        {"method": e["method"], "path": e["path"], "reason": e.get("reason", "")} for e in deferred
                    ],
                    "deprecated_v1": _serialize(deprecated_v1),
                    "skipped": _serialize(skipped),
                    "stats": {
                        "total": len(covered) + len(uncovered),
                        "covered": len(covered),
                        "uncovered": len(uncovered),
                        "deferred": len(deferred),
                        "deprecated_v1": len(deprecated_v1),
                        "skipped": len(skipped),
                    },
                },
                indent=2,
            )
        )
    else:
        total = len(covered) + len(uncovered)
        print(f"Upstream API: {total} current endpoints")
        print(f"  Covered by CLI: {len(covered)}")
        print(f"  Not covered:    {len(uncovered)}")
        print(f"  Deferred:       {len(deferred)} (deliberately out of scope, see below)")
        print(f"  Deprecated v1:  {len(deprecated_v1)} (skipped, CLI uses v2)")
        print(f"  Non-API/infra:  {len(skipped)} (skipped)")

        if deferred:
            print("\nDeliberately not covered:")
            for ep in sorted(deferred, key=lambda e: (e["path"], e["method"])):
                print(f"  {ep['method']:6s} {ep['path']}")
                print(f"         {ep.get('reason', '')}")

        if uncovered:
            print("\nUncovered endpoints:")
            for ep in sorted(uncovered, key=lambda e: (e["path"], e["method"])):
                tags = ", ".join(sorted(ep["tags"])) if ep["tags"] else "untagged"
                print(f"  {ep['method']:6s} {ep['path']}")
                print(f"         {ep['summary']}  [{tags}]")

    if dead:
        print(f"\nPaths the client calls that the API does not have: {len(dead)}")
        for method, path in dead:
            print(f"  {method:6s} {path}")
        print("  Each is a command that cannot work. Remove it, or add it to KNOWN_DEAD with a reason.")

    if bodyless:
        print(f"\nCalls to an endpoint that requires a body, sent without one: {len(bodyless)}")
        for method, path, fields in bodyless:
            print(f"  {method:6s} {path}")
            print(f"         required: {', '.join(fields)}")
        print("  Each of these returns 422 every time. Send the body.")

    if uncovered or dead or bodyless:
        sys.exit(1)


if __name__ == "__main__":
    main()
