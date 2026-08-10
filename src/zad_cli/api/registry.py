"""The service catalog: what ZAD offers, read from the API instead of hardcoded.

``GET /api/v2/services`` is project-independent and needs no API key. It answers the two
questions a client actually has: which services exist, and at which layers each one
accepts configuration. Everything the CLI knows about services comes from here, so a
service added upstream shows up without a CLI release.

The catalog is cached on disk per API URL. A cache miss without a network falls back to
the snapshot shipped with the CLI, and the caller is told which of the three it got.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

# One day: the catalog changes with an API release, not with a project.
DEFAULT_TTL_SECONDS = 24 * 60 * 60

CACHE_DIR = Path.home() / ".cache" / "zad"
SNAPSHOT_PATH = Path(__file__).resolve().parent.parent / "data" / "services-snapshot.json"

# Where a layer's config or values live, as a path under the service's own prefix.
# Derived from the layer name, not from a per-service table: the API documents these
# paths as a single pattern and every service follows it.
_CONFIG_SUFFIX = {
    "project": "config/project",
    "component": "config/component/{component}",
    "deployment": "config/deployment/{deployment}",
}
_VALUES_SUFFIX = {
    "component": "values/component/{component}",
    "deployment-component": "values/deployment/{deployment}/component/{component}",
}


class UnknownServiceError(ValueError):
    """A service name that is not in the catalog."""


class MissingLayerError(ValueError):
    """A service does not accept config (or values) at the requested layer."""


@dataclass
class ServiceEntry:
    """One service, as the catalog describes it.

    ``kind``, ``binding``, ``hidden``, ``requires``, ``explanation``, ``layers`` and
    ``variables`` are optional: older and newer API builds expose different subsets, and
    a field that is absent must not stop the CLI from listing the service.
    """

    name: str
    description: str = ""
    configurable: bool = False
    targets: list[str] = field(default_factory=list)
    value_targets: list[str] = field(default_factory=list)
    config_schema_version: str | None = None
    kind: str = ""
    binding: str = ""
    hidden: bool = False
    requires: list[str] = field(default_factory=list)
    explanation: str = ""
    layers: list[dict[str, Any]] = field(default_factory=list)
    variables: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> ServiceEntry:
        return cls(
            name=data["name"],
            description=data.get("description") or "",
            configurable=bool(data.get("configurable", False)),
            targets=list(data.get("targets") or []),
            value_targets=list(data.get("value_targets") or []),
            config_schema_version=data.get("config_schema_version"),
            kind=data.get("kind") or "",
            binding=data.get("binding") or "",
            hidden=bool(data.get("hidden", False)),
            requires=list(data.get("requires") or []),
            explanation=data.get("explanation") or "",
            layers=list(data.get("layers") or []),
            variables=list(data.get("variables") or []),
        )

    def to_dict(self) -> dict[str, Any]:
        """Full record, for ``--output json``."""
        out: dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            "configurable": self.configurable,
            "targets": self.targets,
            "value_targets": self.value_targets,
            "config_schema_version": self.config_schema_version,
        }
        for key, value in (
            ("kind", self.kind),
            ("binding", self.binding),
            ("requires", self.requires),
            ("explanation", self.explanation),
            ("layers", self.layers),
            ("variables", self.variables),
        ):
            if value:
                out[key] = value
        if self.hidden:
            out["hidden"] = True
        return out

    # --- Endpoint derivation ---

    def config_endpoint(self, target: str, *, component: str | None = None, deployment: str | None = None) -> str:
        """Path (relative to the API root) of this service's config at one layer.

        Prefers the ``config_endpoint`` the API states per layer when it publishes one;
        otherwise builds it from the documented pattern.
        """
        if target not in self.targets:
            raise MissingLayerError(
                f"Service '{self.name}' has no config at target '{target}'. "
                f"Available: {', '.join(self.targets) or 'none'}"
            )
        stated = self._stated_endpoint(target)
        suffix = stated if stated is not None else _CONFIG_SUFFIX[target]
        return self._render(suffix, component=component, deployment=deployment)

    def values_endpoint(self, target: str, *, component: str | None = None, deployment: str | None = None) -> str:
        """Path of this service's key/value map at one layer."""
        if target not in self.value_targets:
            raise MissingLayerError(
                f"Service '{self.name}' has no values at target '{target}'. "
                f"Available: {', '.join(self.value_targets) or 'none'}"
            )
        return self._render(_VALUES_SUFFIX[target], component=component, deployment=deployment)

    def _stated_endpoint(self, target: str) -> str | None:
        """The layer's own ``config_endpoint``, reduced to the part after the service prefix."""
        for layer in self.layers:
            if layer.get("target") != target:
                continue
            endpoint = layer.get("config_endpoint")
            if not isinstance(endpoint, str):
                continue
            # "PUT /api/v2/projects/{project_name}/services/x/config/project" -> "config/project"
            path = endpoint.split()[-1]
            marker = f"/services/{self.name}/"
            if marker in path:
                return path.split(marker, 1)[1]
        return None

    def _render(self, suffix: str, *, component: str | None, deployment: str | None) -> str:
        if "{component}" in suffix:
            if not component:
                raise MissingLayerError(f"Service '{self.name}' needs a component for this layer (use --component).")
            suffix = suffix.replace("{component}", component)
        if "{deployment}" in suffix:
            if not deployment:
                raise MissingLayerError(f"Service '{self.name}' needs a deployment for this layer (use --deployment).")
            suffix = suffix.replace("{deployment}", deployment)
        # Placeholder names as the API spells them, for endpoints stated by the API itself.
        suffix = suffix.replace("{component_name}", component or "").replace("{deployment_name}", deployment or "")
        return f"/v2/projects/{{project}}/services/{self.name}/{suffix.lstrip('/')}"


