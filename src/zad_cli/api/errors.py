"""Clear, actionable diagnosis of API and task failures.

The goal is simple: tell the user *what went wrong and what to do next*. The
upstream API already carries the signal for that (``ErrorCategory`` on cluster
errors, ``ComponentFailureInfo`` with log tails on failed deployment tasks,
``HTTPValidationError`` on bad input, ``error_type`` on task results), but a bare
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


# Neutral, source-labelled phrasing (no blame, just where the fault lives).
FAULT_SOURCE: dict[Fault, str] = {
    Fault.USER_INPUT: "your request",
    Fault.USER_APP: "your application (cluster runtime)",
    Fault.USER_CONFIG: "your configuration / git",
    Fault.AUTH: "your credentials / permissions",
    Fault.PLATFORM: "ZAD platform",
    Fault.NETWORK: "network / connectivity",
    Fault.UNKNOWN: "not attributable from the response",
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

# CI/CD exit codes: 1 = your fault (fix it), 2 = platform/transient (safe to retry),
# 3 = unattributable. UNKNOWN gets its own code rather than claiming "your fault"
# (1) or "safe to retry" (2) when the API gave us no signal to attribute the failure.
FAULT_EXIT_CODE: dict[Fault, int] = {
    Fault.USER_INPUT: 1,
    Fault.USER_APP: 1,
    Fault.USER_CONFIG: 1,
    Fault.AUTH: 1,
    Fault.PLATFORM: 2,
    Fault.NETWORK: 2,
    Fault.UNKNOWN: 3,
}

# Which fault each cluster ErrorCategory implies. Keyed by ErrorCategory so the
# spec-conformance test can assert every upstream category is mapped here.
CATEGORY_FAULT: dict[ErrorCategory, Fault] = {
    ErrorCategory.IMAGE_PULL: Fault.USER_APP,
    ErrorCategory.CRASH_LOOP: Fault.USER_APP,
    # Not the platform: the destination came from the caller, so a target that does not
    # resolve or refuses the connection is a wrong value in the command. Without this it
    # arrived as a bare 500 and CI was told to retry a typo until it gave up.
    ErrorCategory.INVALID_TARGET: Fault.USER_INPUT,
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
    ErrorCategory.CRASH_LOOP: "The container starts then exits. Check `zadctl logs` for the crash reason.",
    ErrorCategory.INVALID_TARGET: (
        "The target you gave could not be used: check the host, the name and the credentials. "
        "Leave the --target-* options out to restore into the project's own database or bucket."
    ),
    ErrorCategory.OUT_OF_MEMORY: "The container exceeded its memory limit. Reduce usage or raise the limit.",
    ErrorCategory.HEALTH_CHECK: "The app started but its readiness/liveness probe never passed. Check the probe.",
    ErrorCategory.SYNC_FAILED: "ZAD could not sync your config from git. Check the repo, branch, and manifests.",
    ErrorCategory.COMPARISON_ERROR: "ZAD could not compare desired vs live state. Retry `zadctl deployment refresh`.",
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


def _format_checks(validation: object) -> list[str]:
    """Turn a ``validation.checks`` array into readable lines.

    A second shape of 422, and the one that carries the actual reason. ``:validate-clone``
    answers with ``{"validation": {"passed": false, "checks": [{"name": ..., "status":
    "failed", "message": "Deployment 'x' has no clone-from configuration"}]}}``. Reading
    only FastAPI's ``detail`` array left "Clone validation failed" on screen while the
    sentence that says why sat unread in the same response.

    Only failing checks are shown: on a validation that fails for one reason out of eight,
    the seven that passed are noise in front of the one that did not.
    """
    if not isinstance(validation, dict):
        return []
    checks = validation.get("checks")
    if not isinstance(checks, list):
        return []
    lines: list[str] = []
    for check in checks:
        if not isinstance(check, dict) or check.get("status") == "passed":
            continue
        message = check.get("message") or check.get("status") or "failed"
        name = check.get("name")
        lines.append(f"{name}: {message}" if name else str(message))
    return lines


def _format_used_by(used_by: object) -> list[str]:
    """Turn a conflict's ``used_by`` array into lines naming what blocks the action.

    The API already writes a ``label`` per entry ("deployment 'productie'"), so this
    prefers that over rebuilding the sentence from the parts and getting the wording
    subtly different from what the same API says elsewhere.
    """
    if not isinstance(used_by, list):
        return []
    lines: list[str] = []
    for item in used_by:
        if not isinstance(item, dict):
            lines.append(str(item))
            continue
        label = item.get("label")
        if isinstance(label, str) and label:
            lines.append(label)
            continue
        kind, name = item.get("kind"), item.get("deployment") or item.get("component")
        lines.append(f"{kind} '{name}'" if kind and name else str(item))
    return lines


def diagnose_http_error(status_code: int, body: object, *, auth: str | None = None) -> Diagnosis:
    """Diagnose a failed HTTP response.

    ``status_code == 0`` means the request never reached ZAD (connection error).
    ``body`` may be a parsed dict, a raw string, or None.
    ``auth`` is which credential the request carried (``"bearer"`` or ``"api-key"``), so a
    401 can name the one that actually needs fixing.
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
        details = _format_validation(body_dict.get("detail")) or _format_checks(body_dict.get("validation"))
    if body_dict is not None and not details:
        raw = body_dict.get("message") or body_dict.get("detail")
        # `detail` is not always a string. A 409 from `component delete` nests
        # {"detail": {"detail": "<why>", "used_by": [...]}}, and reading only the outer
        # layer left "the resource is in a state that blocks this action" on screen while
        # the sentence naming what blocks it sat one level down in the same body.
        if isinstance(raw, dict):
            inner = raw.get("detail") or raw.get("message")
            summary = inner if isinstance(inner, str) else None
            details = _format_used_by(raw.get("used_by"))
        else:
            summary = raw if isinstance(raw, str) else None
    elif isinstance(body, str) and body.strip():
        summary = body.strip()

    # The body may name the category itself, and then it beats anything the status code
    # implies. A restore into an unreachable target is a 500 by transport and a wrong value
    # by cause: without this it came out as "platform, retry" and a pipeline would repeat a
    # typo until it ran out of attempts.
    raw_category = body_dict.get("error_category") if body_dict else None
    stated = category_of(raw_category)
    if stated is not ErrorCategory.UNKNOWN:
        fault = CATEGORY_FAULT[stated]
    elif raw_category:
        # Said out loud, not merely absent: the API had a place to attribute this and put
        # "Unknown" in it. Calling that the platform's fault would tell a pipeline to retry
        # something nobody has established is retryable, so we say what the API said.
        fault = Fault.UNKNOWN

    headline, next_steps = _http_headline(status_code, fault, auth)
    hint = CATEGORY_HINT.get(stated)
    if hint:
        next_steps = [hint, *next_steps]
    # A conflict that names what uses the resource is not a conflict that passes: waiting
    # for it to settle is the one thing that cannot work. `used_by` is data, not wording,
    # so keying on it says the right thing without matching on a sentence that may change.
    if status_code == 409 and details:
        next_steps = [
            "Remove the references listed above first, or pass --force to delete them along with it.",
        ]
    return Diagnosis(
        fault=fault,
        headline=headline,
        summary=summary,
        details=details,
        next_steps=next_steps,
        status_code=status_code,
    )


