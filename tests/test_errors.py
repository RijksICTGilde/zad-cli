"""Unit tests for the diagnosis layer (api/errors.py)."""

from zad_cli.api.errors import (
    Fault,
    degraded_diagnoses,
    diagnose_http_error,
    diagnose_task_failure,
)


def test_http_422_extracts_field_paths() -> None:
    body = {
        "detail": [
            {"loc": ["body", "components", 0, "image"], "msg": "field required", "type": "missing"},
            {"loc": ["body", "deployment_name"], "msg": "string too short", "type": "value_error"},
        ]
    }
    d = diagnose_http_error(422, body)
    assert d.fault is Fault.USER_INPUT
    assert d.exit_code == 1
    assert "components.0.image: field required" in d.details
    assert "deployment_name: string too short" in d.details
    # The 'body' prefix is stripped for readability.
    assert not any(line.startswith("body.") for line in d.details)


def test_http_401_is_auth() -> None:
    d = diagnose_http_error(401, {"detail": "invalid api key"})
    assert d.fault is Fault.AUTH
    assert d.source == "your credentials / permissions"
    assert d.exit_code == 1


def test_http_404_is_user_input() -> None:
    assert diagnose_http_error(404, {"detail": "not found"}).fault is Fault.USER_INPUT


def test_http_500_is_platform_and_retryable_exit_code() -> None:
    d = diagnose_http_error(500, "boom")
    assert d.fault is Fault.PLATFORM
    assert d.exit_code == 2
    assert "platform" in d.headline.lower()


def test_connection_failure_is_network() -> None:
    d = diagnose_http_error(0, "connection refused")
    assert d.fault is Fault.NETWORK
    assert d.exit_code == 2


def test_task_failure_component_imagepull_is_user_app() -> None:
    result = {
        "status": "failed",
        "processing": {
            "status": "failed",
            "component_failures": [
                {
                    "component": "web",
                    "failure_type": "ImagePull",
                    "message": "Back-off pulling image ghcr.io/org/web:bad",
                    "logs": ["Error: manifest unknown"],
                }
            ],
        },
    }
    d = diagnose_task_failure("deployment failed", result)
    assert d.fault is Fault.USER_APP
    assert "your application" in d.source
    assert any("web (ImagePull)" in line for line in d.details)
    assert any("manifest unknown" in line for line in d.details)


def test_task_failure_syncfailed_text_is_user_config() -> None:
    # No structured failures, but the message carries the backend's category vocabulary.
    d = diagnose_task_failure("git clone failed (SyncFailed)", {})
    assert d.fault is Fault.USER_CONFIG


def test_task_failure_unknown_stays_unknown() -> None:
    d = diagnose_task_failure("something odd happened", {})
    assert d.fault is Fault.UNKNOWN
    # UNKNOWN gets its own exit code: not "your fault" (1), not "safe to retry" (2).
    assert d.exit_code == 3
    # Points at the task, not at `zadctl logs`: that needs a deployment, and a task that
    # failed before one exists has none, so naming it sends the reader somewhere empty.
    assert "task" in " ".join(d.next_steps).lower()


def test_a_partly_finished_task_says_so_and_lists_what_landed() -> None:
    """'Failed' flatly sends people looking for a change that is already there."""
    subtasks = [
        {"name": "Component toevoegen", "status": "completed", "error": None},
        {"name": "Diensten en manifesten bijwerken", "status": "failed", "error": "mislukt"},
    ]
    d = diagnose_task_failure("Project processing failed", {}, "t-1", subtasks)
    flat = " ".join(d.details + d.next_steps)
    assert "part of the way" in d.headline
    assert "Component toevoegen" in flat
    assert "Diensten en manifesten bijwerken" in flat
    assert "t-1" in flat


def test_a_task_with_no_subtasks_still_gets_a_way_forward() -> None:
    d = diagnose_task_failure("boem", {}, "t-9")
    assert "zadctl task status t-9" in " ".join(d.next_steps)


def test_degraded_diagnoses_flags_warnings() -> None:
    diags = degraded_diagnoses({"status": "success", "warnings": ["deprecated field 'foo'"]})
    assert len(diags) == 1
    assert diags[0].fault is Fault.USER_CONFIG
    assert "deprecated field 'foo'" in diags[0].details


def test_degraded_diagnoses_flags_unhealthy_components() -> None:
    result = {
        "status": "success",
        "processing": {
            "status": "completed",
            "component_failures": [{"component": "web", "failure_type": "CrashLoop", "message": "exited 1"}],
        },
    }
    diags = degraded_diagnoses(result)
    assert len(diags) == 1
    assert diags[0].fault is Fault.USER_APP


def test_degraded_diagnoses_clean_result_is_empty() -> None:
    assert degraded_diagnoses({"status": "success"}) == []
    assert degraded_diagnoses(None) == []


