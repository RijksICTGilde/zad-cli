#!/usr/bin/env python3
"""Compare upstream OpenAPI endpoints against ZadClient coverage.

Reads api/upstream-openapi.json and extracts all API paths.
Extracts URL patterns from src/zad_cli/api/client.py.
Reports which upstream endpoints are not covered by the CLI client.

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

# Paths to skip in the OpenAPI spec. These are matched BEFORE stripping /api prefix,
# so they must match the raw OpenAPI paths (which include /api/).
SKIP_PREFIXES = (
    "/auth/",
    "/invite/",
    "/health",
    "/readyz",
    "/forms/",
    "/static/",
)

SKIP_PATHS = {
    "/openapi.json",
    "/docs",
    "/docs/oauth2-redirect",
    "/redoc",
    "/api/metrics",  # prometheus metrics endpoint
}

# Web UI routes that look like API routes but aren't.
# These are paths WITHOUT /api/ prefix that serve HTML pages.
_WEB_UI_PREFIXES = (
    "/projects/",  # web UI project pages (not /api/projects/)
    "/admin/",  # web UI admin pages (not /api/v2/admin/)
)


def _is_web_ui_route(path: str) -> bool:
    """Check if a path is a web UI route (not an API endpoint)."""
    # API routes start with /api/
    if path.startswith("/api/"):
        return False
    return any(path.startswith(prefix) for prefix in _WEB_UI_PREFIXES)


def load_openapi_paths(spec_path: Path) -> list[tuple[str, str]]:
    """Extract (method, path) pairs from an OpenAPI spec."""
    spec = json.loads(spec_path.read_text())
    paths = spec.get("paths", {})
    endpoints = []
    for path, methods in paths.items():
        for method in methods:
            if method in ("get", "post", "put", "delete", "patch"):
                endpoints.append((method.upper(), path))
    return endpoints


def extract_client_paths(client_path: Path) -> set[tuple[str, str]]:
    """Extract (method, path_pattern) from ZadClient source code."""
    source = client_path.read_text()
    covered = set()

    # Match self._request("METHOD", f"/path...") and self._async_request("METHOD", f"/path...")
    # Also handles non-f-strings like self._request("GET", "/projects")
    pattern = re.compile(r'self\._(?:async_)?request\(\s*"(\w+)"\s*,\s*f?"([^"]+)"')
    for match in pattern.finditer(source):
        method = match.group(1)
        path = match.group(2)
        # Normalize f-string {var} to {param} for comparison
        path = re.sub(r"\{[^}]+\}", "{param}", path)
        covered.add((method, path))

    return covered


def normalize_path(path: str) -> str:
    """Normalize path parameters for comparison.

    Converts /api/v2/projects/{project_name} to /v2/projects/{param}
    and /v2/projects/{project} to /v2/projects/{param}.
    """
    # Strip /api prefix if present
    if path.startswith("/api"):
        path = path[4:]
    # Normalize parameter names
    path = re.sub(r"\{[^}]+\}", "{param}", path)
    return path


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

    # Check if the spec is still a placeholder
    spec_data = json.loads(spec_path.read_text())
    if not spec_data.get("paths"):
        print("Warning: OpenAPI spec has no paths. Run scripts/fetch_openapi.py to populate it.", file=sys.stderr)
        sys.exit(0)

    upstream = load_openapi_paths(spec_path)
    client_paths = extract_client_paths(client_path)

    # Normalize for comparison
    client_normalized = {(m, normalize_path(p)) for m, p in client_paths}

    covered = []
    uncovered = []
    skipped = []

    for method, path in upstream:
        # Skip non-API paths
        if any(path.startswith(prefix) for prefix in SKIP_PREFIXES):
            skipped.append((method, path))
            continue
        if path in SKIP_PATHS:
            skipped.append((method, path))
            continue
        if _is_web_ui_route(path):
            skipped.append((method, path))
            continue

        normalized = (method, normalize_path(path))
        if normalized in client_normalized:
            covered.append((method, path))
        else:
            uncovered.append((method, path))

    if args.json:
        print(
            json.dumps(
                {
                    "covered": [{"method": m, "path": p} for m, p in covered],
                    "uncovered": [{"method": m, "path": p} for m, p in uncovered],
                    "skipped": [{"method": m, "path": p} for m, p in skipped],
                },
                indent=2,
            )
        )
    else:
        total_api = len(covered) + len(uncovered)
        print(f"Upstream API: {total_api} endpoints ({len(skipped)} skipped)")
        print(f"Covered by CLI: {len(covered)}")
        print(f"Not covered: {len(uncovered)}")
        if uncovered:
            print("\nUncovered endpoints:")
            for method, path in sorted(uncovered):
                print(f"  {method:6s} {path}")

    # Exit non-zero if there are uncovered endpoints (useful for CI gating)
    if uncovered:
        sys.exit(1)


if __name__ == "__main__":
    main()
