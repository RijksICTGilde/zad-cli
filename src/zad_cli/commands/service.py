"""Service commands: browse the catalog and configure a service per layer.

Nothing in this file knows a service name. The catalog says which services exist and at
which layers each accepts config; the vendored spec says what the body for that layer
looks like. A service added upstream needs no change here.
"""

from __future__ import annotations

import json
from typing import Annotated, Any

import typer
from typer.core import TyperCommand, TyperGroup

from zad_cli.helpers import (
    complete_component,
    complete_deployment,
    complete_service,
    confirm_action,
    get_catalog,
    get_helpers,
    handle_api_errors,
    render_dry_run,
    require_project,
    require_service,
    resolve_target,
    surface_warnings,
)
from zad_cli.manifest import apply_sets, load_payload_file, render_skeleton


class ServiceGroup(TyperGroup):
    """`zadctl service <name>` for every service, not only the five with their own verbs.

    The name of a service is the most obvious thing to type after `zadctl service`, and it
    used to answer "No such command" for sixteen of the twenty-one -- while five of them
    (`attachments`, `aliases`, the two storages, `user-env-vars`) did work, because they
    happen to need their own verbs. Which five is not something anyone can be expected to
    know, and "it depends on the shape of its config document" is not an answer either.

    So every service name resolves, from the catalog rather than from a list here: a
    service the platform adds tomorrow works tomorrow. The ones with their own group keep
    it -- they are looked up first -- and the rest describe themselves, which is what a
    name on its own is asking for.
    """

    def get_command(self, ctx, name):  # noqa: ANN001, ANN201
        real = super().get_command(ctx, name)
        if real is not None:
            return real
        entry = _catalog_entry(ctx, name)
        if entry is None:
            return None
        api_url = ""
        if isinstance(getattr(ctx, "obj", None), dict) and ctx.obj.get("settings") is not None:
            api_url = ctx.obj["settings"].api_url
        return _describe_command(entry, api_url)

    def resolve_command(self, ctx, args):  # noqa: ANN001, ANN201
        """Name a near miss, because "No such command" alone is where this started.

        `list_commands` deliberately does not carry every service name -- twenty-one of
        them on the help screen buries the verbs -- so Click has nothing to suggest from.
        The catalog does.
        """
        try:
            return super().resolve_command(ctx, args)
        except typer.BadParameter:
            raise
        except Exception as e:  # noqa: BLE001 - UsageError and its subclasses
            typed = args[0] if args else ""
            names = [*self.list_commands(ctx), *_catalog_names(ctx)]
            import difflib

            close = difflib.get_close_matches(typed, names, n=3, cutoff=0.6)
            if not close:
                raise
            message = f"No such command '{typed}'. Did you mean: {', '.join(close)}?"
            raise type(e)(message) from None


app = typer.Typer(
    cls=ServiceGroup,
    help=(
        "Browse and configure platform services.\n\n"
        "Which services exist depends on the API you are pointed at, so this help cannot list "
        "them: run [bold]zadctl service list[/bold] to see them, and "
        "[bold]zadctl service <name> --help[/bold] for what one does and what you can set on it.\n\n"
        "`list` and `describe` read the public catalog and need no credentials. "
        "The `config` commands require ZAD_API_KEY and ZAD_PROJECT_ID (or --api-key and -p)."
    ),
    no_args_is_help=True,
)

config_app = typer.Typer(
    help=(
        "Read and write a service's configuration, per layer.\n\n"
        "Run [bold]zadctl service list[/bold] for the service names, and "
        "[bold]zadctl service config schema <name> --target <layer>[/bold] for the fields a layer takes."
    ),
    no_args_is_help=True,
)
app.add_typer(config_app, name="config")

# The three services that carry *values* instead of a config document need their own verbs:
# "add this attachment" is not expressible as "set this document". They live here, under the
# name `zadctl service list` shows, so that everything in that list is reachable the way it is
# named. The short top-level forms (`zadctl attachment`, `zadctl env`, `zadctl alias`) are the same
# apps registered twice: having to remember which services are the exception is worse than
# two spellings of the same thing.
from zad_cli.commands import attachment as _attachment  # noqa: E402
from zad_cli.commands.storage import persistent_app as _persistent_app  # noqa: E402
from zad_cli.commands.storage import temp_app as _temp_app  # noqa: E402
from zad_cli.commands.values import alias_app as _alias_app  # noqa: E402
from zad_cli.commands.values import env_app as _env_app  # noqa: E402

app.add_typer(_attachment.app, name="attachments")
app.add_typer(_env_app, name="user-env-vars")
app.add_typer(_alias_app, name="aliases")
# No top-level alias for these two, on purpose. The three above sit at the root because they
# got there first; the entry point is `zadctl service <name>` and the root does not grow a
# keyword per service. `zadctl service list` is the index.
app.add_typer(_persistent_app, name="persistent-storage")
app.add_typer(_temp_app, name="temp-storage")

# A few services are driven by their own command group rather than by `service config`:
# they carry *values* (a set of entries) instead of *config* (one document per layer), and
# a group with its own verbs says that better than a generic setter would. The registry
# cannot state this, because these are our command names, not its.
_OWN_COMMAND: dict[str, tuple[str, str]] = {
    "attachments": ("zadctl service attachments", "zadctl attachment"),
    "user-env-vars": ("zadctl service user-env-vars", "zadctl env"),
    "aliases": ("zadctl service aliases", "zadctl alias"),
    # No shorter second name for these two: the root does not grow a keyword per service.
    # Same value twice, so the one form is what gets printed.
    "persistent-storage": ("zadctl service persistent-storage", "zadctl service persistent-storage"),
    "temp-storage": ("zadctl service temp-storage", "zadctl service temp-storage"),
}


def _use_short(entry: Any) -> str:
    """The command group, for a table cell. `describe` gives the whole invocation."""
    own = _OWN_COMMAND.get(entry.name)
    if own:
        return own[1]
    return "zadctl service config" if entry.targets else "-"


def _how_to_use(entry: Any) -> str:
    """The command that actually configures this service."""
    own = _OWN_COMMAND.get(entry.name)
    if own:
        full, short = own
        return short if short == full else f"{short} (or {full})"
    if not entry.targets:
        return "nothing to set: the platform runs this by itself"
    # The layers you can actually write. The registry advertises `deployment-component`
    # for publish-on-web with no endpoint behind it, and offering it here sends the reader
    # into a refusal -- `service describe` marks it, so this must not contradict that.
    layers = entry.writable_targets() or entry.targets
    if len(layers) == 1:
        return f"zadctl service config set {entry.name}"
    return f"zadctl service config set {entry.name} --target <{'|'.join(layers)}>"


def _targets_cell(entry) -> str:
    """The writable layers, with an asterisk when the registry advertises one without an endpoint."""
    label = ", ".join(entry.writable_targets()) or "-"
    if entry.unwritable_targets():
        label += " *"
    return label


_TARGET_HELP = (
    "Config layer to act on: project, component or deployment. Optional only when the service "
    "has one layer; required otherwise, on purpose, so a project-wide write is never a default "
    "you did not choose. `zadctl service describe <name>` lists the layers a service takes."
)


# Values that mean "do not do the thing this service does". An example is a demonstration,
# and demonstrating the off switch is how a reader ends up pasting one.
_OFF_VALUES = frozenset({"none", "off", "disabled", "never", "false", "no"})


def _choices(node: Any) -> list[str]:
    """The values this field accepts, as the API states them.

    `x-choices` is the platform's own answer to "what may I put here": a list of
    ``{const, title}``, in the order it means them -- `tcp` before `none` for a probe,
    `48h` in a row of durations. It carries fields a plain `enum` never covered, which is
    why `sleep-after-deploy` could only be described as `<text>` before.

    Falls back to `enum`, then to a single `const`, so a field the platform has not
    annotated yet still says what it can.
    """
    if not isinstance(node, dict):
        return []
    inner = _inner(node) or node
    for source in (node, inner):
        raw = source.get("x-choices")
        if isinstance(raw, list) and raw:
            out = [str(c.get("const")) for c in raw if isinstance(c, dict) and c.get("const") is not None]
            if out:
                return out
    for source in (node, inner):
        if source.get("enum"):
            return [str(v) for v in source["enum"]]
        if "const" in source:
            return [str(source["const"])]
    return []