def test_to_dict_is_machine_readable() -> None:
    d = diagnose_http_error(500, "boom")
    payload = d.to_dict()
    assert payload["fault"] == "Platform"
    assert payload["source"] == "ZAD platform"
    assert payload["status_code"] == 500
    assert set(payload) == {"fault", "source", "headline", "summary", "details", "next_steps", "status_code"}


def test_422_with_a_validation_report_names_the_failing_check():
    """`:validate-clone` says why in `validation.checks`, not in FastAPI's `detail`.

    Reading only `detail` left "Clone validation failed for acceptatie" on screen while
    the sentence that explains it sat unread in the same response body.
    """
    body = {
        "status": "invalid",
        "message": "Clone validation failed for acceptatie",
        "validation": {
            "passed": False,
            "checks": [
                {"name": "target_reachable", "status": "passed", "message": "ok"},
                {
                    "name": "clone_configuration",
                    "status": "failed",
                    "message": "Deployment 'acceptatie' has no clone-from configuration",
                },
            ],
        },
    }

    d = diagnose_http_error(422, body)

    assert d.details == ["clone_configuration: Deployment 'acceptatie' has no clone-from configuration"]
    assert d.fault is Fault.USER_INPUT


def test_a_fastapi_validation_array_still_wins():
    """The ordinary 422 shape must keep its field paths."""
    body = {"detail": [{"loc": ["body", "deploymentName"], "msg": "field required"}]}

    assert diagnose_http_error(422, body).details == ["deploymentName: field required"]


def test_409_names_what_still_uses_the_component():
    """The conflict body nests the reason one level down, and lists who blocks it.

    Read only as `body["detail"]` this is a dict, so the summary came out empty and the
    screen said "the resource is in a state that blocks this action" and nothing else.
    """
    body = {
        "detail": {
            "detail": "Component 'bijzaak' is in gebruik door: deployment 'productie'. "
            "Set confirm_in_use=true to remove those references along with it.",
            "used_by": [
                {"deployment": "productie", "component": None, "kind": "deployment", "label": "deployment 'productie'"}
            ],
        }
    }

    d = diagnose_http_error(409, body)

    assert d.summary is not None and "bijzaak" in d.summary
    assert d.details == ["deployment 'productie'"]


def test_a_plain_string_detail_is_unchanged():
    assert diagnose_http_error(404, {"detail": "Not Found"}).summary == "Not Found"


def test_a_conflict_with_references_does_not_say_wait():
    """Nothing settles here: the references have to go, or --force has to remove them."""
    body = {"detail": {"detail": "in gebruik", "used_by": [{"label": "deployment 'productie'"}]}}

    steps = " ".join(diagnose_http_error(409, body).next_steps)

    assert "--force" in steps
    assert "settle" not in steps


def test_a_conflict_without_references_still_says_wait():
    """A genuine state conflict is a different thing and keeps its own advice."""
    steps = " ".join(diagnose_http_error(409, {"detail": "Deployment is syncing"}).next_steps)

    assert "settles" in steps


def test_the_body_s_own_category_beats_the_status_code():
    """A restore into an unreachable target is a 500 by transport and a wrong value by cause.

    Without reading `error_category` this came out as Platform/exit 2, which tells a
    pipeline to retry; a hostname that does not resolve will not start resolving.
    """
    body = {"status": "failed", "message": "Restore pod failed", "error_category": "InvalidTarget"}

    d = diagnose_http_error(500, body)

    assert d.fault is Fault.USER_INPUT
    assert d.exit_code == 1
    assert any("target" in step.lower() for step in d.next_steps)


def test_an_unnamed_500_is_still_the_platform():
    """No category means we do not get to invent one."""
    d = diagnose_http_error(500, {"message": "boom"})

    assert d.fault is Fault.PLATFORM
    assert d.exit_code == 2


def test_a_subtask_says_what_it_acted_on():
    subtasks = [
        {"name": "Diensten bijwerken", "status": "failed", "error": "timeout", "subject": "web"},
        {"name": "Diensten bijwerken", "status": "completed", "subject": "worker"},
    ]

    d = diagnose_task_failure("mislukt", {}, "t", subtasks)

    assert any("Diensten bijwerken (web)" in line for line in d.details)


def test_an_explicit_unknown_is_not_the_platform():
    """ "Unknown" in the field is a statement, and a different one from leaving it out.

    Exit 2 tells CI to retry. When the API had a place to attribute the failure and wrote
    "I don't know" in it, retrying is not the conclusion; reading the logs is.
    """
    d = diagnose_http_error(500, {"status": "failed", "message": "boom", "error_category": "Unknown"})

    assert d.fault is Fault.UNKNOWN
    assert d.exit_code == 3
