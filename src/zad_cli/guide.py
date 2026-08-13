"""One call that explains the whole CLI: `zad guide`.

Running `--help` per command is fine for a human who already knows what to look for. An
agent that starts from nothing has to walk 25 groups before it can tell that
`project list` needs an SSO token and everything else needs an API key. So this module
assembles a single answer: the model behind ZAD, the full command tree with its
parameters and examples, the service catalog, and the settings with their precedence.

Everything that can be derived is derived: the tree from Click, the examples from the
docstrings that already carry them, the services from the registry, the settings from
``settings.SETTING_DOCS``. What is left is the handful of facts that live in no
structure at all; those are written out below, and nowhere else, so they version with
the code that makes them true.

Markdown is the default output because that is what gets pasted into a prompt or piped
into a file. It carries no Rich markup for the same reason.
"""

from __future__ import annotations

import re
from typing import Any


def _click_core() -> Any:
    """The Click that Typer is actually driving.

    Typer 0.27 vendors Click as ``typer._click``, and there may be no top-level ``click``
    installed at all. Walking a tree with a different Click than the one that built it
    would compare classes that are not the same classes.
    """
    try:
        from typer._click import core
    except ImportError:  # pragma: no cover - a Typer that depends on click proper
        import click as core  # type: ignore[no-redef]

    return core


# Rich markup is for a terminal. The guide is text to hand on, so the tags come out.
_MARKUP_RE = re.compile(r"\[/?(?:bold|dim|italic|underline)?\s?(?:cyan|green|yellow|red|blue|magenta|white)?\]")
_EXAMPLE_RE = re.compile(r"^\s*\$ (zad .+)$", re.MULTILINE)


def strip_markup(text: str) -> str:
    """Drop Rich tags such as ``[bold]`` without touching ``[env: ...]`` or ``[default: ...]``."""
    return _MARKUP_RE.sub("", text or "")


# --- The part a human has to write -------------------------------------------------
#
# Only what cannot be read off the command tree, the registry or the settings. Anything
# longer than a few lines is a sign it belongs in one of those instead.

_OVERVIEW = [
    "ZAD (Zelfservice Applicatie Deployment) is the self-service Kubernetes platform of "
    "RijksICTGilde. This CLI wraps its Operations Manager API, and can do everything the "
    "web UI can.",
    "Three ideas carry the whole tool:",
    "1. **The API is a registry.** Which services exist, and what each accepts, comes from "
    "`GET /api/v2/services`, not from a list inside this CLI. `zad service list` and "
    "`zad service describe <name>` need no project and no key.",
    "2. **Configuration sits in layers per service**: `project`, `component`, `deployment` "
    "(and `deployment-component` for values).",
    "3. **Saving and rolling out are two things.** Most mutating calls take a `rollout` "
    "flag; `--no-rollout` writes the change and leaves the cluster alone.",
    "A worked end-to-end walkthrough against the sandbox (real commands, real payloads) "
    "lives in `docs/proefrit.md` in this repository.",
]

_AUTH = [
    "There are two kinds of credentials, and the difference explains the order of everything else.",
    "- **SSO token** (short-lived). Obtained with `zad login`, which signs you in at "
    "Keycloak. It authenticates exactly two commands: `zad project list` and "
    "`zad project create`.",
    "- **Project API key** (long-lived). Sent as `X-API-Key` on every other call. It is "
    "returned when a project is created or listed, and written to the `.env` in the "
    "working directory (mode 0600), together with the project it belongs to.",
    "Why the split: an API key belongs to one project, so you need the project's name "
    "before you can have its key. Listing and creating projects happen before that point, "
    "which is why they use the token instead.",
    "`zad project use <name>` writes the project and its key together, so switching "
    "cannot leave the previous project's key behind. An exported `-p` or "
    "`ZAD_PROJECT_ID` still wins over the file. Keys are masked in output and never "
    "logged: `--verbose` prints method, path, body and params, never headers.",
]