def _http_headline(status_code: int, fault: Fault, auth: str | None = None) -> tuple[str, list[str]]:
    if status_code in (401, 403):
        verb = "Authentication failed" if status_code == 401 else "Permission denied"
        # Two credentials reach this API, and pointing at the wrong one sends people to
        # check a key that had nothing to do with the call. `project list` and
        # `project create` sign in as you; everything else presents the project's key.
        if auth == "bearer":
            steps = [
                "Run `zadctl login`: the SSO token is missing or no longer valid.",
                "In CI, set ZAD_SSO_TOKEN to a token obtained elsewhere.",
            ]
        else:
            steps = ["Set a valid ZAD_API_KEY (or --api-key) with access to this project."]
        return (f"{verb} (HTTP {status_code}).", steps)
    if status_code == 404:
        return (
            "Not found (HTTP 404): the resource you referenced doesn't exist.",
            ["Check the name/spelling and that it exists (e.g. `zadctl deployment list`)."],
        )
    if status_code == 409:
        return (
            "Conflict (HTTP 409): the resource is in a state that blocks this action.",
            ["Check its current state, then retry once it settles."],
        )
    if status_code == 422:
        return (
            "Invalid request (HTTP 422): the values you sent didn't pass validation.",
            ["Fix the field(s) listed above and retry."],
        )
    if fault is Fault.PLATFORM:
        return (
            f"ZAD platform error (HTTP {status_code}), usually transient.",
            ["Retry shortly (exit code 2 = transient). If it persists, report it with the time of the call."],
        )
    return (f"Request rejected (HTTP {status_code}).", [])