def _source(node: Any) -> dict[str, Any] | None:
    """`x-choices-source`: the values depend on the project, and this says where they live.

    The API is explicit about why it is not an `enum`: "An enumeration here would be one
    project's snapshot and wrong for every other." It carries a description, and usually an
    ``endpoint`` with a ``path`` into its answer.
    """
    if not isinstance(node, dict):
        return None
    inner = _inner(node) or node
    for candidate in (node.get("x-choices-source"), inner.get("x-choices-source")):
        if isinstance(candidate, dict):
            return candidate
    return None


def _extract(node: Any, parts: list[str]) -> list[str]:
    """Read `components[].name` out of a response, the way the source states it."""
    if not parts:
        return [str(node)] if isinstance(node, str | int | float) else []
    head, rest = parts[0], parts[1:]
    if head.endswith("[]"):
        sequence = node.get(head[:-2]) if isinstance(node, dict) else None
        if not isinstance(sequence, list):
            return []
        return [value for item in sequence for value in _extract(item, rest)]
    if isinstance(node, dict) and head in node:
        return _extract(node[head], rest)
    return []


def _values_from_source(ctx: Any, source: dict[str, Any], cache: dict[str, list[str]]) -> list[str]:
    """The values this project actually offers for one field, or nothing.

    Only for a source that names a `GET` whose placeholders this run can fill. A
    `{peer_project}` cannot be resolved without knowing which peer is meant, and guessing
    one project's neighbours would be worse than saying nothing.

    Never raises: an unreachable endpoint, a missing key or an API that answers something
    unexpected all mean "no list here", and `describe` keeps working without a project at
    all -- which is the property that makes it the first command anyone runs.
    """
    endpoint, path = source.get("endpoint"), source.get("path")
    if not isinstance(endpoint, str) or not isinstance(path, str):
        return []
    method, _, template = endpoint.partition(" ")
    if method.upper() != "GET":
        return []

    settings = ctx.obj.get("settings") if isinstance(getattr(ctx, "obj", None), dict) else None
    project = getattr(settings, "project_id", "") or ""
    if not project or not getattr(settings, "api_key", ""):
        return []
    template = template.replace("{project_name}", project).replace("{project}", project)
    if "{" in template:
        # A placeholder nobody in this call can fill, `{peer_project}` above all.
        return []
    if template in cache:
        return cache[template]

    try:
        client, _ = get_helpers(ctx)
        # No retries on a side quest. The client retries a 5xx three times with a growing
        # delay, which is right for the call you actually asked for and wrong for the extra
        # one that only enriches a table: a failing endpoint would add six seconds to a
        # description that has already been written.
        retries, client.max_retries = client.max_retries, 0
        try:
            response = client._request("GET", template.removeprefix("/api"))  # noqa: SLF001
        finally:
            client.max_retries = retries
        values = _extract(response.json(), path.split("."))
    except Exception:  # noqa: BLE001 - no list is a fine answer; a traceback is not
        values = []
    cache[template] = values
    return values


def _examples(node: Any) -> list[str]:
    """The concrete values the spec offers as illustrations, wherever it hangs them.

    `match` on sleep-mode is the field nobody can guess -- "which deployments are in scope"
    with a syntax of its own -- and the API answers it with `pr-*`, `*-preview`,
    `acceptatie` on the *item* of the array. Read only the field itself and you print
    `<text>` next to a question the platform has already answered.
    """
    if not isinstance(node, dict):
        return []
    inner = _inner(node) or node
    for source in (node, inner, inner.get("items") if isinstance(inner.get("items"), dict) else {}):
        found = source.get("examples") if isinstance(source, dict) else None
        if isinstance(found, list) and found:
            return [str(value) for value in found]
    return []


def _is_closed(node: Any) -> bool:
    """Whether the listed values are the *only* ones this field accepts.

    The API says which is which, and the difference is the whole meaning of the column:
    "`enum` is present when the field itself is closed: those values, and nothing else, are
    accepted. `x-choices` lists what the portal OFFERS ... Without an `enum` the field
    accepts more than the list shows (`sleep-after-deploy` takes any duration, `90m`
    included), so treat it as a menu, not as validation."

    Printing a menu as if it were the closed set is how a reader concludes `90m` is
    invalid and works around a rule that was never there.
    """
    if not isinstance(node, dict):
        return False
    inner = _inner(node) or node
    return any(source.get("enum") or "const" in source for source in (node, inner))


def _labelled_choices(node: Any) -> list[tuple[str, str]]:
    """`x-choices` as (value, label) pairs; the label is what the platform calls it."""
    if not isinstance(node, dict):
        return []
    inner = _inner(node) or node
    for source in (node, inner):
        raw = source.get("x-choices")
        if isinstance(raw, list) and raw:
            return [
                (str(c["const"]), str(c.get("title") or ""))
                for c in raw
                if isinstance(c, dict) and c.get("const") is not None
            ]
    return []


def _inner(node: Any) -> dict[str, Any]:
    """The real field behind FastAPI's optional wrapper: `anyOf: [{...}, {type: null}]`."""
    if not isinstance(node, dict):
        return {}
    for option in node.get("anyOf") or node.get("oneOf") or []:
        if isinstance(option, dict) and option.get("type") != "null":
            return option
    return {}


def _type_name(node: Any) -> str:
    """A field's type as one word, out of the shapes the spec actually uses.

    FastAPI writes an optional field as ``anyOf: [{type: x}, {type: null}]``, so reading
    ``type`` alone leaves most fields blank -- which is the same as not printing the
    column at all.
    """
    if not isinstance(node, dict):
        return ""
    if "const" in node:
        # The one value this field may hold in this variant. Printing "string" would be
        # true and useless: what the reader needs is the word that picks the variant.
        return str(node["const"])
    stated = _choices(node)
    if stated:
        # "e.g." is the whole difference between a closed set and a menu, and the API is
        # explicit about which it is offering.
        joined = " | ".join(stated)
        return joined if _is_closed(node) else f"e.g. {joined}"
    kind = node.get("type")
    if kind == "array":
        inner = _type_name(node.get("items") or {})
        return f"list of {inner}" if inner else "list"
    if kind:
        return str(kind)
    for option in node.get("anyOf") or node.get("oneOf") or []:
        if isinstance(option, dict) and option.get("type") != "null":
            return _type_name(option)
    return ""


def _example_value(node: Any) -> str:
    """A value that would be accepted, for the example line.

    Preference order is what a reader can trust most: the field's own example, then its
    default, then one of its allowed values, and only then a placeholder shaped like the
    type. A placeholder is angle-bracketed so nobody pastes it as if it were real.
    """
    if not isinstance(node, dict):
        return "<value>"
    illustrations = _examples(node)
    if illustrations:
        return illustrations[0]
    if "const" in node:
        return str(node["const"])
    kind = _type_name(node)
    if kind == "boolean":
        # Always `true`, never the flipped default. `redis` has one field, `acl-key-prefix`,
        # which is on by default and restricts the project's user to its own keys; flipping
        # it produced `--set acl-key-prefix=false` as *the* example for redis -- an example
        # that turns a protection off, with the sentence explaining that consequence sitting
        # in the part of the description this table does not show. `true` reads as switching
        # something on wherever it lands, and on a field that already defaults to true it is
        # a harmless no-op rather than a suggestion.
        return "true"
    if "default" in node and node["default"] not in (None, "", [], {}):
        # A string default earns its place: "48h" says more about the format than
        # <duration> ever could. An *empty* default does not: `--set description=` is a
        # line that sets nothing and looks like a typo.
        return str(node["default"])
    allowed = _choices(node)
    if allowed:
        # `x-choices` is ordered the way the platform means it -- `tcp` first for a probe,
        # `none` last -- so the first entry is the one to show. A bare `enum` has no such
        # promise: `health-check` lists `none | tcp | http | https`, and `--set scheme=none`
        # (probes off) is a poor example for a service whose point is probing, so a value
        # that reads as "off" is skipped where there is another. Same rule as the boolean.
        preferred = [v for v in allowed if v.lower() not in _OFF_VALUES]
        return preferred[0] if preferred else allowed[0]
    if kind in ("integer", "number"):
        return "<number>"
    if kind.startswith("list"):
        return "<value>"
    return "<value>"