_LAYERS = [
    "A service is configured at a layer, and which layers it accepts is stated by the "
    "registry per service (`zad service describe <name>` shows them).",
    "- `project`: one setting for the whole project.",
    "- `component`: for one component, across every deployment that runs it.",
    "- `deployment`: for one deployment.",
    "- `deployment-component`: values (`zad env`, `zad alias`) for one component in one deployment.",
    "`--target` picks the layer. It is optional when a service has exactly one, and "
    "**required when it has more than one**: writing project-wide configuration where a "
    "deployment override was meant is not a default's decision to make.",
    "`zad service config schema <name>` prints the JSON schema of a layer's body, so you "
    "can build a request without guessing field names.",
    "Everything in `zad service list` is reachable under `zad service <name>`. Most "
    "services take a config document, so `zad service config set <name>` is the command. "
    "Three carry *values* rather than a document and have their own verbs: "
    "`zad service attachments`, `zad service user-env-vars` and `zad service aliases`, "
    "with `zad attachment`, `zad env` and `zad alias` as shorter spellings of the same "
    "thing. `zad service describe <name>` names the command for any service.",
]

_ROLLOUT = [
    "A mutation has two halves: the change is stored, and the cluster is brought in line "
    "with it. `rollout` decides whether the second half happens now.",
    "- `--rollout` (the default) saves and rolls out.",
    "- `--no-rollout` saves only. The CLI then says how many changes are waiting.",
    "- `ZAD_ROLLOUT=false` or `zad config set rollout false` makes deferring the default.",
    "- `zad project pending` lists what is saved but not rolled out.",
    "- `zad project refresh` rolls all of it out at once.",
    "Deferring is how you make several related changes land together instead of watching "
    "the cluster reconcile after each one. The flag is only sent on operations the API "
    "says accept it.",
]

_WORKFLOW = [
    "From nothing to something running. These are real commands, in order; the names are the only thing to change.",
    "```",
    "# 1. Sign in. Needed only for the two commands that cannot present a project key,",
    "#    because you need a project's name before you can have its key.",
    "zad login",
    "",
    "# 2. Create the project. You give a display name; the platform derives the technical",
    "#    name and returns it as project_name. The API key comes back once and is stored",
    "#    in the .env here, together with the project it belongs to.",
    'zad project create "Mijn Project" --description "Waar dit project voor is"',
    "",
    "# 3. Define a component, and say which services it uses. Without --deployment this",
    "#    only defines it: nothing runs it yet, which is a valid state. The image lives on",
    "#    the attachment to a deployment, so it is only needed once you attach.",
    "#    --service is not decoration: it is what makes the platform inject that service's",
    "#    variables into this component. Leave it out and the component starts without any",
    "#    DATABASE_*, REDIS_* or S3_* variable, however well the service itself is",
    "#    configured. Nothing warns you; the application finds out.",
    "zad component add web --port 8080 --service postgresql-database --service redis",
    "",
    "# 4. Create a deployment. This is an upsert: with --component it makes the deployment",
    "#    and attaches the component in one call. Without one it is an empty deployment,",
    "#    which is what you want while building the parts up separately.",
    "zad deployment create productie --component web --image ghcr.io/org/app:v1",
    "",
    "#    Attaching an existing component to another deployment later:",
    "zad component assign web acceptatie --image ghcr.io/org/app:v1",
    "",
    "# 5. Configure the services. This is the other half: step 3 said which components use",
    "#    a service, this says how the service itself is set up, at the layer it accepts.",
    "#    Both are needed. Configuring alone provisions the database but hands nobody its",
    "#    credentials; binding alone has nothing to hand over.",
    "#    `zad service list` shows which services exist and their layers.",
    "zad service config set postgresql-database --set scope=shared",
    "zad service config set publish-on-web --component web --set tls=standard",
    "",
    "# 6. Roll it out. Every command above rolls out by itself unless you turned that off",
    "#    with --no-rollout or `zad config set rollout false`. A refresh reconciles the",
    "#    whole project at once, so deferred changes do not have to be replayed one by one.",
    "zad project pending          # what is saved but not rolled out",
    "zad project refresh          # roll the whole project out",
    "",
    "# 7. See what happened.",
    "zad project status",
    "zad deployment describe productie",
    "zad logs productie -c web",
    "```",
    "**An image to try this with.** `ghcr.io/minbzk/base-images/e2e-allservices:latest` is "
    "public and made for exactly this. On start it writes to and reads back from every "
    "service it is bound to (PostgreSQL including extra schemas, Redis, MinIO, Keycloak, "
    "mounted volumes) and reports per service on `GET /status`; `/status?strict=1` answers "
    '503 until they all verify. So it turns "the CLI said it worked" into "the workload '
    'reached its services with the credentials the platform injected", which is a different '
    "claim and the one you actually want.",
    "```",
    "zad component add web --port 8080 --service postgresql-database --service redis",
    "zad deployment create productie --component web \\",
    "  --image ghcr.io/minbzk/base-images/e2e-allservices:latest",
    "zad project refresh",
    'curl -sSf "$(zad deployment describe productie -o json | jq -r .urls.web)/status?strict=1"',
    "```",
    "**Your image has to run as a non-root user.** The platform starts containers "
    "unprivileged, which has two consequences that account for most first crashes. Stock "
    "`nginx` crashloops on `mkdir /var/cache/nginx: Permission denied`; use "
    "`nginxinc/nginx-unprivileged` or another image built for it. And a port below 1024 "
    "cannot be bound, so listen on 8080 rather than 80 - which is also why `health-check` "
    "refuses a port under 1024.",
    "**Two things worth knowing before you start.**",
    "A new image on an existing deployment is `zad deployment update-image <deployment> "
    "--component <name> --image <url>`, not another `deployment create`.",
    "Every mutating command takes `--dry-run`, which prints the method, endpoint and payload "
    "without calling anything. It is the cheapest way to check a command is what you meant, "
    "and it needs no credentials beyond a project.",
]