def result_failure(result: object) -> str | None:
    """The error a *completed* task reports inside its own result, if it reports one.

    A task can finish cleanly and still carry an application-level refusal: the run was
    fine, the thing it was asked to do was not. Reading only the task status therefore
    calls that a success, renders the refusal as if it were data, and exits zero.
    """
    if not isinstance(result, dict):
        return None
    if str(result.get("status", "")).lower() not in ("failed", "error"):
        return None
    error = result.get("error") or result.get("message") or result.get("detail")
    return str(error) if error else "The operation was refused, without saying why."


def _subtask_lines(subtasks: object) -> tuple[list[str], list[str]]:
    """The steps that failed and the steps that got through, in the order they ran.

    This is where the answer usually is: a task reports one flat message, but its subtasks
    say which step broke and, just as importantly, which ones already happened. "Adding the
    component succeeded, rolling it out did not" is a different situation from "nothing
    happened", and the flat message cannot tell them apart.
    """
    failed: list[str] = []
    done: list[str] = []
    if not isinstance(subtasks, list):
        return failed, done
    for item in subtasks:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "step")
        # `subject` says what the step acted on. "Diensten bijwerken" twice in a row is two
        # steps you cannot tell apart; with the subject it is two components by name.
        subject = item.get("subject")
        if subject:
            name = f"{name} ({subject})"
        if str(item.get("status", "")).lower() in ("failed", "error"):
            error = item.get("error")
            failed.append(f"{name}: {error}" if error else name)
        elif str(item.get("status", "")).lower() == "completed":
            done.append(name)
    return failed, done


def diagnose_task_failure(
    error_message: str | None,
    result: object,
    task_id: str | None = None,
    subtasks: object = None,
) -> Diagnosis:
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
    error_type = result_dict.get("error_type")
    if error_type and str(error_type) not in " ".join(details):
        details.append(f"error_type: {error_type}")

    failed_steps, done_steps = _subtask_lines(subtasks)
    for line in failed_steps:
        details.append(f"failed: {line}")
    if done_steps:
        details.append("completed: " + ", ".join(done_steps))

    if fault is Fault.USER_APP:
        headline = "Your application didn't start on the cluster (the deploy reached the cluster; the workload failed)."
        next_steps.append("Inspect `zadctl logs -d <deployment>` and `zadctl deployment describe <deployment>`.")
    elif fault is Fault.USER_CONFIG:
        headline = "Your configuration couldn't be applied."
        next_steps.append("Fix your git repo/manifests, then `zadctl deployment refresh`.")
    elif failed_steps and done_steps:
        # Partly through is its own situation: something did land, and saying "failed"
        # flatly sends people looking for a change that is actually already there.
        headline = "The operation only got part of the way: some steps succeeded, a later one failed."
        next_steps.append("What already landed is listed under 'completed'; do not redo it blindly.")
        if any("manifest" in line.lower() or "processing" in line.lower() for line in failed_steps):
            # The write landed and the rollout did not, which is what a refresh retries.
            next_steps.append("Retry the rollout with `zadctl project refresh`, then `zadctl project status`.")
    else:
        headline = "The operation failed. Check the details below for the cause."

    # Every task failure ends with a way to see the steps. `zadctl logs` is deliberately not
    # suggested here: it needs a deployment, and a task that failed before one exists has
    # no logs to show, so naming it sends the reader somewhere empty.
    next_steps.append(
        f"See every step with `zadctl task status {task_id}`."
        if task_id
        else "Find the task with `zadctl task list`, then `zadctl task status <id>`."
    )

    return Diagnosis(fault=fault, headline=headline, summary=summary, details=details, next_steps=next_steps)