def _accepted_values(node: Any) -> str:
    """What you may put after the `=`, in the words you would type.

    The type is the schema's answer to a question nobody asked at the command line:
    "string" does not tell you that `wake-mode` takes one of three words, and "boolean" is
    a longer way of writing `true | false`. Where the schema names the values, they are the
    column; where it does not, a placeholder shaped like the value is.
    """
    kind = _type_name(node)
    if kind == "boolean":
        return "true | false"

    # Every constraint the API states, on whichever level it states it. Leaving one out
    # sends the reader to a 422 to learn a rule that was written down all along; the pair
    # below is read together so a field that is optional (`anyOf: [{...}, {null}]`) is not
    # quietly less documented than a required one.
    inner = _inner(node) or (node if isinstance(node, dict) else {})
    outer = node if isinstance(node, dict) else {}

    def stated(name: str) -> Any:
        value = inner.get(name)
        return outer.get(name) if value is None else value

    if kind in ("integer", "number"):
        low, high = stated("minimum"), stated("maximum")
        # Exclusive bounds are a different promise, and saying ">0" as "0" would be wrong.
        low_x, high_x = stated("exclusiveMinimum"), stated("exclusiveMaximum")
        limits = []
        if low is not None and high is not None:
            limits.append(f"{low:g}-{high:g}")
        elif low is not None:
            limits.append(f"{low:g} or more")
        elif high is not None:
            limits.append(f"up to {high:g}")
        if low_x is not None:
            limits.append(f"over {low_x:g}")
        if high_x is not None:
            limits.append(f"under {high_x:g}")
        if stated("multipleOf") is not None:
            limits.append(f"multiple of {stated('multipleOf'):g}")
        return f"<number {', '.join(limits)}>" if limits else "<number>"

    if kind == "string":
        # A `pattern` is the whole answer to "what may I put here" for a name or a path.
        # Printed as the regex, because that is what the spec has: inventing prose around
        # it would be inventing a rule.
        limits = []
        shown = _examples(node)
        low, high = stated("minLength"), stated("maxLength")
        if low and high:
            limits.append(f"{low}-{high} chars")
        elif high is not None:
            limits.append(f"max {high}")
        elif low:
            limits.append(f"min {low}")
        if stated("format"):
            limits.append(str(stated("format")))
        if stated("pattern"):
            limits.append(str(stated("pattern")))
        if shown:
            # Illustrations, not a closed set, so the same hedge a menu gets. The rule, if
            # the spec states one, goes behind them: both matter and they are not the same
            # claim.
            joined = " | ".join(shown)
            return f"e.g. {joined} ({', '.join(limits)})" if limits else f"e.g. {joined}"
        return f"<text: {', '.join(limits)}>" if limits else "<text>"

    if kind.startswith("list"):
        # One entry per `--set`, so what matters is the shape of *an* entry -- but how many
        # entries there may be belongs to the option as a whole.
        shown = _examples(node)
        entry = f"e.g. {' | '.join(shown)}" if shown else ("<text>" if kind == "list of string" else "<value>")
        counts = []
        low, high = stated("minItems"), stated("maxItems")
        if low:
            counts.append(f"at least {low}")
        if high is not None:
            counts.append(f"at most {high}")
        if stated("uniqueItems"):
            counts.append("each entry unique")
        return f"{entry} ({', '.join(counts)})" if counts else entry

    # A choice list, a const, or an object: `_type_name` already spells those out.
    return kind or "<value>"


def _values_cell(node: Any, live: list[str] | None) -> str:
    """The values column: what the project offers where that is known, the rule otherwise.

    Three answers in falling order of usefulness. The list this project actually has, when
    the API named an endpoint and we could reach it. Failing that, what the source *is*
    ("the components of this project"), which is a shorter walk than `<text>` leaves you.
    Failing that, the ordinary rules.
    """
    if live:
        return " | ".join(live)
    source = _source(node)
    if source and source.get("description"):
        return f"<{_first_sentence(str(source['description']), 90).rstrip('.')}>"
    return _accepted_values(node)


def _leaves(
    props: dict[str, Any] | None, required: set[str], prefix: str = "", depth: int = 0
) -> list[tuple[str, dict[str, Any], bool]]:
    """Every settable key as `--set` spells it, with the node behind it.

    A nested object is not one option, it is the options inside it. `cross-domain-access`
    is a list of objects two levels deep, so the top level alone reads `inbound[0]` with no
    hint of what goes in it -- a row that costs a line and answers nothing. Expanded, it
    says `inbound[0].from.project`, which is the string you actually type.

    Depth is capped so a schema that nests further degrades to naming the branch rather
    than printing a page.
    """
    if not isinstance(props, dict):
        return []
    out: list[tuple[str, dict[str, Any], bool]] = []
    for name, node in props.items():
        if not isinstance(node, dict):
            continue
        key = f"{prefix}{name}"
        is_required = name in required
        inner = _inner(node) or node
        items = inner.get("items") if inner.get("type") == "array" else None
        sub, sub_prefix = None, ""
        if isinstance(items, dict) and isinstance(items.get("properties"), dict):
            sub, sub_prefix = items, f"{key}[0]."
        elif inner.get("type") == "object" and isinstance(inner.get("properties"), dict):
            sub, sub_prefix = inner, f"{key}."

        if sub is not None and depth < 2:
            out.extend(_leaves(sub["properties"], set(sub.get("required") or []), sub_prefix, depth + 1))
            continue
        # A list of scalars is still set per entry, so the key carries the index.
        if _type_name(node).startswith("list"):
            key = f"{key}[0]"
        out.append((key, node, is_required))
    return out


def _settings_rows(schema: dict[str, Any] | None, resolve: Any = None) -> list[dict[str, str]]:
    """One row per settable key, or nothing for a body that is not a document.

    A list-shaped body (the attachment couplings, the storage volumes) has no `properties`
    and is not described by a field table; those services have their own commands, which
    `use` already names.

    ``resolve`` is what turns an `x-choices-source` into this project's actual values. It
    is optional because the caller decides whether that is appropriate: `describe` asks the
    API, a `--help` screen does not go and fetch a project's components.
    """
    props = (schema or {}).get("properties")
    if not isinstance(props, dict):
        return []
    rows = []
    for key, node, is_required in _leaves(props, set((schema or {}).get("required") or [])):
        default = node.get("default")
        source = _source(node)
        live = resolve(source) if (resolve and source) else None
        row = {
            "option": f"{key} *" if is_required else key,
            "values": _values_cell(node, live),
            "default": "" if default is None else json.dumps(default, ensure_ascii=False),
            # The whole first sentence, not a stub of one: the column wraps, and this
            # is the sentence that says what the field is for. `service config schema`
            # has the rest.
            "description": _first_sentence(node.get("description", ""), 240),
        }
        labelled = _labelled_choices(node)
        if labelled:
            # The platform names its choices as well as listing them ("168h" is "7 dagen"),
            # and a reader deciding between eight durations wants the name. It does not go
            # in the table -- eight labels in one cell is a wall -- but json has no width,
            # and an agent reading this is the reader who benefits most.
            row["choices"] = [{"value": value, "label": label} for value, label in labelled]
        if source:
            # The whole source object, not just what fitted in a cell: an agent that wants
            # the current list should be able to call the endpoint the API named, without
            # this CLI standing in the middle of it.
            row["source"] = source
            if live:
                row["choices"] = [{"value": value, "label": ""} for value in live]
                # Said out loud, because the cell now looks exactly like a platform rule
                # while it is one project's answer at one moment. A reader pasting this
                # into a ticket, and an agent remembering it, both need the difference.
                row["from_project"] = True
        rows.append(row)
    return rows