_INPUT = [
    "Structured request bodies are given in one of two ways, and they compose:",
    "- `-f/--file <path>`: a manifest: the whole request body as YAML or JSON. `-f -` reads stdin.",
    "- `--set dotted.path=value`: one field, repeatable, list indices included "
    "(`--set components[0].image=nginx:1.27`). `--set` wins over `--file`.",
    "- `@file` as a value reads that field's content from a file.",
    "`--set` reads the value as YAML would, so `true`, `false`, `null`, `~`, `yes`, `no` and "
    "anything numeric arrive typed rather than as text. Quote to keep a string: "
    '`--set version="1.0"` is the string, `--set version=1.0` is the number. (`none` is '
    "the word `none`, not null.) `--dry-run` prints the body that would be sent, which is "
    "the cheapest way to see which of the two you got.",
    "- `--generate-skeleton` prints an empty manifest for the command to fill in.",
    "There is deliberately no notation where the position of one flag decides which other "
    "flag it belongs to: everything that belongs together is named in the path.",
    "`--from-file` is different from `--file`: it is the content of one thing (an "
    "attachment's bytes, a map of values), not the request body.",
]

_AGENTS = [
    "Working this CLI without a human at the keyboard:",
    "- **Answer the confirmations first.** `zad config set yes true` (or `ZAD_YES=true`, or "
    "`--yes` per command). Every mutating command asks before it acts, and a script that "
    "does not expect that hangs on the first one rather than failing.",
    "- `--output json` (or `-o json`, `--json`) works on every command. Data goes to "
    "stdout, status and diagnostics to stderr, so stdout stays parseable.",
    "- `zad guide --output json` is this document as structure.",
    "- `zad service list`, `zad service describe <name>` and `zad service config schema "
    "<name>` need no credentials: discover what the platform offers before logging in.",
    "- `--dry-run` on every mutating command shows the exact request that would be sent.",
    "- Failures render a diagnosis with a `fault` field and a matching exit code: 1 = your "
    "input, configuration or application; 2 = platform or network, worth retrying; 3 = "
    "unattributable, read the logs.",
    "- `--strict` turns 'succeeded but degraded' into a non-zero exit for CI.",
    "- `--no-wait` returns the task ID instead of polling; follow it with `zad task wait <id>`.",
]