def superseded_note(result: object) -> str | None:
    """What to say when a task handed its rollout over to a newer one.

    The API completes such a task rather than failing it, with `status: superseded` in the
    result, and its own comment says why: "the project file was already committed, and a
    newer task whose scope covers this one will reprocess from that state." Printed bare,
    that word reads like a failure -- a practice run reported it as one, twice, while every
    change had in fact been saved.

    Deliberately not a Diagnosis: a diagnosis becomes a warning, and `--strict` turns
    warnings into a non-zero exit. Failing a build over a successful hand-over would be
    worse than the confusing word this replaces.
    """
    if not isinstance(result, dict):
        return None
    if str(result.get("status", "")).lower() != "superseded":
        return None
    return (
        "Saved. A newer task covering this change took over the rollout, so this one stopped "
        "waiting -- a hand-over, not a failure. Watch it with `zadctl project pending`."
    )


def approval_notices(result: object) -> list[dict[str, str]]:
    """Approvals this deployment asked for and has not been given.

    The counterpart of `pending_rollout`, in the API's own words: that says a saved change
    is not on the cluster yet, this says a deployment is waiting on an administrator's
    judgement. Domains and subdomains are on request, so a write that claims one files the
    request -- and without this, "no ingress appeared" is the first anyone hears of it.

    Nothing here interprets the notice. The API sends `label`, `subject`, `status` and a
    `text` that says what it means for this deployment "in gewone taal", so this hands them
    on. In particular it does not branch on `status`: the three values it can hold live in
    a description rather than in an `enum`, and a CLI that hardcodes strings the spec does
    not promise is a CLI that goes quietly wrong when a fourth one appears.
    """
    items = result.get("approvals") if isinstance(result, dict) else None
    if not isinstance(items, list):
        return []
    return [notice for notice in items if isinstance(notice, dict) and notice.get("text")]


# The one status of an approval that a pipeline should fall over: an administrator looked at
# the request and said no, so what you asked for is not coming. `requested` is the ordinary
# case on a first write and must not fail anything.
#
# Naming a value here is safe only because the platform made `status` a real enum, and it
# said why in the schema: "een pijplijn hoort te falen op een AFGEWEZEN aanvraag en te
# wachten op een LOPENDE". `tests/test_spec_conformance.py` pins that set, so a fourth value
# arrives as a red test rather than as silence.
_REFUSED = "denied"


def approval_diagnoses(result: object) -> list[Diagnosis]:
    """Approvals that were refused, as warnings `--strict` can fail a build on.

    A refused domain does not stop a deployment: it publishes on the cluster's own address
    instead, healthy and answering, on a name nobody asked for. That is exactly the state
    that should not pass a pipeline quietly.
    """
    out = []
    for notice in approval_notices(result):
        if str(notice.get("status", "")).lower() != _REFUSED:
            continue
        subject = " - ".join(part for part in (notice.get("label"), notice.get("subject")) if part)
        out.append(
            Diagnosis(
                fault=Fault.USER_INPUT,
                headline=f"Refused: {subject or notice.get('service', 'approval')}",
                summary=str(notice.get("text") or ""),
                details=[str(notice["message"])] if notice.get("message") else [],
                next_steps=["Ask the administrator who decided, or claim something you may have."],
            )
        )
    return out


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
                next_steps=["Review the warnings above; they usually point at your configuration."],
            )
        )

    status = str(result_dict.get("status", "")).lower()
    if status in {"partial", "degraded"} and not out:
        out.append(
            Diagnosis(
                fault=Fault.UNKNOWN,
                headline=f"The operation finished with status '{result_dict.get('status')}'.",
                summary=result_dict.get("message") or None,
                next_steps=["Run `zadctl deployment describe <name>` to see the current state."],
            )
        )

    return out