@dataclass
class ServiceCatalog:
    """The catalog plus where it came from."""

    entries: list[ServiceEntry]
    source: str  # "live", "cache" or "snapshot"

    def names(self, *, include_hidden: bool = False) -> list[str]:
        return [e.name for e in self.entries if include_hidden or not e.hidden]

    def visible(self, *, include_hidden: bool = False) -> list[ServiceEntry]:
        return [e for e in self.entries if include_hidden or not e.hidden]

    def get(self, name: str) -> ServiceEntry:
        """Look up a service, or fail naming what is valid, the way the API does."""
        for entry in self.entries:
            if entry.name == name:
                return entry
        raise UnknownServiceError(f"Unknown service '{name}'. Available: {', '.join(self.names(include_hidden=True))}")


def cache_path(api_url: str) -> Path:
    """Cache file for one API URL: two environments never share a catalog."""
    digest = hashlib.sha256(api_url.rstrip("/").encode()).hexdigest()[:12]
    return CACHE_DIR / f"services-{digest}.json"


def _parse(payload: dict[str, Any], source: str) -> ServiceCatalog:
    services = payload.get("services", [])
    return ServiceCatalog(entries=[ServiceEntry.from_api(s) for s in services], source=source)


def _read_cache(path: Path, ttl: int) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        cached = json.loads(path.read_text())
        if time.time() - float(cached["fetched_at"]) > ttl:
            return None
        return cached["payload"]
    except (OSError, ValueError, KeyError):
        return None


def _write_cache(path: Path, payload: dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"fetched_at": time.time(), "payload": payload}))
    except OSError:
        # A cache we cannot write is not a reason to fail the command.
        pass


def _fetch(api_url: str, path: str, timeout: float) -> dict[str, Any]:
    """Fetch a catalog endpoint. No API key: this metadata is project-independent."""
    response = httpx.get(f"{api_url.rstrip('/')}{path}", timeout=timeout, follow_redirects=True)
    response.raise_for_status()
    return response.json()


def offline() -> bool:
    """True when the CLI must not reach out for the catalog.

    Set ``ZAD_CATALOG_OFFLINE=1`` to work from the bundled snapshot only. The test suite
    sets it so no test ever touches a real API.
    """
    return os.environ.get("ZAD_CATALOG_OFFLINE", "").lower() in ("1", "true", "yes")


def load_catalog(api_url: str, *, refresh: bool = False, ttl: int = DEFAULT_TTL_SECONDS) -> ServiceCatalog:
    """Load the service catalog: cache, then live, then the bundled snapshot."""
    path = cache_path(api_url)

    if offline():
        return _parse(json.loads(SNAPSHOT_PATH.read_text()), "snapshot")

    if not refresh:
        cached = _read_cache(path, ttl)
        if cached is not None:
            return _parse(cached, "cache")

    try:
        payload = _fetch(api_url, "/v2/services", timeout=15.0)
    except (httpx.HTTPError, ValueError):
        stale = _read_cache(path, ttl=2**31)
        if stale is not None:
            return _parse(stale, "cache")
        if SNAPSHOT_PATH.exists():
            return _parse(json.loads(SNAPSHOT_PATH.read_text()), "snapshot")
        raise

    _write_cache(path, payload)
    return _parse(payload, "live")


def load_service(api_url: str, name: str, *, refresh: bool = False, ttl: int = DEFAULT_TTL_SECONDS) -> ServiceEntry:
    """One service in as much detail as this API build offers.

    ``GET /api/v2/services/{name}`` carries the Dutch ``explanation``, the per-layer
    ``config_endpoint`` and the ``variables`` table. Not every deployment serves it, so a
    404 falls back to the catalog entry, which is enough to configure the service.
    """
    catalog = load_catalog(api_url, refresh=refresh, ttl=ttl)
    entry = catalog.get(name)
    if offline():
        return entry
    try:
        detail = _fetch(api_url, f"/v2/services/{name}", timeout=15.0)
    except (httpx.HTTPError, ValueError):
        return entry
    if not isinstance(detail, dict) or "name" not in detail:
        return entry
    return ServiceEntry.from_api({**entry.to_dict(), **detail})