_HANDWRITTEN: tuple[tuple[str, str, list[str]], ...] = (
    ("overview", "What ZAD is", _OVERVIEW),
    ("auth", "Two kinds of credentials", _AUTH),
    ("layers", "Configuration layers", _LAYERS),
    ("rollout", "Saving versus rolling out", _ROLLOUT),
    ("workflow", "The order that works", _WORKFLOW),
    ("input", "Manifests, --set and stdin", _INPUT),
    ("agents", "Notes for agents", _AGENTS),
)

# The generated sections, in the order they are rendered after the written ones.
_GENERATED = ("settings", "services", "commands")

SECTION_NAMES: tuple[str, ...] = tuple(name for name, _, _ in _HANDWRITTEN) + _GENERATED

# Every section is in the default; what changes is how deep `commands` goes. Naming every
# command is part of "what can this do"; repeating every parameter is not, because that is
# what `<command> --help` answers one command at a time. Full reference: `zad guide --all`.
DEFAULT_SECTIONS: tuple[str, ...] = SECTION_NAMES


class UnknownSectionError(ValueError):
    """A `--section` that the guide does not have."""

    def __init__(self, name: str) -> None:
        super().__init__(f"Unknown guide section '{name}'. Available: {', '.join(SECTION_NAMES)}")
        self.name = name


# --- The generated part ------------------------------------------------------------


def _param_record(param: Any) -> dict[str, Any] | None:
    """One option or positional argument, as the CLI itself declares it."""
    if param.hidden or param.name in ("help",):
        return None
    record: dict[str, Any] = {
        "name": param.name,
        "kind": "argument" if param.param_type_name == "argument" else "option",
        "required": bool(param.required),
    }
    if record["kind"] == "option":
        record["flags"] = list(param.opts) + list(getattr(param, "secondary_opts", []))
        help_text = strip_markup(getattr(param, "help", "") or "").strip()
        if help_text:
            record["help"] = help_text
    # str and bool are what a flag is by default; naming them adds noise, not information.
    type_name = getattr(param.type, "name", "") or ""
    if type_name and type_name not in ("text", "str", "bool", "boolean"):
        record["type"] = type_name
    choices = getattr(param.type, "choices", None)
    if choices:
        record["choices"] = list(choices)
    if getattr(param, "multiple", False):
        record["repeatable"] = True
    default = param.default
    if default is not None and default != () and not (record["kind"] == "option" and default is False):
        record["default"] = default
    return record


def _usage(path: str, params: list[dict[str, Any]]) -> str:
    """A one-line usage string: the command, its positionals, then whether options follow."""
    parts = [f"zad {path}" if path else "zad"]
    for param in params:
        if param["kind"] != "argument":
            continue
        name = str(param["name"]).upper()
        if param.get("repeatable"):
            name = f"{name}..."
        parts.append(name if param["required"] else f"[{name}]")
    if any(p["kind"] == "option" for p in params):
        parts.append("[OPTIONS]")
    return " ".join(parts)


def _describe(command: Any, ctx: Any, path: str) -> dict[str, Any]:
    """One command: summary, full help, parameters and the examples in its docstring."""
    help_text = strip_markup(command.help or command.short_help or "").strip()
    summary = help_text.splitlines()[0].strip() if help_text else ""
    params = [r for r in (_param_record(p) for p in command.get_params(ctx)) if r is not None]
    return {
        "path": path,
        "summary": summary,
        "help": help_text,
        "usage": _usage(path, params),
        "parameters": params,
        "examples": [match.strip() for match in _EXAMPLE_RE.findall(strip_markup(command.help or ""))],
    }


