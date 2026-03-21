"""Available ZAD services (matches ServiceType enum in Operations Manager)."""

from enum import StrEnum


class ServiceName(StrEnum):
    publish_on_web = "publish-on-web"
    keycloak = "keycloak"
    authorization_wall = "authorization-wall"
    metrics_scraper = "metrics-scraper"
    persistent_storage = "persistent-storage"
    temp_storage = "temp-storage"
    postgresql_database = "postgresql-database"
    namespace_postgresql_database = "namespace-postgresql-database"
    minio_storage = "minio-storage"
    redis = "redis"
    namespace_redis = "namespace-redis"
