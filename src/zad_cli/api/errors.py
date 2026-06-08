"""Clear, actionable diagnosis of API and task failures.

The goal is simple: tell the user *what went wrong and what to do next*. The
upstream API already carries the signal for that — ``ErrorCategory`` on cluster
errors, ``ComponentFailureInfo`` (with log tails) on failed deployment tasks,
``HTTPValidationError`` on bad input, ``error_type`` on task results — but a bare
``HTTP 500`` / ``Task failed`` string throws it away.

This module turns those raw signals into a :class:`Diagnosis`: a plain-language
headline, a neutral source label so you know where to look ("Source: your
application"), the concrete message, the backend's own explanation, and a next
step. The fault vocabulary is kept in lockstep with the OpenAPI spec by
``tests/test_spec_conformance.py`` (strict coupling: drift fails CI) while runtime
parsing degrades gracefully on unknown values (loose coupling).

We never claim more certainty than the data supports: when the API gives no
category, the fault is ``UNKNOWN`` and we point at the logs rather than guessing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from pydantic import ValidationError

from zad_cli.api.models import ErrorCategory, ProcessingStatus


class Fault(StrEnum):
    """Who/what a failure belongs to. Drives the source label, color and exit code."""

    USER_INPUT = "UserInput"  # the request you sent is wrong
    USER_APP = "UserApp"  # your container/workload failed at runtime
    USER_CONFIG = "UserConfig"  # your git config/manifests couldn't be applied
    AUTH = "Auth"  # your API key / permissions
    PLATFORM = "Platform"  # ZAD itself errored
    NETWORK = "Network"  # couldn't reach ZAD
    UNKNOWN = "Unknown"  # not enough signal to attribute honestly


# Neutral, source-labelled phrasing (no blame — just where the fault lives).
FAULT_SOURCE: dict[Fault, str] = {
    Fault.USER_INPUT: "your request",
    Fault.USER_APP: "your application (cluster runtime)",
    Fault.USER_CONFIG: "your configuration / git",
    Fault.AUTH: "your credentials / permissions",
    Fault.PLATFORM: "ZAD platform",
    Fault.NETWORK: "network / connectivity",
    Fault.UNKNOWN: "unknown — see logs",
}

# Rich color: user-fixable = yellow, escalate/investigate = red, auth = magenta.
FAULT_COLOR: dict[Fault, str] = {
    Fault.USER_INPUT: "yellow",
    Fault.USER_APP: "yellow",
    Fault.USER_CONFIG: "yellow",
    Fault.AUTH: "magenta",
    Fault.PLATFORM: "red",
    Fault.NETWORK: "red",
    Fault.UNKNOWN: "red",
}

# CI/CD exit codes: 1 = your fault (fix it), 2 = platform/transient (safe to retry).
FAULT_EXIT_CODE: dict[Fault, int] = {
    Fault.USER_INPUT: 1,
    Fault.USER_APP: 1,
    Fault.USER_CONFIG: 1,
    Fault.AUTH: 1,
    Fault.PLATFORM: 2,
    Fault.NETWORK: 2,
    Fault.UNKNOWN: 1,
}

# Which fault each cluster ErrorCategory implies. Keyed by ErrorCategory so the
# spec-conformance test can assert every upstream category is mapped here.
CATEGORY_FAULT: dict[ErrorCategory, Fault] = {
    ErrorCategory.IMAGE_PULL: Fault.USER_APP,
    ErrorCategory.CRASH_LOOP: Fault.USER_APP,
    ErrorCategory.OUT_OF_MEMORY: Fault.USER_APP,
    ErrorCategory.HEALTH_CHECK: Fault.USER_APP,
    ErrorCategory.SYNC_FAILED: Fault.USER_CONFIG,
    ErrorCategory.COMPARISON_ERROR: Fault.USER_CONFIG,
    ErrorCategory.UNKNOWN: Fault.UNKNOWN,
}

# Fallback next-step hint, used ONLY when the backend gave no explanation of its
# own. We always prefer the server's words over these.
CATEGORY_HINT: dict[ErrorCategory, str] = {
    ErrorCategory.IMAGE_PULL: "Check the image tag exists and the registry is reachable / credentials are set.",
    ErrorCategory.CRASH_LOOP: "The container starts then exits. Check `zad logs` for the crash reason.",
    ErrorCategory.OUT_OF_MEMORY: "The container exceeded its memory limit. Reduce usage or raise the limit.",
    ErrorCategory.HEALTH_CHECK: "The app started but its readiness/liveness probe never passed. Check the probe.",
    ErrorCategory.SYNC_FAILED: "ZAD could not sync your config from git. Check the repo, branch, and manifests.",
    ErrorCategory.COMPARISON_ERROR: "ZAD could not compare desired vs live state. Retry `zad deployment refresh`.",
    ErrorCategory.UNKNOWN: "",
}

# Unambiguous Kubernetes reason tokens we can map without guessing. Used only as
# a last resort when the API gives a raw message but no structured category.
_K8S_TOKEN_CATEGORY: dict[str, ErrorCategory] = {
    "imagepullbackoff": ErrorCategory.IMAGE_PULL,
    "errimagepull": ErrorCategory.IMAGE_PULL,
    "invalidimagename": ErrorCategory.IMAGE_PULL,
    "crashloopbackoff": ErrorCategory.CRASH_LOOP,
    "oomkilled": ErrorCategory.OUT_OF_MEMORY,
}

# HTTP status -> fault for the cases that aren't a simple 4xx/5xx split.
_HTTP_FAULT: dict[int, Fault] = {
    400: Fault.USER_INPUT,
    401: Fault.AUTH,
    403: Fault.AUTH,
    404: Fault.USER_INPUT,
    409: Fault.USER_INPUT,
    422: Fault.USER_INPUT,
}


@dataclass
class Diagnosis:
    """A structured, source-labelled explanation of a failure.

    ``details`` are concrete lines (validation errors, component failures, log
    tails); ``next_steps`` are actionable suggestions. ``summary`` is the raw
    upstream message when we have one.
    """

    fault: Fault
    headline: str
    summary: str | None = None
    details: list[str] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)
    status_code: int | None = None

    @property
    def source(self) -> str:
        return FAULT_SOURCE[self.fault]

    @property
    def color(self) -> str:
        return FAULT_COLOR[self.fault]

    @property
    def exit_code(self) -> int:
        return FAULT_EXIT_CODE[self.fault]

    def to_dict(self) -> dict:
        """Flat, machine-readable shape for `--output json` (CI/CD branch key: `fault`)."""
        return {
            "fault": self.fault.value,
            "source": self.source,
            "headline": self.headline,
            "summary": self.summary,
            "details": self.details,
            "next_steps": self.next_steps,
            "status_code": self.status_code,
        }


def category_of(value: str | None) -> ErrorCategory:
    """Coerce an arbitrary string to a known ErrorCategory (case-insensitive), else UNKNOWN.

    Loose coupling: an upstream category we don't know yet maps to UNKNOWN rather
    than raising.
    """
    if isinstance(value, str):
        for cat in ErrorCategory:
            if cat.value.lower() == value.lower():
                return cat
    return ErrorCategory.UNKNOWN


def _scan_category(text: str | None) -> ErrorCategory:
    """Best-effort category from raw text.

    Matches the backend's own ``ErrorCategory`` vocabulary (spec-derived) plus a
    few unambiguous Kubernetes reason tokens. Returns UNKNOWN rather than guessing
    when nothing matches.
    """
    if not text:
        return ErrorCategory.UNKNOWN
    low = text.lower().replace(" ", "")
    for token, cat in _K8S_TOKEN_CATEGORY.items():
        if token in low:
            return cat
    for cat in ErrorCategory:
        if cat is not ErrorCategory.UNKNOWN and cat.value.lower() in low:
            return cat
    return ErrorCategory.UNKNOWN


def _parse_processing(raw: object) -> ProcessingStatus | None:
    if not isinstance(raw, dict):
        return None
    try:
        return ProcessingStatus.model_validate(raw)
    except ValidationError:
        return None


def _format_validation(detail: object) -> list[str]:
    """Turn a FastAPI HTTPValidationError ``detail`` array into readable field lines."""
    if not isinstance(detail, list):
        return []
    lines: list[str] = []
    for item in detail:
        if not isinstance(item, dict):
            lines.append(str(item))
            continue
        loc = [str(p) for p in item.get("loc", [])]
        if loc and loc[0] in {"body", "query", "path", "header", "cookie"}:
            loc = loc[1:]
        field_path = ".".join(loc) or "(request)"
        lines.append(f"{field_path}: {item.get('msg', 'invalid value')}")
    return lines


def diagnose_http_error(status_code: int, body: object) -> Diagnosis:
    """Diagnose a failed HTTP response.

    ``status_code == 0`` means the request never reached ZAD (connection error).
    ``body`` may be a parsed dict, a raw string, or None.
    """
    if status_code == 0:
        return Diagnosis(
            fault=Fault.NETWORK,
            headline="Could not reach the ZAD API.",
            summary=str(body) if body else None,
            next_steps=[
                "Check your network/VPN and that --api-url is correct.",
                "If ZAD should be reachable, retry shortly (exit code 2 = transient).",
            ],
            status_code=0,
        )

    fault = _HTTP_FAULT.get(status_code)
    if fault is None:
        fault = (
            Fault.USER_INPUT if 400 <= status_code < 500 else Fault.PLATFORM if status_code >= 500 else Fault.UNKNOWN
        )

    body_dict = body if isinstance(body, dict) else None
    details: list[str] = []
    summary: str | None = None

    if status_code == 422 and body_dict is not None:
        details = _format_validation(body_dict.get("detail"))
    if body_dict is not None and not details:
        raw = body_dict.get("message") or body_dict.get("detail")
        summary = raw if isinstance(raw, str) else None
    elif isinstance(body, str) and body.strip():
        summary = body.strip()

    headline, next_steps = _http_headline(status_code, fault)
    return Diagnosis(
        fault=fault,
        headline=headline,
        summary=summary,
        details=details,
        next_steps=next_steps,
        status_code=status_code,
    )


def _http_headline(status_code: int, fault: Fault) -> tuple[str, list[str]]:
    if status_code in (401, 403):
        verb = "Authentication failed" if status_code == 401 else "Permission denied"
        return (
            f"{verb} (HTTP {status_code}).",
            ["Set a valid ZAD_API_KEY (or --api-key) with access to this project."],
        )
    if status_code == 404:
        return (
            "Not found (HTTP 404) — the resource you referenced doesn't exist.",
            ["Check the name/spelling and that it exists (e.g. `zad deployment list`)."],
        )
    if status_code == 409:
        return (
            "Conflict (HTTP 409) — the resource is in a state that blocks this action.",
            ["Check its current state, then retry once it settles."],
        )
    if status_code == 422:
        return (
            "Invalid request (HTTP 422) — the values you sent didn't pass validation.",
            ["Fix the field(s) listed above and retry."],
        )
    if fault is Fault.PLATFORM:
        return (
            f"ZAD platform error (HTTP {status_code}) — usually transient.",
            ["Retry shortly (exit code 2 = transient). If it persists, report it with the time of the call."],
        )
    return (f"Request rejected (HTTP {status_code}).", [])


def diagnose_task_failure(error_message: str | None, result: object) -> Diagnosis:
    """Diagnose a failed async task from its ``error_message`` and ``result`` payload."""
    result_dict = result if isinstance(result, dict) else {}
    processing = _parse_processing(result_dict.get("processing"))
    failures = (processing.component_failures if processing else None) or []

    details: list[str] = []
    next_steps: list[str] = []

    if failures:
        cats: list[ErrorCategory] = []
        for fail in failures:
            cat = category_of(fail.failure_type)
            cats.append(cat)
            label = f"{fail.component} ({fail.failure_type}): {fail.message}"
            details.append(label)
            for line in (fail.logs or [])[:5]:
                details.append(f"    {line}")
            hint = CATEGORY_HINT.get(cat)
            if hint and hint not in next_steps:
                next_steps.append(hint)
        known = [c for c in cats if c is not ErrorCategory.UNKNOWN]
        # A component concretely failed at runtime → it's the app, even if the
        # exact category is unrecognised.
        fault = CATEGORY_FAULT[known[0]] if known else Fault.USER_APP
    else:
        # No structured failures: fall back to a category scan of the raw text.
        text = " ".join(
            t for t in [error_message, processing.error if processing else None, result_dict.get("error")] if t
        )
        cat = _scan_category(text)
        fault = CATEGORY_FAULT[cat] if cat is not ErrorCategory.UNKNOWN else Fault.UNKNOWN
        hint = CATEGORY_HINT.get(cat)
        if hint:
            next_steps.append(hint)

    summary = (
        error_message or (processing.error if processing else None) or (processing.message if processing else None)
    )

    if fault is Fault.USER_APP:
        headline = "Your application didn't start on the cluster (the deploy reached the cluster; the workload failed)."
        next_steps.append("Inspect `zad logs -d <deployment>` and `zad deployment describe <deployment>`.")
    elif fault is Fault.USER_CONFIG:
        headline = "Your configuration couldn't be applied."
        next_steps.append("Fix your git repo/manifests, then `zad deployment refresh`.")
    else:
        headline = "The operation failed. Check the details below for the cause."
        next_steps.append("Run `zad task status <id>` and `zad logs` for the full output.")

    return Diagnosis(fault=fault, headline=headline, summary=summary, details=details, next_steps=next_steps)


def degraded_diagnoses(result: object) -> list[Diagnosis]:
    """Inspect a *successful* task result for degraded state worth surfacing.

    Returns an empty list for a genuinely clean result. Catches the
    "looks like it worked but your app is actually unhealthy" case: component
    failures, ``warnings``, or a ``partial``/``degraded`` status on an otherwise
    200/completed response.
    """
    result_dict = result if isinstance(result, dict) else {}
    out: list[Diagnosis] = []

    processing = _parse_processing(result_dict.get("processing"))
    if processing and processing.component_failures:
        diag = diagnose_task_failure(None, result_dict)
        diag.headline = "The operation succeeded, but some components are unhealthy."
        out.append(diag)

    warnings = result_dict.get("warnings") or []
    if warnings:
        out.append(
            Diagnosis(
                fault=Fault.USER_CONFIG,
                headline="The operation succeeded with warnings.",
                details=[str(w) for w in warnings],
                next_steps=["Review the warnings above — they usually point at your configuration."],
            )
        )

    status = str(result_dict.get("status", "")).lower()
    if status in {"partial", "degraded"} and not out:
        out.append(
            Diagnosis(
                fault=Fault.UNKNOWN,
                headline=f"The operation finished with status '{result_dict.get('status')}'.",
                summary=result_dict.get("message") or None,
                next_steps=["Run `zad deployment describe <name>` to see the current state."],
            )
        )

    return out