def command_tree(app: Any = None) -> dict[str, Any]:
    """Walk the Typer/Click tree: every group, every command, every parameter.

    Nothing here is a list anyone maintains. A command that is registered is a command
    that is documented, which is the only way this stays true.
    """
    import typer.main

    if app is None:
        from zad_cli.cli import app as default_app

        app = default_app

    core = _click_core()
    root = typer.main.get_command(app)
    root_ctx = core.Context(root, info_name="zad")

    groups: list[dict[str, Any]] = []
    commands: list[dict[str, Any]] = []

    def walk(node: Any, ctx: Any, path: str) -> None:
        # A group is a command that has commands. Typer's vendored Click has no separate
        # Group class, so asking for the attribute is what holds across both.
        children = getattr(node, "commands", None)
        if children:
            if path:
                groups.append(
                    {
                        "path": path,
                        "summary": (strip_markup(node.help or node.short_help or "").strip().splitlines() or [""])[0],
                    }
                )
            for name in sorted(children):
                child = children[name]
                if child.hidden:
                    continue
                child_path = f"{path} {name}".strip()
                walk(child, core.Context(child, parent=ctx, info_name=name), child_path)
            return
        commands.append(_describe(node, ctx, path))

    walk(root, root_ctx, "")
    # Top-level commands first, then one block per group. Without this the five commands
    # that sit on the root are scattered between the groups they sort next to.
    commands.sort(key=lambda c: (" " in c["path"], c["path"]))

    global_options = [r for r in (_param_record(p) for p in root.get_params(root_ctx)) if r is not None]
    return {"global_options": global_options, "groups": groups, "commands": commands}


def settings_records() -> list[dict[str, Any]]:
    """Every setting with its flag, environment variables, config key and default."""
    from zad_cli.settings import SETTING_DOCS

    return [doc.to_dict() for doc in SETTING_DOCS]


def service_records(api_url: str, *, refresh: bool = False) -> dict[str, Any]:
    """The service catalog, and where this copy of it came from."""
    from zad_cli.api.registry import load_catalog

    try:
        catalog = load_catalog(api_url, refresh=refresh)
    except Exception as e:  # noqa: BLE001 - a guide without the catalog still beats no guide
        return {"source": "unavailable", "error": str(e), "api_url": api_url, "services": []}
    return {
        "source": catalog.source,
        "api_url": api_url,
        "services": [
            {
                "name": entry.name,
                "kind": entry.kind,
                "binding": entry.binding,
                "description": entry.description,
                "config_targets": entry.targets,
                "value_targets": entry.value_targets,
            }
            for entry in catalog.visible()
        ],
    }


_CATALOG_NOTE = {
    "live": "Fetched from the API this CLI is pointed at.",
    "cache": "From the local cache of that API's catalog; `--refresh-catalog` re-fetches it.",
    "snapshot": (
        "The API did not answer, so this is the snapshot bundled with the CLI. It may differ "
        "from the services your environment actually offers."
    ),
    "unavailable": "The catalog could not be loaded; the rest of this guide is unaffected.",
}


def build_guide(
    api_url: str, *, refresh: bool = False, section: str | None = None, everything: bool = False
) -> dict[str, Any]:
    """Assemble the guide. `section` limits it to one part, by the names in SECTION_NAMES."""
    if section is not None and section not in SECTION_NAMES:
        raise UnknownSectionError(section)

    if section is not None:
        wanted: tuple[str, ...] = (section,)
    else:
        wanted = SECTION_NAMES if everything else DEFAULT_SECTIONS
    sections: list[dict[str, Any]] = []

    for name, title, paragraphs in _HANDWRITTEN:
        if name in wanted:
            sections.append({"name": name, "title": title, "paragraphs": list(paragraphs)})

    if "settings" in wanted:
        sections.append(
            {
                "name": "settings",
                "title": "Settings and where they come from",
                "paragraphs": [
                    "Highest wins: command-line flag > exported environment variable > the "
                    "`.env` in the working directory > built-in default.",
                    "There is one file, and it is that `.env`. Nothing is written under `~`, so two "
                    "checkouts can work on two projects without deciding for each other which one "
                    "is active. `zad config set <key> <value>` writes it; `zad config list` shows "
                    "each setting's value and which layer decided it.",
                ],
                "settings": settings_records(),
            }
        )

    if "services" in wanted:
        catalog = service_records(api_url, refresh=refresh)
        sections.append(
            {
                "name": "services",
                "title": "Services this platform offers",
                "paragraphs": [
                    "This list comes from the API's own registry, so it differs per environment.",
                    _CATALOG_NOTE.get(catalog["source"], ""),
                ],
                **catalog,
            }
        )

    if "commands" in wanted:
        tree = command_tree()
        # Two depths of the same tree. The map names every command with its one-line help,
        # which is what "what can this thing do" asks for; the full reference repeats every
        # parameter, which is what `<command> --help` already answers one command at a time.
        detailed = everything or section == "commands"
        sections.append(
            {
                "name": "commands",
                "title": "Every command" if detailed else "The commands, in one map",
                "paragraphs": [
                    "Generated from the command tree itself, so it cannot fall behind it.",
                    "Global options work in any position: `zad -o json project list` and "
                    "`zad project list -o json` are the same call.",
                ]
                + (
                    []
                    if detailed
                    else [
                        "Every command is here with what it does. For its parameters, run "
                        "`zad <command> --help`, or `zad guide --all` for all of them at once.",
                    ]
                ),
                **(tree if detailed else _compact(tree)),
            }
        )

    return {"guide": "zad-cli", "sections": sections}


