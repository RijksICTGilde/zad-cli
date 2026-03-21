"""Available ZAD services (matches ServiceType enum in Operations Manager)."""

VALID_SERVICES = [
    "publish-on-web",
    "keycloak",
    "authorization-wall",
    "metrics-scraper",
    "persistent-storage",
    "temp-storage",
    "postgresql-database",
    "namespace-postgresql-database",
    "minio-storage",
    "redis",
    "namespace-redis",
]


def validate_service(name: str) -> str:
    """Validate a service name, exit with error if invalid."""
    if name in VALID_SERVICES:
        return name
    import sys

    print(f"Error: unknown service '{name}'.", file=sys.stderr)
    print(f"Available: {', '.join(VALID_SERVICES)}", file=sys.stderr)
    raise SystemExit(1)
