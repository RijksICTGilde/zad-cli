# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

## What is zad-cli?

zad-cli is a CLI for ZAD (Zelfservice Applicatie Deployment), the self-service Kubernetes deployment platform used by the Dutch government (RijksICTGilde). It wraps the Operations Manager REST API (v2 async endpoints).

The goal: **the CLI can do everything the web UI can**, and an agent can discover what ZAD offers through the CLI without any built-in knowledge. That goal, met against an API that has stopped moving, is what 1.0 is for; until then this is a 0.x.

### The three ideas it is built on

1. **The API is a registry.** `GET /api/v2/services` says which services exist and what you can configure on each; `GET /api/v2/services/{name}` describes one in full, including the Dutch `explanation` and the `config_endpoint` per layer. Both are public: no project, no API key. **The registry is the source of truth, not the CLI.** No module may carry a list of service names.
2. **Configuration sits in layers per service**: `project`, `component`, `deployment` (and `deployment-component` for values). Which layers a service accepts comes from the registry, never from the CLI.
3. **Saving and rolling out are two things.** `rollout` is a query parameter on most mutating operations, with `zadctl project pending` next to it. `--no-rollout` saves the change and leaves the cluster alone until `zadctl project refresh`.

## Commands

```bash
uv sync                # Install
uv run pytest          # Run tests
uv run ruff check .    # Lint
uv run ruff format .   # Format
uv run zadctl --help      # Run the CLI
```

## Architecture

Typer-based CLI with noun-verb command structure (`zadctl deployment create`, `zadctl component add`).