def _compact(tree: dict[str, Any]) -> dict[str, Any]:
    """The same tree without the parameters: every command, with what it does."""
    return {
        "compact": True,
        "global_options": tree.get("global_options", []),
        "groups": tree.get("groups", []),
        "commands": [
            {"path": c.get("path", ""), "summary": c.get("summary", ""), "usage": c.get("usage", "")}
            for c in tree.get("commands", [])
        ],
    }


# --- Markdown ----------------------------------------------------------------------


_LIST_ITEM_RE = re.compile(r"^(?:- |\d+\. )")

# This document gets pasted into terminals and prompts as often as it is rendered, so
# the source lines are wrapped. Markdown joins them back up; a reader does not have to.
WRAP_WIDTH = 95


def wrap(text: str) -> list[str]:
    """One block, soft-wrapped. A list item keeps its marker and indents what follows it."""
    import textwrap

    marker = _LIST_ITEM_RE.match(text)
    # A continuation line lines up under the text, not under the marker: three spaces for
    # "1. ", two for "- ".
    indent = " " * len(marker.group(0)) if marker else ""
    return textwrap.wrap(
        text,
        width=WRAP_WIDTH,
        subsequent_indent=indent,
        break_long_words=False,
        # Without this, `--no-rollout` wraps in the middle and stops being a flag.
        break_on_hyphens=False,
    ) or [text]


def _wrap_paragraphs(paragraphs: list[str]) -> list[str]:
    """Paragraphs as blocks, with consecutive list items kept in one list.

    Inside a ``` fence nothing is touched: those lines are commands to copy, and wrapping
    or spacing them out turns a runnable block into something you have to repair first.
    """
    out: list[str] = []
    in_fence = False
    for index, paragraph in enumerate(paragraphs):
        if paragraph.startswith("```"):
            in_fence = not in_fence
            out.append(paragraph)
            if not in_fence:
                out.append("")
            continue
        if in_fence:
            out.append(paragraph)
            continue
        if not paragraph:
            continue
        out.extend(wrap(paragraph))
        following = next((p for p in paragraphs[index + 1 :] if p), "")
        if not (_LIST_ITEM_RE.match(paragraph) and _LIST_ITEM_RE.match(following)):
            out.append("")
    return out


