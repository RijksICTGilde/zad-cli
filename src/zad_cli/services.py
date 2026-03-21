"""Available ZAD services (matches ServiceType enum in Operations Manager)."""

import typer

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
    """Validate a service name, raise BadParameter if invalid."""
    if name in VALID_SERVICES:
        return name
    raise typer.BadParameter(f"Unknown service '{name}'. Available: {', '.join(VALID_SERVICES)}")