def _example_command(entry: Any, layer: str, schema: dict[str, Any] | None, *, count: int = 1) -> str:
    """A line you can run, built from the schema rather than written out per service.

    `use` says which command configures a service; it does not say what to put in it, and
    a reader who has to open `service config schema` to find the first field is a reader
    the description sent away. The required field comes first if there is one, because
    that is the one the API refuses the call without.

    With ``count`` above one it sets several options in the same call. One example on its
    own reads as the whole grammar, and the grammar it suggests is one call per setting --
    which is not just slower but wrong for a document this CLI writes whole: a second call
    is a second body.
    """
    props = (schema or {}).get("properties")
    if not isinstance(props, dict) or not props:
        return ""
    leaves = _leaves(props, set((schema or {}).get("required") or []))
    if not leaves:
        return ""

    # The same keys the table lists, so the example is one of its rows rather than a second
    # opinion on what the options are. Required first (the API refuses the call without
    # it), then the ones the schema gives a real value for, so the line reads as something
    # somebody might actually mean rather than a row of <text>.
    ordered = sorted(leaves, key=lambda leaf: (not leaf[2], _example_value(leaf[1]).startswith("<")))
    chosen = ordered[:count]

    parts = [f"zadctl service config set {entry.name}"]
    if len(entry.targets) > 1:
        parts.append(f"--target {layer}")
    if layer == "component":
        parts.append("--component <name>")
    elif layer == "deployment":
        parts.append("--deployment <name>")
    parts.extend(_set_flag(key, _example_value(node)) for key, node, _ in chosen)
    return " ".join(parts)


# Characters a shell reads before the command ever sees them. `match[0]=pr-*` is two of
# them: zsh globs the brackets *and* the star, and answers "no matches found" instead of
# running anything. `<value>` is a redirection. An example you cannot paste is not one.
_SHELL_SPECIAL = frozenset("*?[]{}()$`~!#&;<>|\\'\" \t")


def _set_flag(key: str, value: str) -> str:
    """One `--set` flag, quoted when the shell would otherwise take it apart."""
    pair = f"{key}={value}"
    return f"--set '{pair}'" if any(char in _SHELL_SPECIAL for char in pair) else f"--set {pair}"


def _variants(schema: dict[str, Any] | None) -> list[tuple[str, dict[str, Any]]]:
    """A config body as the one or more shapes it is allowed to have.

    `postgresql-database` is a `oneOf`: a database on the shared instance takes different
    fields from one of its own. Reading only the top level shows nothing at all for it,
    which is worse than the `service config schema` it was meant to save you from. The
    branches are labelled by the field that tells them apart -- `scope`, here -- because
    "option 1" is not something you can act on.
    """
    if not isinstance(schema, dict):
        return []
    branches = schema.get("oneOf") or schema.get("anyOf")
    if not isinstance(branches, list) or not branches:
        return [("", schema)]

    out: list[tuple[str, dict[str, Any]]] = []
    for index, branch in enumerate(branches, start=1):
        if not isinstance(branch, dict):
            continue
        label = ""
        for name, node in (branch.get("properties") or {}).items():
            if isinstance(node, dict) and "const" in node:
                label = f"{name}={node['const']}"
                break
        out.append((label or f"option {index}", branch))
    return out


def _catalog_names(ctx: Any) -> list[str]:
    """Every service name this API offers, for suggesting one back. Never fetches."""
    from zad_cli.api.registry import load_catalog

    api_url = ""
    if isinstance(getattr(ctx, "obj", None), dict) and ctx.obj.get("settings") is not None:
        api_url = ctx.obj["settings"].api_url
    try:
        return load_catalog(api_url or "", ttl=2**31).names()
    except Exception:  # noqa: BLE001 - no catalog means nothing to suggest, not a crash
        return []


def _catalog_entry(ctx: Any, name: str) -> Any:
    """One catalog entry by name, for resolving `zadctl service <name>`.

    Never fetches: this runs while Click is still working out which command was typed, and
    a name that turns out to be a typo must not cost a round trip -- nor must `--help` on
    a laptop with no connection. The cache or the bundled snapshot is enough to know
    whether a name is a service.
    """
    from zad_cli.api.registry import load_catalog

    api_url = ""
    if isinstance(getattr(ctx, "obj", None), dict) and ctx.obj.get("settings") is not None:
        api_url = ctx.obj["settings"].api_url
    try:
        catalog = load_catalog(api_url or "", ttl=2**31)
    except Exception:  # noqa: BLE001 - no catalog means no dynamic name, not a crash here
        return None
    try:
        return catalog.get(name)
    except Exception:  # noqa: BLE001 - UnknownServiceError and friends: simply not a service
        return None


def _describe_command(entry: Any, api_url: str = "") -> Any:
    """`zadctl service <name>`: the service explained, and what you can set on it.

    Built when the name is typed rather than registered up front, because the names come
    from the registry and the registry is not a list this CLI keeps. The help text is the
    same material `describe` prints, so the two cannot drift.
    """
    current_context = _current_context()

    def _run() -> None:
        # `obj` is inherited from the parent context, so this is the same settings,
        # formatter and catalog every other command works from.
        describe(current_context(), entry.name)

    # TyperCommand rather than a bare Click Command: the vendored `Command` is abstract,
    # and this is the class every other command in this CLI is rendered with, so the help
    # screen looks like the rest instead of like a guest.
    return _ServiceCommand(
        name=entry.name,
        short_help=_first_sentence(entry.description or "", 70),
        callback=_run,
        params=[],
        entry=entry,
        api_url=api_url,
    )


