"""The version has to say the same thing everywhere it is written down.

`uv.lock` records the project's own version alongside its dependencies, and nothing regenerated
it at release time, so it trailed a release behind: 0.10.2 in the lock while `pyproject.toml`
said 0.11.0. It was repaired twice as bycatch of a Dependabot PR and drifted straight back both
times, because the only thing that would have caught it was the release job that caused it.

`build_command = "uv lock"` fixes the cause, and `uv sync --locked` in CI catches a recurrence:
that question cannot be asked from pytest, because `uv sync` and `uv run` both rewrite the
lockfile before a test gets to read it. What is left here is the half uv does not touch.
"""

import tomllib
from pathlib import Path

import zad_cli

ROOT = Path(__file__).resolve().parents[1]


def test_the_package_reports_the_version_pyproject_declares() -> None:
    declared = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]

    assert zad_cli.__version__ == declared, (
        f"zad_cli.__version__ is {zad_cli.__version__} and pyproject.toml says {declared}. "
        "semantic-release writes both; one of them did not get written."
    )