def _settings_markdown(section: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for record in section["settings"]:
        lines.extend(wrap(f"- **{record['setting']}**: {record['description']}"))
        bits = []
        if record["flag"]:
            bits.append(f"flag `{record['flag']}`")
        if record["env"]:
            bits.append("env " + ", ".join(f"`{name}`" for name in record["env"]))
        if record["config_key"]:
            bits.append(f"config `{record['config_key']}`")
        if record["default"]:
            # A default that is a value gets code style; one that is a sentence does not,
            # or the backticks inside it would close the span early.
            default = str(record["default"])
            bits.append(f"default `{default}`" if " " not in default else f"default: {default}")
        lines.extend(f"  {line}" for line in wrap(" · ".join(bits)))
    lines.append("")
    return lines


def _services_markdown(section: dict[str, Any]) -> list[str]:
    services = section.get("services") or []
    if not services:
        return [f"_No catalog available ({section.get('error', 'unknown reason')})._", ""]
    lines = ["| Service | Kind | Binding | Config layers |", "|---|---|---|---|"]
    for service in services:
        layers = ", ".join(service["config_targets"]) or "-"
        lines.append(f"| {service['name']} | {service['kind'] or '-'} | {service['binding'] or '-'} | {layers} |")
    lines.append("")
    lines.append("`zad service describe <name>` gives one service in full, including its variables.")
    lines.append("")
    return lines


def _param_line(param: dict[str, Any]) -> str:
    if param["kind"] == "argument":
        head = f"`{str(param['name']).upper()}`"
    else:
        head = ", ".join(f"`{flag}`" for flag in param["flags"])
    bits = []
    if param["required"]:
        bits.append("required")
    if param.get("repeatable"):
        bits.append("repeatable")
    if param.get("type"):
        bits.append(str(param["type"]))
    if param.get("choices"):
        bits.append("one of " + ", ".join(str(c) for c in param["choices"]))
    if "default" in param and param["default"] not in ("", False):
        bits.append(f"default {param['default']}")
    suffix = f" ({', '.join(bits)})" if bits else ""
    help_text = param.get("help", "")
    return f"- {head}{suffix}" + (f" - {help_text}" if help_text else "")


def _commands_markdown(section: dict[str, Any]) -> list[str]:
    lines: list[str] = ["### Global options", ""]
    for param in section["global_options"]:
        lines.extend(wrap(_param_line(param)))
    lines.append("")

    summaries = {group["path"]: group["summary"] for group in section["groups"]}
    current_group = None
    for command in section["commands"]:
        group = command["path"].rsplit(" ", 1)[0] if " " in command["path"] else ""
        if group != current_group:
            current_group = group
            heading = f"zad {group}" if group else "zad (top level)"
            if section.get("compact") and lines and lines[-1] != "":
                lines.append("")
            lines.extend([f"### {heading}", ""])
            if summaries.get(group):
                lines.extend([*wrap(summaries[group]), ""])
        if section.get("compact"):
            # One line per command: the name, and what it does. Enough to find the command
            # you want; `--help` says how to call it.
            summary = command.get("summary") or ""
            if lines and lines[-1].startswith("- ") and group != current_group:
                lines.append("")
            lines.extend(wrap(f"- `zad {command['path']}`" + (f": {summary}" if summary else "")))
            continue
        lines.append(f"#### `{command['usage']}`")
        lines.append("")
        if command["summary"]:
            lines.extend([*wrap(command["summary"]), ""])
        if command["parameters"]:
            for param in command["parameters"]:
                lines.extend(wrap(_param_line(param)))
            lines.append("")
        if command["examples"]:
            lines.append("```sh")
            lines.extend(f"$ {example}" for example in command["examples"])
            lines.extend(["```", ""])
    if section.get("compact"):
        lines.append("")
    return lines


def render_markdown(guide: dict[str, Any]) -> str:
    """The guide as plain markdown: no Rich markup, readable as text."""
    lines: list[str] = ["# zad-cli guide", ""]
    lines.extend(
        [
            *wrap(
                "Everything this CLI can do, in one document. Generated by `zad guide`; "
                "`zad guide --output json` gives the same content as structure."
            ),
            "",
        ]
    )
    for section in guide["sections"]:
        lines.append(f"## {section['title']}")
        lines.append("")
        lines.extend(_wrap_paragraphs(section.get("paragraphs", [])))
        if section["name"] == "settings":
            lines.extend(_settings_markdown(section))
        elif section["name"] == "services":
            lines.extend(_services_markdown(section))
        elif section["name"] == "commands":
            lines.extend(_commands_markdown(section))
    # One trailing newline, not three: this gets written to a file as often as it is read.
    return "\n".join(lines).rstrip("\n") + "\n"
