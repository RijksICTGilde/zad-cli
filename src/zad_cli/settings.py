"""Settings resolved from CLI flags > environment > defaults.

Precedence (highest wins):
  1. CLI flags (--api-key, --api-url, -p, -o, --rollout/--no-rollout)
  2. Exported environment variables
  3. The `.env.zadctl` in the working directory, which is where the CLI writes
  4. Built-in defaults

The environment and the file are separate layers on purpose: an exported variable is
someone being explicit right now, the file is what was remembered earlier, and telling
them apart is what makes ``zadctl config list`` able to explain itself.

Every setting also records *where* its value came from, in ``Settings.sources``, so
``zadctl config list`` can say why the CLI behaves the way it does instead of only what it
is doing.

The file is read here rather than pushed into os.environ, so the two stay
distinguishable.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field

from zad_cli import envfile

__all__ = [
    "DEFAULT_API_URL",
    "DEFAULT_KEYCLOAK_CLIENT_ID",
    "DEFAULT_KEYCLOAK_REALM",
    "DEFAULT_KEYCLOAK_URL",
    "SETTING_DOCS",
    "VALID_OUTPUT_FORMATS",
    "InvalidSettingError",
    "SettingDoc",
    "Settings",
    "parse_bool",
]

DEFAULT_API_URL = "https://operations-manager.rig.prd1.gn2.quattro.rijksapps.nl/api"

# The Keycloak `zadctl login` talks to. Three values, because only the first one moves when
# you point the CLI at a test realm; deriving the host from the API URL was a guess, and
# for production it guessed wrong.
DEFAULT_KEYCLOAK_URL = "https://keycloak.rijksapp.nl"
DEFAULT_KEYCLOAK_REALM = "rig-platform"
DEFAULT_KEYCLOAK_CLIENT_ID = "zad-cli"

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}

# The formats the formatter renders. Shared with config.py, which refuses the rest at
# write time so a typo cannot sit in the file waiting to break a later run.
VALID_TABLE_STYLES = frozenset({"lines", "ascii", "plain"})
VALID_OUTPUT_FORMATS = frozenset({"table", "json", "yaml"})


class InvalidSettingError(ValueError):
    """A setting was given a value it cannot have."""


def parse_bool(raw: object, *, name: str) -> bool:
    """Read a boolean the way a person writes one in a `.env.zadctl`.

    Accepts true/false, 1/0, yes/no and on/off, in any case. A real bool passes through,
    so a caller that already parsed one does not have to spell it back out.
    """
    if isinstance(raw, bool):
        return raw
    value = str(raw).strip().lower()
    if value in _TRUE:
        return True
    if value in _FALSE:
        return False
    raise InvalidSettingError(f"{name} must be true or false, got: {raw}")


def _env(name: str) -> str | None:
    """One variable: exported first, then the .env.zadctl in this directory."""
    return os.environ.get(name) or envfile.get(name) or None


def _int_env(name: str, default: int) -> int:
    """Read an integer from an environment variable with a clear error on invalid values."""
    raw = _env(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        print(f"Error: {name} must be an integer, got: {raw}", file=sys.stderr)
        raise SystemExit(1) from None


def _bool_setting(var: str, *, flag: bool | None, default: bool) -> tuple[bool, str]:
    """A boolean from flag > exported variable > .env.zadctl > default, with where it came from.

    Presence, not truth: a value of false is the case these settings exist for, and
    testing the layer for truth would drop it straight through to the default.
    """
    if flag is not None:
        return flag, "flag"
    exported = os.environ.get(var)
    if exported is not None and exported != "":
        return parse_bool(exported, name=var), "env"
    from_file = envfile.get(var)
    if from_file:
        return parse_bool(from_file, name=var), "envfile"
    return default, "default"


def _first(*candidates: tuple[str, object | None]) -> tuple[object | None, str]:
    """The first candidate that has a value, and the name of where it came from."""
    for source, value in candidates:
        if value is not None and value != "":
            return value, source
    return None, "default"


@dataclass
class Settings:
    """Resolved settings."""

    api_url: str
    api_key: str
    project_id: str
    output_format: str
    verbose: bool = False
    table_style: str = "ascii"
    rollout: bool = True
    assume_yes: bool = False
    keycloak_url: str = ""
    keycloak_realm: str = ""
    keycloak_client_id: str = ""
    sso_issuer: str = ""
    task_timeout: int = 300
    task_poll_interval: int = 3
    max_retries: int = 3
    retry_delay: int = 2
    # setting name -> "flag", "env", "envfile", "composed" or "default"
    sources: dict[str, str] = field(default_factory=dict)

    @classmethod
    def resolve(
        cls,
        *,
        api_url: str | None = None,
        api_key: str | None = None,
        project_id: str | None = None,
        output_format: str | None = None,
        table_style: str | None = None,
        verbose: bool = False,
        rollout: bool | None = None,
        assume_yes: bool | None = None,
        keycloak_url: str | None = None,
        keycloak_realm: str | None = None,
        keycloak_client_id: str | None = None,
    ) -> Settings:
        resolved_project, project_source = _first(
            ("flag", project_id),
            ("env", os.environ.get("ZAD_PROJECT_ID")),
            ("envfile", envfile.get("ZAD_PROJECT_ID")),
        )
        project = str(resolved_project or "")

        resolved_key, key_source = _first(
            ("flag", api_key),
            ("env", os.environ.get("ZAD_API_KEY")),
            ("envfile", envfile.get("ZAD_API_KEY")),
        )

        resolved_url, url_source = _first(
            ("flag", api_url),
            ("env", os.environ.get("ZAD_API_URL")),
            ("envfile", envfile.get("ZAD_API_URL")),
        )

        resolved_output, output_source = _first(
            ("flag", output_format),
            ("env", os.environ.get("ZAD_OUTPUT_FORMAT")),
            ("envfile", envfile.get("ZAD_OUTPUT_FORMAT")),
        )
        if resolved_output is not None and str(resolved_output).lower() not in VALID_OUTPUT_FORMATS:
            raise InvalidSettingError(
                f"output must be one of {', '.join(sorted(VALID_OUTPUT_FORMATS))}, got: {resolved_output}"
            )

        resolved_style, style_source = _first(
            ("flag", table_style),
            ("env", os.environ.get("ZAD_TABLE_STYLE")),
            ("envfile", envfile.get("ZAD_TABLE_STYLE")),
        )
        if resolved_style is not None and str(resolved_style).lower() not in VALID_TABLE_STYLES:
            raise InvalidSettingError(
                f"table_style must be one of {', '.join(sorted(VALID_TABLE_STYLES))}, got: {resolved_style}"
            )

        # bool | None, not bool: "the user typed --rollout" and "nobody said anything"
        # have to stay distinguishable, or the flag would always beat the file.
        env_rollout = os.environ.get("ZAD_ROLLOUT")
        file_rollout = envfile.get("ZAD_ROLLOUT")
        try:
            if rollout is not None:
                resolved_rollout, rollout_source = rollout, "flag"
            # Presence, not truth: ZAD_ROLLOUT=false is the one case this setting exists
            # for, and testing it for truth would drop it straight through to the default.
            elif env_rollout is not None and env_rollout != "":
                resolved_rollout, rollout_source = parse_bool(env_rollout, name="ZAD_ROLLOUT"), "env"
            elif file_rollout:
                resolved_rollout, rollout_source = parse_bool(file_rollout, name="ZAD_ROLLOUT"), "envfile"
            else:
                resolved_rollout, rollout_source = True, "default"
        except InvalidSettingError as e:
            print(f"Error: {e}", file=sys.stderr)
            raise SystemExit(1) from None

        # Confirmation is a setting for the same reason rollout is: answering the same
        # obvious question every run is not a safety net, it is noise that trains people
        # to type -y without reading.
        try:
            resolved_yes, yes_source = _bool_setting("ZAD_YES", flag=assume_yes, default=False)
        except InvalidSettingError as e:
            print(f"Error: {e}", file=sys.stderr)
            raise SystemExit(1) from None

        # Three settings, not one issuer URL: the base URL is what moves when you point
        # the CLI at another Keycloak, and having to retype the realm and the client to
        # do it is how those two end up wrong.
        resolved_kc_url, kc_url_source = _first(
            ("flag", keycloak_url),
            ("env", os.environ.get("ZAD_KEYCLOAK_URL")),
            ("envfile", envfile.get("ZAD_KEYCLOAK_URL")),
        )
        resolved_kc_realm, kc_realm_source = _first(
            ("flag", keycloak_realm),
            ("env", os.environ.get("ZAD_KEYCLOAK_REALM")),
            ("envfile", envfile.get("ZAD_KEYCLOAK_REALM")),
        )
        resolved_kc_client, kc_client_source = _first(
            ("flag", keycloak_client_id),
            # ZAD_SSO_CLIENT_ID predates the split and keeps working; same layer, first say.
            ("env", os.environ.get("ZAD_SSO_CLIENT_ID") or os.environ.get("ZAD_KEYCLOAK_CLIENT_ID")),
            ("envfile", envfile.get("ZAD_SSO_CLIENT_ID") or envfile.get("ZAD_KEYCLOAK_CLIENT_ID")),
        )
        kc_url = str(resolved_kc_url or DEFAULT_KEYCLOAK_URL).rstrip("/")
        kc_realm = str(resolved_kc_realm or DEFAULT_KEYCLOAK_REALM)
        kc_client = str(resolved_kc_client or DEFAULT_KEYCLOAK_CLIENT_ID)

        # ZAD_SSO_ISSUER hands over a full issuer URL and skips the composition entirely,
        # for a realm that is not laid out as {base}/realms/{realm}.
        issuer_override = _env("ZAD_SSO_ISSUER")
        if issuer_override:
            sso_issuer, issuer_source = issuer_override.rstrip("/"), "env"
        else:
            sso_issuer, issuer_source = f"{kc_url}/realms/{kc_realm}", "composed"

        return cls(
            api_url=str(resolved_url or DEFAULT_API_URL),
            api_key=str(resolved_key or ""),
            project_id=project,
            output_format=str(resolved_output or "table"),
            table_style=str(resolved_style or "ascii").lower(),
            verbose=verbose,
            rollout=resolved_rollout,
            assume_yes=resolved_yes,
            keycloak_url=kc_url,
            keycloak_realm=kc_realm,
            keycloak_client_id=kc_client,
            sso_issuer=sso_issuer,
            task_timeout=_int_env("ZAD_TASK_TIMEOUT", 300),
            task_poll_interval=_int_env("ZAD_TASK_POLL_INTERVAL", 3),
            max_retries=_int_env("ZAD_MAX_RETRIES", 3),
            retry_delay=_int_env("ZAD_RETRY_DELAY", 2),
            sources={
                "api_url": url_source,
                "api_key": key_source,
                "project": project_source,
                "output": output_source,
                "table_style": style_source,
                "rollout": rollout_source,
                "yes": yes_source,
                "keycloak_url": kc_url_source,
                "keycloak_realm": kc_realm_source,
                "keycloak_client_id": kc_client_source,
                "sso_issuer": issuer_source,
            },
        )


@dataclass(frozen=True)
class SettingDoc:
    """One setting, and the places it can come from.

    The resolution above is code; this is the same thing said once, in the order the
    layers win: flag, exported variable, the `.env.zadctl` in the working directory, default.
    `zadctl guide` reads it instead of restating it, and ``tests/test_guide.py`` fails the
    build when a ``ZAD_*`` variable appears in this module without a row here: a setting
    nobody can find is a setting nobody uses.
    """

    name: str
    description: str
    flag: str = ""
    env: tuple[str, ...] = ()
    config_key: str = ""
    default: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "setting": self.name,
            "description": self.description,
            "flag": self.flag,
            "env": list(self.env),
            "config_key": self.config_key,
            "default": self.default,
        }


SETTING_DOCS: tuple[SettingDoc, ...] = (
    SettingDoc(
        name="api_url",
        description="Operations Manager API base URL.",
        flag="--api-url",
        env=("ZAD_API_URL",),
        config_key="api_url",
        default=DEFAULT_API_URL,
    ),
    SettingDoc(
        name="api_key",
        description="Project API key, sent as X-API-Key on every project-scoped call.",
        flag="--api-key",
        env=("ZAD_API_KEY",),
        default="the active project's key from the credentials store",
    ),
    SettingDoc(
        name="project",
        description="Which project the command acts on.",
        flag="-p / --project",
        env=("ZAD_PROJECT_ID",),
        default="the active project set by `zadctl project use`",
    ),
    SettingDoc(
        name="output",
        description="Output format: table, json or yaml.",
        flag="-o / --output (--json, --yaml)",
        env=("ZAD_OUTPUT_FORMAT",),
        config_key="output",
        default="table",
    ),
    SettingDoc(
        name="table_style",
        description="How tables are drawn: ascii, lines or plain. A matter of taste, so it is yours to set.",
        env=("ZAD_TABLE_STYLE",),
        config_key="table_style",
        default="ascii",
    ),
    SettingDoc(
        name="rollout",
        description="Roll a saved change out to the cluster.",
        flag="--rollout / --no-rollout",
        env=("ZAD_ROLLOUT",),
        config_key="rollout",
        default="true",
    ),
    SettingDoc(
        name="yes",
        description=(
            "Answer confirmation prompts with yes, so the obvious is not asked every run. "
            "The per-command --yes/-y does the same for one call."
        ),
        env=("ZAD_YES",),
        config_key="yes",
        default="false (ask)",
    ),
    SettingDoc(
        name="keycloak_url",
        description="Keycloak base URL `zadctl login` signs in against.",
        flag="--keycloak-url",
        env=("ZAD_KEYCLOAK_URL",),
        config_key="keycloak_url",
        default=DEFAULT_KEYCLOAK_URL,
    ),
    SettingDoc(
        name="keycloak_realm",
        description="Keycloak realm `zadctl login` signs in against.",
        flag="--keycloak-realm",
        env=("ZAD_KEYCLOAK_REALM",),
        config_key="keycloak_realm",
        default=DEFAULT_KEYCLOAK_REALM,
    ),
    SettingDoc(
        name="keycloak_client_id",
        description="OAuth client `zadctl login` uses.",
        flag="--keycloak-client-id",
        env=("ZAD_SSO_CLIENT_ID", "ZAD_KEYCLOAK_CLIENT_ID"),
        config_key="keycloak_client_id",
        default=DEFAULT_KEYCLOAK_CLIENT_ID,
    ),
    SettingDoc(
        name="sso_issuer",
        description="OIDC issuer. Set it only for a realm not laid out as {url}/realms/{realm}.",
        env=("ZAD_SSO_ISSUER",),
        default="composed from keycloak_url + keycloak_realm",
    ),
    SettingDoc(
        name="task_timeout",
        description="Seconds to wait for an async task before giving up (the task keeps running).",
        env=("ZAD_TASK_TIMEOUT",),
        default="300",
    ),
    SettingDoc(
        name="task_poll_interval",
        description="Seconds between polls of /api/tasks/{id}.",
        env=("ZAD_TASK_POLL_INTERVAL",),
        default="3",
    ),
    SettingDoc(
        name="max_retries",
        description="How often a failed request is retried.",
        env=("ZAD_MAX_RETRIES",),
        default="3",
    ),
    SettingDoc(
        name="retry_delay",
        description="Seconds between retries.",
        env=("ZAD_RETRY_DELAY",),
        default="2",
    ),
)
