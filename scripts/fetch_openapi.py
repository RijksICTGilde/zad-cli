#!/usr/bin/env python3
"""Fetch the upstream OpenAPI spec from the deployed Operations Manager.

Usage:
    python scripts/fetch_openapi.py                    # uses ZAD_API_URL + ZAD_API_KEY from env/.env
    python scripts/fetch_openapi.py --url URL --key KEY # explicit
    python scripts/fetch_openapi.py --output path.json  # custom output path

The spec is written to api/upstream-openapi.json by default.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx


def fetch_spec(api_url: str, api_key: str) -> dict:
    base = api_url.rstrip("/")
    if base.endswith("/api"):
        base = base[:-4]

    openapi_url = f"{base}/openapi.json"
    response = httpx.get(openapi_url, headers={"X-API-Key": api_key}, timeout=30)
    response.raise_for_status()

    content_type = response.headers.get("content-type", "").lower()
    if "json" not in content_type:
        print(f"Error: Expected JSON response but got {content_type}", file=sys.stderr)
        print(f"Response body (first 500 chars): {response.text[:500]}", file=sys.stderr)
        sys.exit(1)

    return response.json()


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch upstream OpenAPI spec")
    parser.add_argument("--url", default=None, help="API URL (default: ZAD_API_URL or built-in default)")
    parser.add_argument("--key", default=None, help="API key (default: ZAD_API_KEY)")
    parser.add_argument("--output", default="api/upstream-openapi.json", help="Output file path")
    args = parser.parse_args()

    import os

    from dotenv import load_dotenv

    load_dotenv()

    api_url = args.url or os.environ.get(
        "ZAD_API_URL", "https://operations-manager.rig.prd1.gn2.quattro.rijksapps.nl/api"
    )
    api_key = args.key or os.environ.get("ZAD_API_KEY")
    if not api_key:
        print("Error: ZAD_API_KEY is required (set via --key or ZAD_API_KEY env var)", file=sys.stderr)
        sys.exit(1)

    if not api_url.startswith("https://") and "localhost" not in api_url and "127.0.0.1" not in api_url:
        print("Warning: sending API key over non-HTTPS connection", file=sys.stderr)

    print(f"Fetching OpenAPI spec from {api_url}...", file=sys.stderr)
    spec = fetch_spec(api_url, api_key)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(spec, indent=2) + "\n")
    print(f"Written to {output} ({len(spec.get('paths', {}))} paths)", file=sys.stderr)


if __name__ == "__main__":
    main()