class _ServiceCommand(TyperCommand):
    """`zadctl service <name>`, whose help text is written when it is asked for.

    Not at construction: resolving a command happens on every invocation, including the one
    that goes on to run it, and building this help reads a spec and may ask the API what
    this project's components are called. Only `--help` should pay for that.
    """

    def __init__(self, *args: Any, entry: Any = None, api_url: str = "", **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._entry, self._api_url = entry, api_url

    def format_help(self, ctx: Any, formatter: Any) -> None:
        self.help = _command_help(self._entry, self._api_url, ctx)
        super().format_help(ctx, formatter)


def _current_context() -> Any:
    """Click's context accessor, from the Click that Typer is actually driving.

    Typer vendors Click as ``typer._click``, and there may be no top-level ``click``
    installed at all -- the same reason `guide.py` looks it up this way.
    """
    try:
        from typer._click.globals import get_current_context
    except ImportError:  # pragma: no cover - a Typer that depends on click proper
        from click.globals import get_current_context  # type: ignore[no-redef]

    return get_current_context


def _command_help(entry: Any, api_url: str = "", ctx: Any = None) -> str:
    """Plain-text help for one service: what it is, how to set it, what it takes.

    Plain text, not a Rich table: this is Click's help, wrapped by Click. The options are
    read from the cached spec only -- `--help` that waits on the network is `--help` that
    hangs on a train.
    """
    lines = [entry.description or f"The {entry.name} service.", ""]
    lines.append(f"Configure with: {_how_to_use(entry)}")
    if entry.value_targets:
        lines.append(f"Values live at: {', '.join(entry.value_targets)}")
    lines.append(f"Full description: zadctl service describe {entry.name}")

    # Three seconds, not fifteen: a help screen that waits on a network is a help screen
    # that hangs, and the bundled spec is a fair answer when the API is slower than that.
    # After any other command has run once, this is a cache read and costs nothing.
    per_layer = _settings_per_layer(entry, api_url or None, timeout=3.0, ctx=ctx)
    for layer, blocks in per_layer.items():
        for block in blocks:
            heading = "Options" if len(entry.targets) == 1 else f"Options ({layer})"
            if block["variant"]:
                heading = f"{heading} — {block['variant']}"
            lines += ["", f"{heading}:"]
            width = max(len(row["option"]) for row in block["fields"])
            for row in block["fields"]:
                default = f"  (default {row['default']})" if row["default"] else ""
                values = f"{row['values']} +" if row.get("from_project") else row["values"]
                lines.append(f"  {row['option']:<{width}}  {values}{default}")
            if block["example"]:
                lines += ["", f"  $ {block['example']}"]
            # Both examples, exactly as `describe` gives them. One on its own reads as the
            # whole grammar, and the grammar it suggests is one call per setting -- which
            # loses the earlier settings, because this command writes the document whole.
            # Two screens that answer the same question must not answer it differently.
            if block["example_multiple"]:
                lines += ["", "  or several at once:", f"  $ {block['example_multiple']}"]

    # The same note `describe` prints under its table. Which half depends on whether the
    # values could be read: with a project they are here, and saying "with a project
    # selected, run describe" to someone who *has* one selected is the CLI not knowing what
    # it just did.
    rows = [row for blocks in per_layer.values() for b in blocks for row in b["fields"]]
    if any(row.get("from_project") for row in rows):
        project = ""
        if isinstance(getattr(ctx, "obj", None), dict) and ctx.obj.get("settings") is not None:
            project = getattr(ctx.obj["settings"], "project_id", "") or ""
        lines += ["", f"+ from project '{project or '?'}'; these values differ per project"]
    elif any(row.get("source") for row in rows):
        lines += [
            "",
            "Options shown as <...> take values that come from your project itself.",
            f"Select a project, or run `zadctl service describe {entry.name}` there, to see the current ones.",
        ]
    return "\n".join(lines)


def _settings_per_layer(
    entry: Any, api_url: str | None = None, *, refresh: bool = False, timeout: float = 15.0, ctx: Any = None
) -> dict[str, list[dict[str, Any]]]:
    """What can be set at each of a service's layers, read from that API's own spec.

    The platform states what it accepts and keeps stating more of it -- `x-choices` on a
    dozen fields today, and whatever it adds next month. A CLI that answers from the spec
    it shipped with is a CLI that goes stale between releases, on the one command whose
    whole job is telling you what the platform offers.

    So: live where it can be reached, cached for a day, the bundled copy otherwise. That
    last fallback is why `describe` still answers without a project, a key or a network,
    which is what makes it the first command an agent runs.
    """
    from zad_cli.api import spec

    # One cache per call: several fields name the same endpoint (four of them ask for this
    # project's components), and asking four times for one table would be rude.
    fetched: dict[str, list[str]] = {}
    resolve = (lambda source: _values_from_source(ctx, source, fetched)) if ctx is not None else None

    out: dict[str, list[dict[str, Any]]] = {}
    for layer in entry.targets:
        try:
            schema = spec.request_schema(
                "PUT", _template_path(entry, layer), api_url=api_url, refresh=refresh, timeout=timeout
            )
        except typer.BadParameter:
            # A layer the registry advertises and this CLI cannot reach: `targets_labelled`
            # already marks it, and a missing field table is not the place to raise.
            continue
        blocks = []
        for label, branch in _variants(schema):
            rows = _settings_rows(branch, resolve)
            if not rows:
                continue
            blocks.append(
                {
                    "variant": label,
                    "fields": rows,
                    "example": _example_command(entry, layer, branch),
                    # Only where there is a second option to combine with; on a one-option
                    # service the two lines would be the same line printed twice.
                    "example_multiple": (_example_command(entry, layer, branch, count=3) if len(rows) > 1 else ""),
                }
            )
        if blocks:
            out[layer] = blocks
    return out


def _first_sentence(text: str, limit: int = 90) -> str:
    """First sentence of a description, for the list table."""
    head = text.split(". ", 1)[0].strip()
    if len(head) > limit:
        head = head[: limit - 1].rstrip() + "…"
    return head


def _binding_line(entry: Any) -> str:
    """What `binding` means, in the imperative, rather than as a bare word.

    "binding: component" said nothing to anyone who did not already know. It is the answer
    to "how does a component actually get this service's variables?", and the answer is a
    command they have to run: without it the service is configured and provisioned and the
    component still receives nothing, with no warning anywhere.

    `binding` says at which layer the service is *configured*. It does not say whether a
    component can be bound to it, and this line used to claim it did: for
    `binding: deployment` it read "no per-component binding for postgresql-database",
    which flatly contradicted the guide -- and the guide was right. A practice run bound
    postgres, redis and minio to two of three components with `--service` and watched the
    third come up without any `DATABASE_*`. Putting a claim in the registry's mouth that
    the registry never made is worse than saying nothing: two documents that disagree cost
    more than one that is silent.
    """
    where = {
        "component": "configured per component",
        "deployment": "configured per deployment",
        "project": "configured once for the whole project",
    }.get(entry.binding)
    if not where:
        return entry.binding or "-"
    return (
        f"{entry.binding} - {where}; a component receives its variables once you bind it: "
        f"zadctl component add <name> --service {entry.name}"
    )


def _kind_of(entry: Any) -> str:
    """Label a service as system or user, falling back to what `configurable` implies."""
    return entry.kind or ("user" if entry.configurable else "system")


@app.command("list")
def list_services(
    ctx: typer.Context,
    all_services: bool = typer.Option(False, "--all", help="Include hidden services"),
) -> None:
    """List the services this platform offers.

    Hidden services are internal variants the portal does not offer directly; --all shows
    them. Needs no API key: the catalog is project-independent.

    [bold]Example:[/bold]

        $ zadctl service list
    """
    formatter = ctx.obj["formatter"]
    catalog = get_catalog(ctx)
    entries = catalog.visible(include_hidden=all_services)

    if formatter.fmt in ("json", "yaml"):
        formatter.render([{**e.to_dict(), "use": _how_to_use(e)} for e in entries])
        return

    # The targets column holds the layers you can actually write. A layer the registry
    # advertises without an endpoint ("deployment-component (not supported)") reads as a
    # choice in a list of choices; it becomes a footnote instead, where the marker is the
    # message rather than a parenthesis you had to notice.
    rows = [
        {
            "service": e.name,
            "kind": _kind_of(e),
            "binding": e.binding,
            "targets": _targets_cell(e),
            "values": ", ".join(e.value_targets),
            # Targets and values say where a setting lands; neither says which command puts
            # it there, which is the question someone reading this list actually has.
            "use": _use_short(e),
            # The catalog descriptions are full paragraphs; the table is an index, and
            # `service describe` is where the whole text belongs.
            "description": _first_sentence(e.description),
        }
        for e in entries
    ]
    formatter.render(
        rows,
        columns=["service", "kind", "use", "targets", "values", "description"],
        title=f"Services ({catalog.source})",
    )
    marked = [(e.name, e.unwritable_targets()) for e in entries if e.unwritable_targets()]
    if marked:
        from zad_cli.output.formatter import err_console

        err_console.print(
            "[dim]* the registry lists a further layer with no endpoint, so this CLI cannot write it: "
            + "; ".join(f"{name}: {', '.join(layers)}" for name, layers in marked)
            + "[/dim]"
        )


@app.command("types")
def list_service_types(
    ctx: typer.Context,
    all_services: bool = typer.Option(False, "--all", help="Include hidden services"),
) -> None:
    """Alias of `service list`, kept for scripts that already call it.

    [bold]Example:[/bold]

        $ zadctl service types
    """
    list_services(ctx, all_services=all_services)


@app.command()
@handle_api_errors
def add(
    ctx: typer.Context,
    service_name: Annotated[str, typer.Argument(help="Service name", autocompletion=complete_service)],
    components: Annotated[
        list[str] | None,
        typer.Option(
            "--component",
            "-c",
            help="Also bind it to this component. Repeatable.",
            autocompletion=complete_component,
        ),
    ] = None,
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be sent without making the API call"),
) -> None:
    """Select a service for this project, without configuring it.

    This is the step the platform means when it refuses a component with [bold]"Services
    that must be enabled at project level first"[/bold]. Until now the only way to do it
    was `service config set <name>` with an empty body, which is the same call wearing the
    name of a different idea.

    Adding is not configuring: the service is selected with nothing set. Give it settings
    with `zadctl service config set`, and see what it accepts with `zadctl service config
    schema <name>`.

    [bold]Examples:[/bold]

        $ zadctl service add keycloak

        $ zadctl service add redis --component web --component worker
    """
    entry = require_service(ctx, service_name)
    project = require_project(ctx)
    client, formatter = get_helpers(ctx)

    payload: dict = {"service": entry.name}
    if components:
        payload["components"] = list(components)

    if dry_run:
        render_dry_run(formatter, "POST", f"/v2/projects/{project}/services", payload)
        return

    result = client.add_service(project, payload)
    formatter.render(result)
    where = f" and bound to {', '.join(components)}" if components else ""
    formatter.render_success(f"Service '{entry.name}' selected for project '{project}'{where}.")
    surface_warnings(ctx, formatter, result)


@app.command()
@handle_api_errors
def assign(
    ctx: typer.Context,
    service_name: Annotated[str, typer.Argument(help="Service name", autocompletion=complete_service)],
    components: Annotated[
        list[str],
        typer.Option(
            "--component",
            "-c",
            help="Component that should receive this service's variables. Repeatable.",
            autocompletion=complete_component,
        ),
    ],
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be sent without making the API call"),
) -> None:
    """Bind a service to one or more components, so they receive its variables.

    The same act as `zadctl component add --service <name>`, entered from the service
    instead of from the component. Which one reads better depends on what you are doing:
    setting up a component names the component, wiring a database names the database.

    Binding also selects the service for the project when it was not selected yet, so this
    one call is enough for a service that needs no project-level decision. Adding to a
    component that already has it changes nothing and keeps its configuration.

    [bold]Example:[/bold]

        $ zadctl service assign postgresql-database --component backend --component worker
    """
    entry = require_service(ctx, service_name)
    project = require_project(ctx)
    client, formatter = get_helpers(ctx)

    payload = {"service": entry.name, "components": list(components)}

    if dry_run:
        render_dry_run(formatter, "POST", f"/v2/projects/{project}/services", payload)
        return

    result = client.add_service(project, payload)
    formatter.render(result)
    formatter.render_success(f"Service '{entry.name}' bound to {', '.join(components)}.")
    surface_warnings(ctx, formatter, result)


@app.command()
@handle_api_errors
def unassign(
    ctx: typer.Context,
    service_name: Annotated[str, typer.Argument(help="Service name", autocompletion=complete_service)],
    components: Annotated[
        list[str],
        typer.Option(
            "--component",
            "-c",
            help="Component that should stop receiving it. Repeatable.",
            autocompletion=complete_component,
        ),
    ],
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be sent without making the API call"),
) -> None:
    """Unbind a service from one or more components.

    The project keeps the service and every other component keeps it too: only the named
    components stop receiving its variables, and the config that belonged to that binding
    goes with it.

    One call per component, because the API takes the removal on the component. A component
    that did not have the service is left alone rather than reported as an error.

    [bold]Example:[/bold]

        $ zadctl service unassign redis --component worker
    """
    entry = require_service(ctx, service_name)
    project = require_project(ctx)
    client, formatter = get_helpers(ctx)

    payload = {"remove_services": [entry.name]}

    if dry_run:
        for component in components:
            render_dry_run(formatter, "PATCH", f"/v2/projects/{project}/components/{component}", payload)
        return

    confirm_action(
        f"Unbind '{entry.name}' from {', '.join(components)} in project '{project}'?",
        yes,
        ctx,
    )

    for component in components:
        result = client.update_component(project, component, payload)
        formatter.render(result)
        formatter.render_success(f"Service '{entry.name}' unbound from '{component}'.")
        surface_warnings(ctx, formatter, result)


@app.command()
def describe(
    ctx: typer.Context,
    service_name: Annotated[str, typer.Argument(help="Service name", autocompletion=complete_service)],
) -> None:
    """Explain one service: what it does, what you can set, which variables it offers.

    The explanation comes from the platform itself and is in Dutch.

    [bold]Example:[/bold]

        $ zadctl service describe postgresql-database
    """
    from zad_cli.api.registry import UnknownServiceError, load_service

    formatter = ctx.obj["formatter"]
    settings = ctx.obj["settings"]
    require_service(ctx, service_name)  # fail early, naming the valid services

    try:
        entry = load_service(settings.api_url, service_name, refresh=ctx.obj.get("refresh_catalog", False))
    except UnknownServiceError as e:
        raise typer.BadParameter(str(e)) from e

    per_layer = _settings_per_layer(entry, settings.api_url, refresh=ctx.obj.get("refresh_catalog", False), ctx=ctx)

    if formatter.fmt in ("json", "yaml"):
        # `use` is added here too: an agent reading this is exactly the reader who cannot
        # guess that `attachments` is driven by `zadctl attachment` and not by `service config`.
        formatter.render({**entry.to_dict(), "use": _how_to_use(entry), "settings": per_layer})
        return

    formatter.render_detail(
        {
            "service": entry.name,
            "kind": _kind_of(entry),
            "binding": _binding_line(entry),
            "configurable": entry.configurable,
            "use": _how_to_use(entry),
            "config targets": ", ".join(entry.targets_labelled()) or "-",
            "value targets": ", ".join(entry.value_targets) or "-",
            "schema version": entry.config_schema_version or "-",
            "requires": ", ".join(entry.requires) or "-",
        },
        title=entry.name,
    )
    if entry.description:
        formatter.console.print(f"\n{entry.description}\n")
    if entry.explanation:
        from rich.markdown import Markdown

        formatter.console.print(Markdown(entry.explanation))

    # What you can set, and a line that sets it. Without this, `use` names a command and
    # leaves the reader to find its fields in `service config schema` -- one call further
    # on, which is exactly where someone reading a description stops looking.
    for layer, blocks in per_layer.items():
        for block in blocks:
            # The title says how to use the table, so the columns can stay short: without it
            # the reader has a list of names and no sentence putting them on a command line.
            title = "Options, set with --set <option>=<value>"
            if len(entry.targets) > 1:
                title = f"{title}  ({layer} layer)"
            if block["variant"]:
                title = f"{title}  — {block['variant']}"
            # A blank line before the heading: the explanation above it is prose, and prose
            # running straight into a table header reads as one block of text.
            formatter.console.print()
            # `+` rather than a unicode dagger, for the reason this CLI draws ascii tables
            # by default: it survives every terminal, every font and every paste into a
            # ticket -- which is exactly where a value that came from one project ends up.
            cells = [
                {**row, "values": f"{row['values']} +"} if row.get("from_project") else row for row in block["fields"]
            ]
            formatter.render(cells, columns=["option", "values", "default", "description"], title=title)
            if block["example"]:
                formatter.console.print(f"\n  $ {block['example']}")
            # A single example reads as the whole grammar, and the grammar it suggests is
            # one call per setting. It is not just slower: `service config set` writes the
            # document whole, so a second call is a second body, and the first one's
            # settings are gone.
            if block["example_multiple"]:
                formatter.console.print("\n  [dim]or several at once:[/dim]")
                formatter.console.print(f"  $ {block['example_multiple']}")
            if block["example"]:
                formatter.console.print()
    if any(row["option"].endswith(" *") for blocks in per_layer.values() for b in blocks for row in b["fields"]):
        formatter.console.print("[dim]* required[/dim]")
    # The marked values are one project's answer at one moment, printed in the same column
    # as `auto | confirm | manual`, which is a rule for everybody. Naming the project is
    # what keeps the two apart in a transcript.
    if any(row.get("from_project") for blocks in per_layer.values() for b in blocks for row in b["fields"]):
        project = getattr(settings, "project_id", "") or "?"
        formatter.console.print(
            f"[dim]+ from project '{project}', read just now; these values differ per project[/dim]"
        )
    formatter.console.print()
    if entry.variables:
        rows = [
            {
                "variable": v.get("name", ""),
                "description": v.get("description", ""),
                "aliases": ", ".join(v.get("aliases") or []),
                "secret": "yes" if v.get("secret_key") else "",
            }
            for v in entry.variables
        ]
        formatter.render(rows, columns=["variable", "description", "aliases", "secret"], title="Variables")


# --- service config ---


def _template_path(entry: Any, layer: str) -> str:
    """This service+layer as the spec spells it, for looking the request schema up.

    Raises the same usage error as the endpoint itself for a layer the CLI cannot reach.
    This runs first, so leaving it unguarded turned a layer the registry over-advertises
    into a Python traceback before the friendly message ever got a chance.
    """
    from zad_cli.api.registry import MissingLayerError

    try:
        path = entry.config_endpoint(layer, component="{component_name}", deployment="{deployment_name}")
    except MissingLayerError as e:
        raise typer.BadParameter(str(e)) from e
    return path.replace("{project}", "{project_name}")


def _resolve_layer(ctx: typer.Context, service_name: str, target: str | None) -> tuple[Any, str]:
    entry = require_service(ctx, service_name)
    return entry, resolve_target(entry, target)


def _endpoint(entry: Any, layer: str, project: str, component: str | None, deployment: str | None) -> str:
    from zad_cli.api.registry import MissingLayerError

    try:
        path = entry.config_endpoint(layer, component=component, deployment=deployment)
    except MissingLayerError as e:
        raise typer.BadParameter(str(e)) from e
    return path.replace("{project}", project)


@config_app.command("get")
@handle_api_errors
def config_get(
    ctx: typer.Context,
    service_name: Annotated[str, typer.Argument(help="Service name", autocompletion=complete_service)],
) -> None:
    """Show a service's current config, across every layer it is set on.

    [bold]Example:[/bold]

        $ zadctl service config get postgresql-database
    """
    entry = require_service(ctx, service_name)
    project = require_project(ctx)
    client, formatter = get_helpers(ctx)

    result = client.get_service_config(project, entry.name)
    formatter.render_document(result)


@config_app.command("schema")
def config_schema(
    ctx: typer.Context,
    service_name: Annotated[str, typer.Argument(help="Service name", autocompletion=complete_service)],
    target: str = typer.Option(None, "--target", help=_TARGET_HELP),
    skeleton: bool = typer.Option(False, "--generate-skeleton", help="Print an example body instead of the schema"),
    write: str = typer.Option(
        None, "--write", help="Write the schema to this file so an editor can validate your manifest against it"
    ),
) -> None:
    """Print the JSON Schema for a service's config at one layer.

    This is what a tool needs to build a valid body without trial and error. With --write
    the schema lands in a file and the CLI prints the `yaml-language-server` line to put at
    the top of your manifest, which gives editors completion and validation as you type.

    [bold]Examples:[/bold]

        $ zadctl service config schema postgresql-database --target project

        $ zadctl service config schema postgresql-database --write .zad/postgresql-database.json
    """
    import json
    from pathlib import Path

    from zad_cli.api import spec

    formatter = ctx.obj["formatter"]
    entry, layer = _resolve_layer(ctx, service_name, target)

    schema = spec.request_schema("PUT", _template_path(entry, layer))
    if schema is None:
        raise typer.BadParameter(f"The vendored API spec documents no request body for {entry.name} ({layer}).")

    if write:
        path = Path(write).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        # $schema and a title make the file usable on its own, not just as a fragment.
        document = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": f"{entry.name} config ({layer})",
            **schema,
        }
        path.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n")
        formatter.render_success(f"Schema written to {path}.")
        formatter.render_success(
            f"Add this line at the top of your manifest:\n  # yaml-language-server: $schema={path}"
        )
        return

    formatter.render_document(render_skeleton(schema) if skeleton else schema)


