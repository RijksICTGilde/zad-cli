"""Service catalog: parsing, endpoint derivation, caching and the offline fallback.

The catalog is what replaced the hardcoded service list, so these tests are the guard
against a service name creeping back into the source.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import httpx
import pytest
import respx

from zad_cli.api import registry
from zad_cli.api.registry import (
    MissingLayerError,
    ServiceCatalog,
    ServiceEntry,
    UnknownServiceError,
    load_catalog,
    load_service,
)

API_URL = "https://zad.example.test/api"

CATALOG_PAYLOAD = {
    "services": [
        {
            "name": "postgresql-database",
            "description": "Database service voor applicaties",
            "configurable": True,
            "targets": ["project"],
            "value_targets": [],
            "config_schema_version": "1.0",
            "kind": "user",
            "binding": "deployment",
        },
        {
            "name": "publish-on-web",
            "description": "Publiceer op het web",
            "configurable": True,
            "targets": ["component"],
            "value_targets": [],
            "kind": "user",
            "binding": "component",
        },
        {
            "name": "cross-domain-access",
            "description": "Netwerktoegang tussen projecten",
            "configurable": True,
            "targets": ["project", "deployment"],
            "value_targets": [],
            "kind": "user",
            "binding": "deployment",
        },
        {
            "name": "user-env-vars",
            "description": "Eigen omgevingsvariabelen",
            "configurable": False,
            "targets": [],
            "value_targets": ["component", "deployment-component"],
            "kind": "system",
            "binding": "component",
        },
        {
            "name": "namespace-redis",
            "description": "Redis in de eigen namespace",
            "configurable": True,
            "targets": [],
            "value_targets": [],
            "hidden": True,
            "kind": "user",
            "binding": "deployment",
        },
    ]
}


@pytest.fixture(autouse=True)
def _fetching_allowed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """These tests exercise fetching, so they opt out of the global offline default."""
    monkeypatch.setattr(registry, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.delenv("ZAD_CATALOG_OFFLINE", raising=False)
    yield


def _catalog() -> ServiceCatalog:
    return ServiceCatalog(entries=[ServiceEntry.from_api(s) for s in CATALOG_PAYLOAD["services"]], source="live")


# --- Parsing ---


def test_entry_keeps_optional_fields_absent_without_failing():
    """An API build that omits kind/binding must still yield a usable entry."""
    entry = ServiceEntry.from_api({"name": "minimal", "configurable": False})
    assert entry.name == "minimal"
    assert entry.targets == []
    assert entry.kind == ""
    assert entry.hidden is False


def test_hidden_services_are_excluded_unless_asked_for():
    catalog = _catalog()
    assert "namespace-redis" not in catalog.names()
    assert "namespace-redis" in catalog.names(include_hidden=True)


def test_unknown_service_names_the_valid_ones():
    with pytest.raises(UnknownServiceError) as excinfo:
        _catalog().get("postgres")
    assert "postgresql-database" in str(excinfo.value)


# --- Endpoint derivation ---


def test_project_layer_endpoint():
    entry = _catalog().get("postgresql-database")
    assert entry.config_endpoint("project") == "/v2/projects/{project}/services/postgresql-database/config/project"


def test_component_layer_endpoint_fills_the_component():
    entry = _catalog().get("publish-on-web")
    path = entry.config_endpoint("component", component="web")
    assert path == "/v2/projects/{project}/services/publish-on-web/config/component/web"


def test_component_layer_without_component_is_an_error():
    entry = _catalog().get("publish-on-web")
    with pytest.raises(MissingLayerError):
        entry.config_endpoint("component")


def test_layer_the_service_does_not_have_is_an_error():
    entry = _catalog().get("postgresql-database")
    with pytest.raises(MissingLayerError) as excinfo:
        entry.config_endpoint("component", component="web")
    assert "project" in str(excinfo.value)


def test_stated_config_endpoint_wins_over_the_derived_one():
    """When the API publishes the endpoint per layer, that is what we call."""
    entry = ServiceEntry.from_api(
        {
            "name": "odd-one",
            "configurable": True,
            "targets": ["project"],
            "layers": [
                {
                    "target": "project",
                    "config_endpoint": "PUT /api/v2/projects/{project_name}/services/odd-one/elders/project",
                }
            ],
        }
    )
    assert entry.config_endpoint("project") == "/v2/projects/{project}/services/odd-one/elders/project"


def test_values_endpoints_for_both_value_layers():
    entry = _catalog().get("user-env-vars")
    assert entry.values_endpoint("component", component="web") == (
        "/v2/projects/{project}/services/user-env-vars/values/component/web"
    )
    assert entry.values_endpoint("deployment-component", component="web", deployment="prod") == (
        "/v2/projects/{project}/services/user-env-vars/values/deployment/prod/component/web"
    )


def test_values_layer_the_service_does_not_have_is_an_error():
    entry = _catalog().get("postgresql-database")
    with pytest.raises(MissingLayerError):
        entry.values_endpoint("component", component="web")


# --- Loading ---


@respx.mock
def test_load_catalog_fetches_live_and_caches():
    route = respx.get(f"{API_URL}/v2/services").mock(return_value=httpx.Response(200, json=CATALOG_PAYLOAD))

    first = load_catalog(API_URL)
    assert first.source == "live"
    assert len(first.entries) == 5

    second = load_catalog(API_URL)
    assert second.source == "cache"
    assert route.call_count == 1


@respx.mock
def test_refresh_bypasses_the_cache():
    route = respx.get(f"{API_URL}/v2/services").mock(return_value=httpx.Response(200, json=CATALOG_PAYLOAD))
    load_catalog(API_URL)
    load_catalog(API_URL, refresh=True)
    assert route.call_count == 2


@respx.mock
def test_catalog_is_cached_per_api_url():
    """Two environments must not share one catalog."""
    other = "https://other.example.test/api"
    respx.get(f"{API_URL}/v2/services").mock(return_value=httpx.Response(200, json=CATALOG_PAYLOAD))
    respx.get(f"{other}/v2/services").mock(return_value=httpx.Response(200, json={"services": []}))

    assert len(load_catalog(API_URL).entries) == 5
    assert len(load_catalog(other).entries) == 0


@respx.mock
def test_expired_cache_is_refetched():
    respx.get(f"{API_URL}/v2/services").mock(return_value=httpx.Response(200, json=CATALOG_PAYLOAD))
    load_catalog(API_URL)
    path = registry.cache_path(API_URL)
    cached = json.loads(path.read_text())
    cached["fetched_at"] = time.time() - registry.DEFAULT_TTL_SECONDS - 1
    path.write_text(json.dumps(cached))

    assert load_catalog(API_URL).source == "live"


@respx.mock
def test_unreachable_api_falls_back_to_a_stale_cache():
    respx.get(f"{API_URL}/v2/services").mock(return_value=httpx.Response(200, json=CATALOG_PAYLOAD))
    load_catalog(API_URL)
    path = registry.cache_path(API_URL)
    cached = json.loads(path.read_text())
    cached["fetched_at"] = 0
    path.write_text(json.dumps(cached))

    respx.get(f"{API_URL}/v2/services").mock(side_effect=httpx.ConnectError("down"))
    catalog = load_catalog(API_URL)
    assert catalog.source == "cache"
    assert len(catalog.entries) == 5


@respx.mock
def test_unreachable_api_without_a_cache_falls_back_to_the_snapshot():
    respx.get(f"{API_URL}/v2/services").mock(side_effect=httpx.ConnectError("down"))
    catalog = load_catalog(API_URL)
    assert catalog.source == "snapshot"
    assert catalog.entries


def test_offline_mode_never_touches_the_network(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ZAD_CATALOG_OFFLINE", "1")
    with respx.mock:
        route = respx.get(f"{API_URL}/v2/services").mock(return_value=httpx.Response(200, json=CATALOG_PAYLOAD))
        catalog = load_catalog(API_URL)
    assert route.call_count == 0
    assert catalog.source == "snapshot"


def test_bundled_snapshot_matches_the_shape_the_cli_expects():
    """The fallback has to be usable, not just present."""
    payload = json.loads(registry.SNAPSHOT_PATH.read_text())
    catalog = ServiceCatalog(entries=[ServiceEntry.from_api(s) for s in payload["services"]], source="snapshot")
    assert len(catalog.entries) >= 20
    assert catalog.get("postgresql-database").targets == ["project"]


@respx.mock
def test_load_service_merges_detail_over_the_catalog_entry():
    respx.get(f"{API_URL}/v2/services").mock(return_value=httpx.Response(200, json=CATALOG_PAYLOAD))
    respx.get(f"{API_URL}/v2/services/postgresql-database").mock(
        return_value=httpx.Response(
            200,
            json={
                "name": "postgresql-database",
                "explanation": "# PostgreSQL\n\nUitleg.",
                "variables": [{"name": "DATABASE_SERVER_HOST", "aliases": ["APP_DATABASE_SERVER"]}],
            },
        )
    )
    entry = load_service(API_URL, "postgresql-database")
    assert entry.explanation.startswith("# PostgreSQL")
    assert entry.variables[0]["name"] == "DATABASE_SERVER_HOST"
    # The detail response carries no targets, so the catalog's must survive the merge.
    assert entry.targets == ["project"]


@respx.mock
def test_load_service_without_a_detail_endpoint_still_returns_the_entry():
    """Not every API build serves /v2/services/{name}; a 404 must not be fatal."""
    respx.get(f"{API_URL}/v2/services").mock(return_value=httpx.Response(200, json=CATALOG_PAYLOAD))
    respx.get(f"{API_URL}/v2/services/postgresql-database").mock(return_value=httpx.Response(404, json={}))

    entry = load_service(API_URL, "postgresql-database")
    assert entry.name == "postgresql-database"
    assert entry.targets == ["project"]


def test_the_hardcoded_service_module_is_gone():
    """1.0 removed src/zad_cli/services.py; the registry replaced it."""
    source_root = Path(registry.__file__).resolve().parent.parent
    assert not (source_root / "services.py").exists()


def test_no_module_carries_a_list_of_service_names():
    """The catalog is the source of truth, so no source file may enumerate services.

    A single name can be legitimate (``deployment update-image --recreate-storage`` names
    the one service it acts on). Two or more on a line is a catalog, and a catalog in the
    source is exactly what the registry replaced.
    """
    source_root = Path(registry.__file__).resolve().parent.parent
    names = {s["name"] for s in json.loads(registry.SNAPSHOT_PATH.read_text())["services"] if "-" in s["name"]}

    offenders: list[str] = []
    for path in source_root.rglob("*.py"):
        for number, line in enumerate(path.read_text().splitlines(), start=1):
            found = {name for name in names if f'"{name}"' in line or f"'{name}'" in line}
            if len(found) > 1:
                offenders.append(f"{path.name}:{number}: {sorted(found)}")
    assert not offenders, "Service names must come from the catalog, not the source: " + "; ".join(offenders)


def test_a_layer_the_registry_names_without_an_endpoint_is_a_usage_error():
    """`publish-on-web` advertises `deployment-component` with `config_endpoint: null`.

    Taking that at face value crashed the CLI with `KeyError: 'deployment-component'` and
    a Python traceback, on a command that had not yet touched the network. Whatever such a
    layer means, this CLI cannot write there, and saying so is the whole job.
    """
    from zad_cli.api.registry import MissingLayerError, ServiceEntry

    entry = ServiceEntry(
        name="publish-on-web",
        targets=["component", "deployment", "deployment-component"],
        layers=[
            {"target": "component", "config_endpoint": "PUT /api/v2/projects/{project_name}/x/component/{c}"},
            {"target": "deployment-component", "config_endpoint": None},
        ],
    )

    with pytest.raises(MissingLayerError) as excinfo:
        entry.config_endpoint("deployment-component", component="web", deployment="productie")

    message = str(excinfo.value)
    assert "deployment-component" in message
    # And it says where you can write, so the reader is not left guessing.
    assert "component" in message


def test_offline_mode_does_not_blame_the_api(monkeypatch, capsys):
    """ "The API did not answer" is untrue when nobody asked it anything.

    ZAD_CATALOG_OFFLINE is something you set yourself, and reporting it as an unreachable
    API sends the reader to debug a network that was never used. Noticed while reading the
    output of our own build script, which sets the flag.
    """
    import typer

    from zad_cli.helpers import get_catalog
    from zad_cli.settings import Settings

    monkeypatch.setenv("ZAD_CATALOG_OFFLINE", "1")
    ctx = typer.Context(typer.main.get_command(__import__("zad_cli.cli", fromlist=["app"]).app))
    ctx.obj = {"settings": Settings.resolve(api_url="https://api.example.com")}

    get_catalog(ctx)

    err = capsys.readouterr().err
    assert "did not answer" not in err
    assert "ZAD_CATALOG_OFFLINE" in err
