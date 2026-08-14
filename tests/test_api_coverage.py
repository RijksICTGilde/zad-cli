"""The three questions `scripts/check_coverage.py` asks, asked on every test run.

The script itself only ran in the api-sync workflow, against the spec it had just fetched.
That answers "what changed upstream?" and nothing else: a call that has been broken since
December looks the same in every diff, because it never changed. Both bugs that got past us
were of that kind, so the questions belong here, against the spec we vendor, where they get
asked whether or not upstream moved.

1. Does every path the client calls exist?          (`zad metrics`, seven dead commands)
2. Does every call carry the body its endpoint requires?  (`zadctl restore`, three of them)
3. And do the checks themselves still detect anything?
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from check_coverage import find_calls_without_required_body, find_dead_client_paths  # noqa: E402

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