- **cli.py** - Typer app, global options (--output, --api-key, --api-url, -p, --no-wait, --verbose, --rollout/--no-rollout, --refresh-catalog, --strict). Loads `.env` at startup. `guide`, `logs`, `login`, `logout` and `version` are direct commands (not sub-apps).
- **helpers.py** - Shared `get_helpers()`, `require_project()`, `require_service()`, `get_catalog()`, `resolve_target()`, `render_dry_run()` used by all command modules
- **settings.py** - Resolves settings: flags > exported environment variables > the env file in the working directory > defaults. `SETTING_DOCS` says the same thing once as data (flag, env vars, config key, default) for `zadctl guide`
- **guide.py** - `zadctl guide`: the whole CLI in one call. The command tree comes from Click, the examples from the docstrings that already carry them, the services from the registry and the settings from `SETTING_DOCS`. Only what is derivable from none of those is written out, in that module. Adding a list of commands, flags or service names here is what `tests/test_guide.py` exists to stop
- **envfile.py** - The one file this CLI writes: the env file in the directory you run from. It owns the filename, the 0600 mode, the `setting -> ZAD_*` mapping (`ENV_VARS`), which variables are secret, and the git-ignore check. Nothing is written under `~`, because a single store there has one active project and two checkouts then fight over it
- **config.py** - The named-setting layer on top of `envfile.py`, so `zadctl config set rollout false` writes `ZAD_ROLLOUT` and not a key nothing reads. `KNOWN_KEYS` is a closed set: `config set` refuses anything else, because a file is a bad place to find out that `ZAD_ROLOUT=false` did nothing. Values are validated where they are written, not where they are read, since this file is written once and read on every later run
- **picker.py** - The arrow-key list (`zadctl project use` without a name). Rich draws it, the terminal's raw mode delivers the keys, everything goes to stderr; a numbered prompt is the fallback without raw mode
- **credentials.py** - The secrets in that same env file: the project API key, the SSO access and refresh token, the active project. `store_api_key` writes the project, its key and the API URL together, because a key means nothing against a different API. An expired access token is refreshed silently on read
- **auth.py** - SSO login against Keycloak: device grant first, authorization code + PKCE on a `127.0.0.1` listener as fallback. Which Keycloak is a *setting* (never derived from the API host); the scope to ask with comes from the realm's `scopes_supported`, and a token without `zad-api` in `aud` is refused rather than stored
- **manifest.py** - `-f/--file`, `--set dotted.path=value`, `@file` values, `--generate-skeleton`, and the local schema check that names the field path
- **commands/** - One file per command group:
  - project (list, create, use/select, describe, status, refresh, pending, delete, subdomains, check-subdomain)
  - deployment (list, url, describe, create, assign, update-image, refresh, delete)
  - component (list, add, assign, update, delete)
  - service (list, types, describe, add, assign, unassign) and service config (get, set, patch, clear, schema)
  - attachment (list, add, assign, update, delete)
  - values.py → env and alias (list, get, add, set, unset, clear): one factory, two services
  - db (schema list/add/remove), registry (add)
  - resource (tune, sanitize), task (wait, status, list, cancel)
  - backup (create, list, status, delete)
  - restore (list, project, backup, pvc, database, deployment, pvc-snapshots, bucket)
  - clone (database, bucket, check), logs
  - config_cmd (init, set, get, unset, list, path), open_cmd (project, portal, domains), login (login, logout), guide (guide)
- **api/registry.py** - The service catalog: fetch, cache per API URL (24h TTL, `--refresh-catalog`), bundled snapshot fallback, and deriving each layer's config/values endpoint
- **api/spec.py** - Reads the vendored OpenAPI spec: which operations accept `rollout`, and each operation's request schema
- **api/client.py** - httpx client with retry logic and verbose mode. Mutating ops use v2 async endpoints (return 202, poll via /api/tasks/{id})
- **api/models.py** - Pydantic request/response models (UpsertDeploymentRequest, CloneDatabaseRequest, CloneBucketRequest, etc.)
- **output/formatter.py** - Output: table (Rich), json, yaml. Data to stdout, status to stderr. `formatter.console` is the public Rich Console instance.

## CLI Design Principles

These are binding rules. Every new command must follow them. The automated API sync agent and any contributor must treat these as non-negotiable.

### Noun-verb command structure

Commands follow `zadctl <noun> <verb>` (e.g. `zadctl deployment create`, `zadctl service config set`). One file per noun group in `commands/`. Register sub-apps in `cli.py`. Exceptions: `guide`, `logs`, `login`, `logout` and `version` are direct commands on the root app.

**The entry point is `zadctl service <name>`, and the root does not grow a keyword per
service.** Everything in `zadctl service list` is reachable under `zadctl service <name>`.
Services with one config document per layer use the generic `zadctl service config`; the ones
that carry a *set of entries* (`attachments`, `user-env-vars`, `aliases`, `persistent-storage`,
`temp-storage`) need their own verbs, because "add this volume" is not expressible as "set
this document" -- and because the generic setter writes the block whole, so naming one entry
removes the others. Those groups are registered under `service` by the name the catalog shows.
`tests/commands/test_service_config.py` enforces the reachability.

`zadctl attachment`, `zadctl env` and `zadctl alias` are the same apps registered a second
time at the root. They stay, and **nothing joins them**: a root that grows one keyword per
service becomes a list nobody can hold in their head, and the registry keeps growing. Storage
is the first group to land under `service <name>` only, which is the shape from here on.
`zadctl service list` is the index.

### Verb vocabulary

Use these verbs with their exact semantics:

| Verb | Meaning | Example |
|------|---------|---------|
| `list` | List all resources | `project list`, `task list` |
| `create` | Create a new top-level resource | `deployment create`, `backup create` |
| `add` | Attach something to an existing resource | `component add`, `env add` |
| `delete` | Remove a resource (NEVER `remove`, `drop`, `rm`) | `deployment delete`, `component delete` |
| `describe` | Show detailed single-resource info | `deployment describe` |
| `status` | Show current state | `project status`, `backup status` |
| `refresh` | Re-fetch from source (git) | `project refresh`, `deployment refresh` |
| `update-image` | Mutate a specific field | `deployment update-image` |
| `check` | Read-only validation | `clone check`, `project check-subdomain` |
| `assign` | Bind one resource to another | `component assign`, `deployment assign`, `attachment assign` |
| `unassign` | Unbind, keeping both resources | `service unassign`, `attachment unassign` |
| `patch` | Touch single entries of a list-shaped config block, leaving the rest | `service config patch` |
| `describe` | Show one resource in full | `service describe` |
| `set` | Change something that exists | `service config set`, `env set` |
| `clear` | Remove everything at one layer | `service config clear`, `env clear` |
| `unset` | Remove one or more named values | `env unset`, `alias unset` |
| `pending` | Show what is saved but not rolled out | `project pending` |
| `use` | Choose what later commands act on | `project use` |

`add` and `set` are not synonyms where the API distinguishes them: on values, `add` is a
POST that rejects an existing key and `set` is a PATCH that requires one. Do not collapse
two endpoints into one verb because they look similar from the outside.

Multi-word commands use kebab-case: `update-image`, `check-subdomain`.

### Argument rules

**Positional arguments** identify the primary target resource:
- Deployment name: always positional when targeting a single deployment (`zadctl deployment delete <name>`, `zadctl backup create <deployment>`)
- Component/service name: positional when targeting a single item (`zadctl component delete <name>`, `zadctl service describe <name>`)
- Task ID: positional (`zadctl task status <id>`)
- Never use `-d` to identify a deployment target. `-d` is only a filter option on list commands.

**Options** for everything else:
- `--target` picks the config layer (`project`, `component`, `deployment`). Optional when the service has exactly one layer; **required, never defaulted, when it has more than one**. Writing project-wide config when a deployment override was meant is not something a default may decide.
- `-f/--file` is a *manifest*: the whole request body, as YAML or JSON, `-` for stdin.
- `--from-file` is a *payload*: the content of one thing (an attachment's bytes, a mapping of values). `-f` may alias it when it is the only file input of that command.
- `--set dotted.path=value` sets one field, is repeatable, and wins over `--file`.
- `--mount-path`, never `--path`: `--path` already means *ingress path* elsewhere in this CLI.
- `--component, -c` for component references (repeatable where needed)
- `--deployment` (long form only, no `-d`) when repeatable (`component add --deployment a --deployment b`)
- `--image` for container image URLs
- Filter options on list commands: `--status, -s`, `--filter-project` (not `--project` to avoid collision with global `-p`)

**Required options** use `typer.Option(...)` with ellipsis. Optional ones use `typer.Option(None, ...)` or a default value.

### Destructive and mutating commands

Every command that changes state must have:
1. `--dry-run` flag: calls `render_dry_run(formatter, method, endpoint, payload)` and returns. Check dry-run BEFORE confirmation.
2. `@handle_api_errors` decorator on the command function.
3. Success message via `formatter.render_success(f"Component '{name}' added.")` after the operation.

Read-only commands (`list`, `describe`, `status`, `check`, `schema`) need neither.

**Only removal asks.** A command gets `--yes, -y` and a `confirm_action(message, yes, ctx)`
call when it takes something away, or writes older data over it: the `delete` and `remove`
verbs, `clear`, `unset`, the `restore` commands and the `admin` purges. Adding, setting,
updating and creating just act, `deployment create` included even though it is an upsert. Thirty-two confirmations spread over everything trained
people to answer "y" without reading, and that habit is worth more than the prompts it
defeats. `tests/commands/test_confirmations.py` pins both halves of the rule, so a new
prompt on an `add` fails the build.

`confirm_action` takes the context so that `--yes`, `ZAD_YES` and `zadctl config set yes true`
all silence it; a script or an agent then never meets a prompt at all. And `--yes` without
`--dry-run` is refused by `tests/test_uniformity.py`: a command you must confirm is one you
want to rehearse first.

### Services come from the registry

Never write a service name into a list, a validator, or an endpoint table.

- Resolve a name with `require_service(ctx, name)`; it fails naming the valid services.
- Pick a layer with `resolve_target(entry, target)`.
- Build the endpoint with `entry.config_endpoint(layer, ...)` or `entry.values_endpoint(...)`, which prefer the `config_endpoint` the API publishes per layer and otherwise follow the documented path pattern.
- Get a body's schema from `api/spec.py`, not from a hand-written model.

`tests/test_registry.py` fails the build if any module names two or more services on one line. A single name is allowed only where the command genuinely acts on that one service (`deployment update-image --recreate-storage`, `zadctl db schema`, `zadctl env`/`zadctl alias`).

### Rollout

`--rollout` and `--no-rollout` are global, and the Typer option is `bool | None`: only that
keeps "the user typed `--rollout`" apart from "nobody said anything", which is what makes
the layering work. `Settings.resolve()` decides it (**flag > `ZAD_ROLLOUT` > the env file's
`ZAD_ROLLOUT` > `true`**) and records the winning layer in `Settings.sources`, which is what
`zadctl config list` shows. The client adds the `rollout` query parameter only to operations
the vendored spec says accept it, never from a list in the code. After a mutation that did
not roll out, the CLI says how many changes are waiting and how to roll them out.

### Authentication

Every project-scoped call uses `X-API-Key`. `project list` and `project create` are the two exceptions: they take `Authorization: Bearer <SSO token>`, because you need the project name before you can have its key. Both responses carry API keys, so mask them in table output, store them in the env file, and never log them. `--verbose` prints method, path, body and params, never headers.

### Project handling

Most commands need a project. Get it via `project = require_project(ctx)`. The project comes from the global `-p` flag or `ZAD_PROJECT_ID` env var. Do not add a per-command project option.

Exceptions that don't require project: `project list`, `project check-subdomain`, `service types`, admin/restore operations that take cluster/namespace directly.

### Output conventions

All commands must respect `--output` (table/json/yaml):
- Use `client, formatter = get_helpers(ctx)` at the top of every command.
- Lists: `formatter.render(rows, columns=[...], title="...")`
- Single item: `formatter.render(data)` or `formatter.render_detail(data)`
- Text output: `formatter.render_text(text)` (for logs)
- Data goes to stdout. Status/progress messages go to stderr.
- Empty results show `[dim]No results.[/dim]` in table mode.

### Help text format

```python
"""Brief one-line description shown in command list.

Longer description if needed.

[bold]Example:[/bold]

    $ zadctl service config clear postgresql-database
"""
```

- First line: brief, shown in `--help` command list
- Use Rich markup (`[bold]`, `[/bold]`) for formatting
- Include at least one example with `$ zadctl ...`. `guide.py` lifts the examples out of these docstrings by that prefix, so a command without one lands in the guide with an empty example list
- Group-level help includes: `"Requires ZAD_API_KEY and ZAD_PROJECT_ID (or --api-key and -p)."`
- Do NOT repeat the API key requirement in individual command help

### Command implementation template

Every new command follows this skeleton (see `commands/service.py` for a clean example):

```python
@app.command()
@handle_api_errors
def verb(
    ctx: typer.Context,
    target: str = typer.Argument(help="..."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be sent without making the API call"),
) -> None:
    """Brief description."""
    project = require_project(ctx)
    client, formatter = get_helpers(ctx)

    if dry_run:
        render_dry_run(formatter, "METHOD", f"/v2/projects/{project}/...", payload)
        return

    confirm_action(f"Action on '{target}' in project '{project}'?", yes)

    result = client.method(project, ...)
    formatter.render(result)
    formatter.render_success(f"Target '{target}' verbed.")
    surface_warnings(ctx, formatter, result)  # mutating ops: flag degraded-but-successful state
```

### Error reporting (the diagnosis layer)

Errors must give **clarity and a next step**: say what's wrong, point neutrally at
where to look, and suggest the fix. The machinery lives in `api/errors.py`:

- **`Fault`** (StrEnum): `USER_INPUT`, `USER_APP`, `USER_CONFIG`, `AUTH`, `PLATFORM`,
  `NETWORK`, `UNKNOWN`. Drives a neutral source label (`FAULT_SOURCE`), color
  (`FAULT_COLOR`), and CI/CD exit code (`FAULT_EXIT_CODE`: 1 = your fault, 2 =
  platform/transient, 3 = unknown/unattributable).
- **`Diagnosis`** (dataclass): `fault`, `headline`, `summary`, `details`, `next_steps`,
  `status_code`. `to_dict()` is the json contract (CI branches on `fault`).
- **`diagnose_http_error`** parses status codes and FastAPI `422` validation arrays;
  **`diagnose_task_failure`** digs into `processing.component_failures`, `error_type`,
  and `ErrorCategory`; **`degraded_diagnoses`** catches "succeeded but unhealthy".

Rules for new code:
- The client raises `ZadApiError` / `TaskFailedError` / `TaskTimeoutError` with a
  `.diagnosis` attached (build it at the raise site via the `diagnose_*` helpers or
  `_http_error`). `handle_api_errors` renders it and exits with `diagnosis.exit_code`.
- Render failures with `formatter.render_diagnosis(d)`, degraded-success with
  `formatter.render_warnings(diags)`. Diagnostics go to **stderr**; json error objects
  go to stdout. Never hardcode an error string where a `Diagnosis` belongs.
- After any mutating op, call `surface_warnings(ctx, formatter, result)` so warnings /
  unhealthy components are surfaced (and `--strict` can fail CI).
- **Honesty:** when the API gives no category, the fault is `UNKNOWN` and we point at
  the logs (exit code 3); don't guess whose fault it is.

**Spec coupling:** `CATEGORY_FAULT` / `CATEGORY_HINT` are keyed by `ErrorCategory`, and
`tests/test_spec_conformance.py` asserts the enum matches `api/upstream-openapi.json` and
that every category is mapped. When the api-sync workflow surfaces a new `ErrorCategory`,
add it to `models.ErrorCategory` **and** both maps; the conformance test tells you.

### Client method conventions

- One public method per API endpoint on `ZadClient`
- V2 (async) endpoints: use `self._async_request(method, path, ...)` - returns dict, handles polling
- V1 (sync) endpoints: use `self._request(method, path, ...)` - returns `httpx.Response`, caller calls `.json()`
- Method name matches the CLI verb: `delete_deployment`, `add_service`, `backup_project`
- Path parameters as positional args, request body as `payload: dict`, query params as keyword args

### Specific conventions

- `deployment create` is an upsert, and does *not* confirm: creating is not taking
  something away. It still accepts `--yes` so that callers passing it keep working
- `check-subdomain` lives under `project` group (not `deployment`)
- `clone check` validates configuration without executing (read-only)
- `task list` uses `--filter-project` (not `--project`) to avoid collision with global `-p`
- `restore database/bucket` take deployment name (like backup) and resolve namespace internally via `client.resolve_namespace()`
- `service types` is kept as an alias of `service list` for scripts that already call it
- `zadctl env` and `zadctl alias` are both built by `commands/values.py`; a third key/value service costs one line
- `attachment add` writes the catalog, `attachment assign` writes the coupling: the mount path belongs to the coupling, so the same file can land elsewhere per component
- `deployment assign` is `component assign` entered from the deployment's side: same endpoint, same required `--image`, because the image lives on the coupling
- There is deliberately no `component unassign` / `deployment unassign` and no `service delete`: the deployment upsert *merges* its component list and never removes an entry, and the project-level service removal endpoint was withdrawn upstream. Do not fake either with a hidden read-modify-write; `service unassign` + `service config clear` per layer is the honest recipe, and `component delete --force` removes a definition project-wide
- `admin cleanup` and `admin reconcile` default to a dry run, like the API; `--apply` is what actually changes something
- Autocompletion: use `complete_deployment`, `complete_component` and `complete_service` callbacks from `helpers.py` on relevant arguments

## Configuration

Precedence: flags > exported environment variables > the env file in the working directory > defaults

There is one file and no layer under `~`. The env file holds both the settings and the
secrets, which is why `envfile.py` writes it 0600 and why `config list` warns when git would
not ignore it. Add a setting by adding a `SettingDoc` to `SETTING_DOCS` and its variable to
`ENV_VARS`, not by writing this table out again somewhere: the table below is a summary,
`SETTING_DOCS` is the source.

| Setting | Flag | Env var | Config key | Default |
|---------|------|---------|-----------|---------|
| API key | `--api-key` | `ZAD_API_KEY` | - | the stored key for this directory's project |
| Project | `-p` / `--project` | `ZAD_PROJECT_ID` | - | the active project set by `zadctl project use` |
| API URL | `--api-url` | `ZAD_API_URL` | `api_url` | the production URL |
| Output | `-o` / `--output` (`--json`, `--yaml`) | `ZAD_OUTPUT_FORMAT` | `output` | `table` |
| Table style | - | `ZAD_TABLE_STYLE` | `table_style` | `ascii` |
| Roll out | `--rollout` / `--no-rollout` | `ZAD_ROLLOUT` | `rollout` | `true` |
| Confirm | `--yes` / `-y`, per command | `ZAD_YES` | `yes` | `false` (ask) |
| Keycloak URL | `--keycloak-url` | `ZAD_KEYCLOAK_URL` | `keycloak_url` | `https://keycloak.rijksapp.nl` |
| Keycloak realm | `--keycloak-realm` | `ZAD_KEYCLOAK_REALM` | `keycloak_realm` | `rig-platform` |
| Keycloak client | `--keycloak-client-id` | `ZAD_SSO_CLIENT_ID` / `ZAD_KEYCLOAK_CLIENT_ID` | `keycloak_client_id` | `zad-cli` |
| SSO issuer | - | `ZAD_SSO_ISSUER` | - | composed: `{keycloak_url}/realms/{keycloak_realm}` |
| SSO token | `zadctl login --token` | `ZAD_SSO_TOKEN` | - | stored by `zadctl login` |
| Task timeout / poll | - | `ZAD_TASK_TIMEOUT`, `ZAD_TASK_POLL_INTERVAL` | - | `300`, `3` |
| Retries | - | `ZAD_MAX_RETRIES`, `ZAD_RETRY_DELAY` | - | `3`, `2` |
| Catalog offline | `--refresh-catalog` forces a fetch | `ZAD_CATALOG_OFFLINE` | - | cached 24h |

`config list` shows every setting in effect with the layer that decided it (from
`Settings.sources`), plus the contents of the env file, so a value that is being overruled
does not look like a bug. Secrets appear as `(set)` and never as themselves. `zadctl project use`
writes the project and its key together, and what it sets is a *fallback*: `-p` and
`ZAD_PROJECT_ID` still win.

## Testing

- `respx` for httpx mocking (test_client.py) and for command tests via `typer.testing.CliRunner`
- `subprocess` for CLI integration tests (test_cli.py)
- `capsys` for output tests (test_output.py)

**No real API calls in tests, and no reading of your own settings.** `tests/conftest.py`
enforces both for every test: it chdirs into a temporary directory, which is what isolates
the env file since that is the only thing the CLI writes, clears every `ZAD_*` variable the
CLI reads so an exported one cannot decide what the suite tests, and sets
`ZAD_CATALOG_OFFLINE=1` so the service catalog comes from the snapshot bundled at
`src/zad_cli/data/services-snapshot.json` instead of the network. Tests that exercise
catalog fetching opt out and mock it with respx.

Refresh the snapshot together with the spec:

```bash
python scripts/fetch_openapi.py --url https://zad.sandbox.rijksapp.dev/api --key <key>
curl -s https://zad.sandbox.rijksapp.dev/api/v2/services > src/zad_cli/data/services-snapshot.json
python scripts/check_coverage.py
```

## Compatibility policy

**Additive by default, and this is a 0.x.** Other teams pin a version of this CLI, so the
default is that nothing goes away:

- **No removing** CLI commands, options, or positional arguments
- **No renaming** commands or flags
- **No changing** argument positions or types
- **Additive changes only**: new commands, new options, new output fields
- **Same rules for `ZadClient`**: no removing public methods, no breaking signature changes, only new methods and new optional kwargs

Being on 0.x is what makes an exception possible without a ceremony around it. Three of
them landed in the four days around 12 August, and each was the same discovery: a command
that had never worked. `service add` and `service delete` called endpoints withdrawn
upstream; the three `restore_*` client methods never sent the body their endpoints require;
`project list --show-keys` could put every key you hold into a transcript. Preserving any of
those would have meant preserving a bug.

**1.0 is for later**: when the goal at the top is met and the API this wraps has stopped
moving. Promising "additive within a major" while the thing underneath still changes weekly
is promising something we do not control.

When something is removed:

1. Edit the baseline in `tests/test_backwards_compat.py`, never deleting a line silently.
2. Add it to `REMOVED_COMMANDS` with what replaced it. The test then checks the command is really gone, so a half-removal cannot ship.
3. Say so in `CHANGELOG.md` and `README.md`, and say *why*: "this never worked" and "we changed our mind" deserve different amounts of sympathy from whoever is upgrading.

`tests/test_backwards_compat.py` checks the CLI command tree and the client method list
against that baseline. CI fails if anything disappears without the baseline being edited.

### Downstream consumers

`zad-actions` pins zad-cli on one line (`scripts/zad-common.sh` → `ZAD_CLI_VERSION`) and uses
`deployment create` and `deployment delete`. Both still work; check this explicitly before
touching the `deployment` group.

## API Monitoring

The upstream Operations Manager API (repo: `RijksICTGilde/RIG-Cluster`) is a FastAPI app with an auto-generated OpenAPI spec at `/openapi.json`.

A scheduled GitHub Actions workflow (`.github/workflows/api-sync.yml`) runs daily on weekdays:
1. Fetches the latest OpenAPI spec from the deployed instance
2. Diffs it against `api/upstream-openapi.json` using [oasdiff](https://github.com/oasdiff/oasdiff)
3. Runs `scripts/check_coverage.py` to find upstream endpoints not yet covered by the CLI
4. If gaps are found, Claude implements new client methods, CLI commands, and tests
5. Creates a PR for human review

Breaking upstream changes get flagged with a `breaking-api-change` label but are not auto-implemented.
