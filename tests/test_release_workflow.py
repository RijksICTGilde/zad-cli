"""The `verify-upgrade` job in the release workflow: the only cover for Windows and macOS.

That job cannot run before a release exists, so nothing here runs it. What is testable
without a release is the part that goes wrong silently: a platform that gets built and then
never upgrade-tested, a job that drifts out of this workflow into one no event starts, and the
filter that decides whether the second measurement happens at all -- a wrong filter there ends
in `::notice::` and a green job, which is the one outcome the job may not have.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

WORKFLOW = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "release-binaries.yml"


def _jobs() -> dict[str, Any]:
    return yaml.safe_load(WORKFLOW.read_text())["jobs"]


def _platforms(job: dict[str, Any]) -> set[tuple[str, str]]:
    """Which (label, binary) pairs a matrix covers."""
    return {(entry["label"], entry["binary"]) for entry in job["strategy"]["matrix"]["include"]}


def _step(name_fragment: str) -> dict[str, Any]:
    steps = _jobs()["verify-upgrade"]["steps"]
    matching = [step for step in steps if name_fragment in step["name"]]
    assert len(matching) == 1, f"{name_fragment!r} matches {[s['name'] for s in steps]}"
    return matching[0]


# --- The shape of the job ---


def test_every_platform_the_release_builds_is_upgrade_verified() -> None:
    """Both matrices from the file, so a platform added to one and not the other is red.

    A build nobody upgrade-tests is exactly how the previous round shipped an unproven path.
    """
    jobs = _jobs()
    assert _platforms(jobs["verify-upgrade"]) == _platforms(jobs["build"])


def test_the_upgrade_check_runs_after_publishing_in_this_same_workflow() -> None:
    """Not a workflow on `release: published`: that release is created with GITHUB_TOKEN, and
    an event raised by that token starts no workflow run."""
    jobs = _jobs()
    assert jobs["verify-upgrade"]["needs"] == "publish"
    assert "publish" in jobs


@pytest.mark.parametrize("step", ["The published binary", "The previous release"])
def test_both_measurements_upgrade_and_then_ask_what_runs(step: str) -> None:
    """Each step installs over a running binary and then reads the version back.

    `--to "$TAG"` and not a bare `upgrade`: `releases/latest` skips a pre-release, so a bare
    one would measure a different release than the one just published.
    """
    script = _step(step)["run"]
    assert 'upgrade --to "$TAG"' in script
    assert "--version" in script


def test_the_previous_release_is_probed_on_an_exit_code() -> None:
    """Not a grep of `upgrade --help`: a renderer that wraps or styles `--to` turns a present
    option into an absent one, and the quiet skip that follows is indistinguishable from a
    pass."""
    script = _step("The previous release")["run"]
    assert re.search(r'if ! "\./\$BINARY" upgrade --help\s*>\s*/dev/null\s*2>&1', script), script


# --- The filter that picks the release to upgrade from ---


def _previous_release_filter() -> str:
    """The `--jq` program out of the step, so the test and the workflow cannot drift apart."""
    script = _step("The previous release")["run"]
    match = re.search(r'--jq "((?:[^"\\]|\\.)*)"', script)
    assert match is not None, "the step no longer passes a --jq program"
    return match.group(1).replace('\\"', '"')


TAG = "v2.0.0"
RELEASES = [
    {"tagName": "v3.0.0", "isDraft": True, "isPrerelease": False},
    {"tagName": "v2.1.0-rc.1", "isDraft": False, "isPrerelease": True},
    {"tagName": TAG, "isDraft": False, "isPrerelease": False},
    {"tagName": "v1.9.0", "isDraft": False, "isPrerelease": False},
]


def _previous(releases: list[dict[str, Any]]) -> str:
    """What the step's own filter answers for this release list, with `$TAG` already in it.

    Bash interpolates `$TAG` before jq sees the program, which is what this does too.
    """
    program = _previous_release_filter().replace("$TAG", TAG)
    done = subprocess.run(  # noqa: S603
        ["jq", "-r", program],  # noqa: S607 - resolved above, and the workflow calls it by name too
        input=json.dumps(releases),
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout.strip()


@pytest.mark.skipif(shutil.which("jq") is None, reason="no jq on PATH to run the workflow's own filter with")
@pytest.mark.parametrize(
    ("releases", "expected"),
    [
        pytest.param(RELEASES, "v1.9.0", id="the newest real release that is not the one just published"),
        pytest.param(RELEASES[2:], "v1.9.0", id="order is the list's, newest first"),
        pytest.param([RELEASES[2]], "", id="nothing earlier than the release just published"),
        pytest.param([], "", id="no releases at all"),
        pytest.param(RELEASES[:2], "", id="only drafts and pre-releases"),
        pytest.param(
            [{"tagName": "v1.9.0", "isDraft": False, "isPrerelease": False}],
            "v1.9.0",
            id="the published tag is not in the list yet",
        ),
    ],
)
def test_the_previous_release_is_the_newest_published_one_that_is_not_this_tag(
    releases: list[dict[str, Any]], expected: str
) -> None:
    """A draft or a pre-release is not a release anybody upgraded from, and upgrading from the
    tag just published would measure nothing."""
    assert _previous(releases) == expected