@config_app.command("set")
@handle_api_errors
def config_set(
    ctx: typer.Context,
    service_name: Annotated[str, typer.Argument(help="Service name", autocompletion=complete_service)],
    target: str = typer.Option(None, "--target", help=_TARGET_HELP),
    component: Annotated[
        str | None,
        typer.Option("--component", "-c", help="Component, for a component layer", autocompletion=complete_component),
    ] = None,
    deployment: Annotated[
        str | None,
        typer.Option("--deployment", help="Deployment, for a deployment layer", autocompletion=complete_deployment),
    ] = None,
    file: str = typer.Option(None, "--file", "-f", help="YAML/JSON manifest with the config body ('-' for stdin)"),
    sets: Annotated[
        list[str] | None,
        typer.Option("--set", help="Set a field: dotted.path=value, repeatable. Wins over --file."),
    ] = None,
    generate_skeleton: bool = typer.Option(
        False, "--generate-skeleton", help="Print an example body for this layer and exit"
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be sent without making the API call"),
) -> None:
    """Write a service's configuration at one layer.

    Values come from a manifest, from --set flags, or both; --set wins, the way Helm
    treats them.

    A service with more than one layer asks for --target, and fails without it: writing
    project-wide config when a deployment override was meant is not something a default
    may decide. `zadctl service describe <name>` lists the layers it takes.

    [bold]Example:[/bold]

        $ zadctl service config set postgresql-database --set scope=project

        $ zadctl service config set minio-storage --target project
    """
    from zad_cli.api import spec
    from zad_cli.manifest import validate_against_schema

    formatter = ctx.obj["formatter"]
    entry, layer = _resolve_layer(ctx, service_name, target)
    schema = spec.request_schema("PUT", _template_path(entry, layer))

    if generate_skeleton:
        if schema is None:
            raise typer.BadParameter(f"The vendored API spec documents no request body for {entry.name} ({layer}).")
        formatter.render_document(render_skeleton(schema))
        return

    payload: Any = load_payload_file(file) if file else None
    if sets:
        payload = apply_sets(payload if payload is not None else {}, sets)
    if payload is None:
        # An empty body means "use this service, with nothing set", which the API accepts
        # and which several services need: publish-on-web or persistent-storage are mostly
        # switched on rather than configured. Refusing it here made selecting a service
        # possible only through `echo {} | ... -f -`. A service that does need fields is
        # still caught, by the schema check below, which names the fields.
        payload = {}

    # Resolve the endpoint first: a missing --component is a more basic mistake than a
    # field being wrong, and reporting the body error first hides it.
    project = require_project(ctx)
    path = _endpoint(entry, layer, project, component, deployment)

    if schema is not None:
        validate_against_schema(payload, schema, what=f"{entry.name} ({layer}) config")

    client, formatter = get_helpers(ctx)

    patch_template = _template_path(entry, layer)
    _warn_if_whole_list(
        formatter,
        schema,
        payload,
        entry.name,
        layer,
        component,
        has_patch=spec.request_schema("PATCH", patch_template) is not None,
    )

    if dry_run:
        render_dry_run(formatter, "PUT", path, payload if isinstance(payload, dict) else {"body": payload})
        return

    result = client.put_service_config(path, payload)
    formatter.render(result)
    formatter.render_success(f"Service '{entry.name}' configured at layer '{layer}'.")
    surface_warnings(ctx, formatter, result)


@config_app.command("patch")
@handle_api_errors
def config_patch(
    ctx: typer.Context,
    service_name: Annotated[str, typer.Argument(help="Service name", autocompletion=complete_service)],
    target: str = typer.Option(None, "--target", help=_TARGET_HELP),
    component: Annotated[
        str | None,
        typer.Option("--component", "-c", help="Component, for a component layer", autocompletion=complete_component),
    ] = None,
    deployment: Annotated[
        str | None,
        typer.Option("--deployment", help="Deployment, for a deployment layer", autocompletion=complete_deployment),
    ] = None,
    file: str = typer.Option(
        None,
        "--file",
        "-f",
        help="YAML/JSON manifest with the patch body {'add': [...], 'remove': [...]} ('-' for stdin)",
    ),
    sets: Annotated[
        list[str] | None,
        typer.Option(
            "--set", help="Set a field: dotted.path=value, repeatable (e.g. --set add[0].name=data). Wins over --file."
        ),
    ] = None,
    remove: Annotated[
        list[str] | None,
        typer.Option(
            "--remove", help="Key of an entry to remove, repeatable. Added to any 'remove' list from -f/--set."
        ),
    ] = None,
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be sent without making the API call"),
) -> None:
    """Add, replace or remove single entries of a list-shaped config block.

    `config set` writes such a block whole: an entry you do not mention is removed. This
    is the endpoint behind the warning `config set` prints for a list: `add` takes full
    entries (a key that exists is replaced, a new one appended), `remove` takes keys only
    (an unknown one is a no-op), so one volume or coupling changes without resending the
    rest. Only layers whose config is a list offer it; where the spec documents no PATCH,
    this command says so instead of sending anything.

    Removing a volume removes what it holds: a storage entry leaves with its PVC and the
    data on it, which is why a `remove` asks first.

    [bold]Examples:[/bold]

        $ zadctl service config patch persistent-storage --component web --remove oude-data

        $ zadctl service config patch persistent-storage --component web \
            --set add[0].name=data --set add[0].size=1Gi --set add[0].mount-path=/data

        $ zadctl service config patch persistent-storage --component web -f patch.yaml
    """
    from zad_cli.api import spec
    from zad_cli.manifest import validate_against_schema

    entry, layer = _resolve_layer(ctx, service_name, target)
    template = _template_path(entry, layer)
    schema = spec.request_schema("PATCH", template)
    if schema is None:
        raise typer.BadParameter(
            f"'{entry.name}' has no per-entry patch at layer '{layer}': this config block is written whole. "
            f"Use `zadctl service config set {entry.name} --target {layer}`."
        )

    project = require_project(ctx)
    path = _endpoint(entry, layer, project, component, deployment)
    client, formatter = get_helpers(ctx)

    payload: Any = load_payload_file(file) if file else {}
    if sets:
        payload = apply_sets(payload, sets)
    if not isinstance(payload, dict):
        raise typer.BadParameter(f"A patch body is a mapping with 'add' and/or 'remove', got {file}.")
    if remove:
        payload["remove"] = [*(payload.get("remove") or []), *remove]
    if not payload.get("add") and not payload.get("remove"):
        raise typer.BadParameter(
            "Nothing to patch: pass --remove <key>, add entries with --set add[0].field=value, "
            "or -f with a {'add': [...]} / {'remove': [...]} body."
        )

    validate_against_schema(payload, schema, what=f"{entry.name} ({layer}) patch")

    if dry_run:
        render_dry_run(formatter, "PATCH", path, payload)
        return

    removing = payload.get("remove") or []
    if removing:
        confirm_action(
            f"Remove {', '.join(str(r) for r in removing)} from the {entry.name} config of "
            f"'{component or deployment or project}'?",
            yes,
            ctx,
        )

    result = client.patch_service_config(path, payload)
    formatter.render(result)
    formatter.render_success(f"Service '{entry.name}' config patched at layer '{layer}'.")
    surface_warnings(ctx, formatter, result)


def _warn_if_whole_list(
    formatter: Any,
    schema: dict[str, Any] | None,
    payload: Any,
    service: str,
    layer: str,
    component: str | None,
    has_patch: bool = False,
) -> None:
    """Say it before the write when this config block is a list.

    Some config blocks are a list rather than an object. The endpoint is a PUT, so it writes
    the block whole, and an entry left out is removed -- which is not obvious from a command
    called `set` that takes the entries you happen to be thinking about. The first person to
    ask how to remove one of two volumes was the one who found this out.

    What that removal costs is not the same everywhere, and RIG-Cluster measured it
    (question 18 in their plans/vragen-uit-zad-cli.md): a storage mount that leaves the list
    while the component stays takes its PVC with it, pruned by ArgoCD, and their own code
    says that prunes "the PVC and its data immediately". An attachment that leaves loses only
    its coupling; the file stays in the project catalogue. So the warning names the kind of
    thing rather than a list of services -- which is also the rule: the catalog is the source
    of truth and no module may enumerate it.

    Said in front of the call, not after: afterwards the other entry is already gone. There
    is deliberately no read-modify-write behind this to spare you the trouble; a hidden merge
    that can lose a race is a bad trade when the thing at stake is a volume with data on it.
    The API answered question 18 with a PATCH that adds and removes one entry at a time, and
    `service config patch` is that endpoint: where the spec offers it for this layer, the
    warning says so, so nobody has to rewrite a list to change one entry.
    """
    if not schema or schema.get("type") != "array":
        return
    entries = len(payload) if isinstance(payload, list) else 0
    where = f" --component {component}" if component else ""
    formatter.render_warning_text(
        f"{service} ({layer}) is a list, and this writes it whole: "
        f"{entries} entr{'y' if entries == 1 else 'ies'}. An entry not named here is removed, and what "
        f"that costs depends on what it is: a storage volume goes with the data on it (the PVC is "
        f"pruned), an attachment loses only its coupling.\n"
        f"  Read the current list first with: zadctl service config get {service}"
        f" --target {layer}{where} -o yaml"
    )
    if has_patch:
        formatter.render_warning_text(f"  One entry at a time: zadctl service config patch {service}{where}")
    if service == "attachments":
        # The one list-shaped block this CLI has its own verbs for; naming them beats
        # sending someone to build a config document by hand.
        formatter.render_warning_text("  One coupling at a time: zadctl attachment assign / zadctl attachment unassign")


@config_app.command("clear")
@handle_api_errors
def config_clear(
    ctx: typer.Context,
    service_name: Annotated[str, typer.Argument(help="Service name", autocompletion=complete_service)],
    target: str = typer.Option(None, "--target", help=_TARGET_HELP),
    component: Annotated[
        str | None,
        typer.Option("--component", "-c", help="Component, for a component layer", autocompletion=complete_component),
    ] = None,
    deployment: Annotated[
        str | None,
        typer.Option("--deployment", help="Deployment, for a deployment layer", autocompletion=complete_deployment),
    ] = None,
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be sent without making the API call"),
) -> None:
    """Remove a service's configuration at one layer.

    [bold]Example:[/bold]

        $ zadctl service config clear publish-on-web --component web
    """
    entry, layer = _resolve_layer(ctx, service_name, target)
    project = require_project(ctx)
    path = _endpoint(entry, layer, project, component, deployment)
    client, formatter = get_helpers(ctx)

    if dry_run:
        render_dry_run(formatter, "DELETE", path)
        return

    confirm_action(f"Clear {entry.name} config at layer '{layer}' in project '{project}'?", yes, ctx)

    result = client.delete_service_config(path)
    formatter.render(result)
    formatter.render_success(f"Service '{entry.name}' config cleared at layer '{layer}'.")
    surface_warnings(ctx, formatter, result)
