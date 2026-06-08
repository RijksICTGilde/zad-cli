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
    assert d.exit_code == 1
    assert "logs" in " ".join(d.next_steps).lower()


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
