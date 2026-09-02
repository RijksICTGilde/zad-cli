"""The four questions `scripts/check_coverage.py` asks, asked on every test run.

The script itself only ran in the api-sync workflow, against the spec it had just fetched.
That answers "what changed upstream?" and nothing else: a call that has been broken since
December looks the same in every diff, because it never changed. Both bugs that got past us
were of that kind, so the questions belong here, against the spec we vendor, where they get
asked whether or not upstream moved.

1. Does every path the client calls exist?          (`zad metrics`, seven dead commands)
2. Does every call carry the body its endpoint requires?  (`zadctl restore`, three of them)
3. Does every call send only query parameters its endpoint declares?  (`zadctl logs`, -n and --since)
4. And do the checks themselves still detect anything?
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from check_coverage import (  # noqa: E402
    _AHEAD_OF_SPEC,
    find_calls_without_required_body,
    find_dead_client_paths,
    find_unknown_query_params,
)

SPEC = ROOT / "api" / "upstream-openapi.json"
CLIENT = ROOT / "src" / "zad_cli" / "api" / "client.py"


def test_no_client_path_is_absent_from_the_spec() -> None:
    dead = find_dead_client_paths(SPEC, CLIENT)

    assert dead == [], (
        "The client calls paths the API does not have, so these commands cannot work:\n"
        + "\n".join(f"  {m} {p}" for m, p in dead)
        + "\nRemove them, or add them to KNOWN_DEAD in scripts/check_coverage.py with a reason."
    )


def test_no_call_omits_a_required_request_body() -> None:
    missing = find_calls_without_required_body(SPEC, CLIENT)

    assert missing == [], (
        "These calls go to an endpoint that requires a body and send none, so they return "
        "422 every time:\n" + "\n".join(f"  {m} {p} (needs {', '.join(f)})" for m, p, f in missing)
    )


@pytest.fixture
def broken_pair(tmp_path: Path) -> tuple[Path, Path]:
    """A spec with one body-requiring endpoint, and a client that calls it without one."""
    spec = tmp_path / "spec.json"
    spec.write_text(
        json.dumps(
            {
                "paths": {
                    "/api/v1/thing/{name}": {
                        "post": {
                            "requestBody": {
                                "required": True,
                                "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Thing"}}},
                            }
                        }
                    }
                },
                "components": {"schemas": {"Thing": {"required": ["target_host"]}}},
            }
        )
    )
    client = tmp_path / "client.py"
    client.write_text(
        'class C:\n    def do(self, name):\n        self._request("POST", f"/v1/thing/{name}", params=p)\n'
    )
    return spec, client


def test_the_body_check_catches_a_missing_body(broken_pair: tuple[Path, Path]) -> None:
    """A check that has never failed is not yet a check."""
    spec, client = broken_pair

    assert find_calls_without_required_body(spec, client) == [("POST", "/v1/thing/{name}", ["target_host"])]


def test_the_body_check_accepts_a_call_that_sends_one(broken_pair: tuple[Path, Path]) -> None:
    spec, client = broken_pair
    client.write_text(
        "class C:\n    def do(self, name, payload):\n"
        '        self._request("POST", f"/v1/thing/{name}", params=p, json=payload)\n'
    )

    assert find_calls_without_required_body(spec, client) == []


def test_no_call_sends_a_query_parameter_the_spec_does_not_declare() -> None:
    undeclared = find_unknown_query_params(SPEC, CLIENT)

    assert undeclared == [], (
        "The client sends query parameters these endpoints do not declare. FastAPI drops "
        "them without a word, so the call returns 200 and the parameter does nothing:\n"
        + "\n".join(f"  {m} {p} ({', '.join(n)})" for m, p, n in undeclared)
    )


def test_every_ahead_of_spec_entry_is_still_a_gap() -> None:
    """An exception outliving its reason is worse than never having made it.

    Each `_AHEAD_OF_SPEC` entry says upstream is adding a parameter. Once it has, the entry
    stops being a promise and starts being a hole, so this fails the moment it can go.
    """
    spec = json.loads(SPEC.read_text())
    declared = {
        (method.upper(), path.removeprefix("/api")): {
            param["name"] for param in details.get("parameters", []) if param.get("in") == "query"
        }
        for path, operations in spec.get("paths", {}).items()
        for method, details in operations.items()
        if isinstance(details, dict)
    }

    landed = [
        f"  {method} {path}: {name}  ({reason})"
        for (method, path), params in _AHEAD_OF_SPEC.items()
        for name, reason in params.items()
        for declared_path, names in declared.items()
        if declared_path[0] == method and declared_path[1].replace("{project_name}", "{p}") == path and name in names
    ]

    assert landed == [], "The spec now declares these, so drop them from _AHEAD_OF_SPEC:\n" + "\n".join(landed)


@pytest.fixture
def query_pair(tmp_path: Path) -> tuple[Path, Path]:
    """A spec declaring one query parameter, and a client that builds params a line at a time."""
    spec = tmp_path / "spec.json"
    spec.write_text(
        json.dumps(
            {
                "paths": {
                    "/api/logs/{project_name}": {
                        "get": {"parameters": [{"name": "lines", "in": "query"}, {"name": "p", "in": "path"}]}
                    }
                }
            }
        )
    )
    client = tmp_path / "client.py"
    client.write_text(
        "class C:\n"
        "    def get_logs(self, project, lines=None):\n"
        "        params: dict[str, str] = {}\n"
        "        if lines:\n"
        '            params["lines"] = str(lines)\n'
        '        return self._request("GET", f"/logs/{project}", params=params)\n'
    )
    return spec, client


def test_the_query_check_accepts_a_declared_parameter(query_pair: tuple[Path, Path]) -> None:
    """The shape the client actually uses: a local dict, filled under `if`, then passed on."""
    spec, client = query_pair

    assert find_unknown_query_params(spec, client) == []


def test_the_query_check_catches_an_undeclared_parameter(query_pair: tuple[Path, Path]) -> None:
    """A check that has never failed is not yet a check. This is `zadctl logs -n`, exactly."""
    spec, client = query_pair
    client.write_text(client.read_text().replace('params["lines"]', 'params["limit"]'))

    assert find_unknown_query_params(spec, client) == [("GET", "/logs/{p}", ["limit"])]


def test_the_query_check_reads_an_inline_dict_too(query_pair: tuple[Path, Path]) -> None:
    spec, client = query_pair
    client.write_text(
        "class C:\n"
        "    def get_logs(self, project):\n"
        '        return self._request("GET", f"/logs/{project}", params={"nope": "1"})\n'
    )

    assert find_unknown_query_params(spec, client) == [("GET", "/logs/{p}", ["nope"])]
