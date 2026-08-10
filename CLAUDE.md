# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

## What is zad-cli?

zad-cli is a CLI for ZAD (Zelfservice Applicatie Deployment), the self-service Kubernetes deployment platform used by the Dutch government (RijksICTGilde). It wraps the Operations Manager REST API (v2 async endpoints).

The goal of 1.0: **the CLI can do everything the web UI can**, and an agent can discover what ZAD offers through the CLI without any built-in knowledge.

### The three ideas 1.0 is built on

1. **The API is a registry.** `GET /api/v2/services` says which services exist and what you can configure on each; `GET /api/v2/services/{name}` describes one in full, including the Dutch `explanation` and the `config_endpoint` per layer. Both are public: no project, no API key. **The registry is the source of truth, not the CLI.** No module may carry a list of service names.
2. **Configuration sits in layers per service**: `project`, `component`, `deployment` (and `deployment-component` for values). Which layers a service accepts comes from the registry, never from the CLI.
3. **Saving and rolling out are two things.** `rollout` is a query parameter on most mutating operations, with `zad project pending` next to it. `--no-rollout` saves the change and leaves the cluster alone until `zad project refresh`.

## Commands

```bash
uv sync                # Install
uv run pytest          # Run tests
uv run ruff check .    # Lint
uv run ruff format .   # Format
uv run zad --help      # Run the CLI
```

## Architecture

Typer-based CLI with noun-verb command structure (`zad deployment create`, `zad component add`).

- **cli.py** - Typer app, global options (--output, --api-key, --api-url, -p, --no-wait, --verbose, --rollout/--no-rollout, --refresh-catalog, --strict). Loads `.env` at startup. `guide`, `logs`, `login`, `logout` and `version` are direct commands (not sub-apps).
- **helpers.py** - Shared `get_helpers()`, `require_project()`, `require_service()`, `get_catalog()`, `resolve_target()`, `render_dry_run()` used by all command modules
- **settings.py** - Resolves settings: flags > env vars / .env > credentials store > config file > defaults. `SETTING_DOCS` says the same thing once as data (flag, env vars, config key, default) for `zad guide`
- **guide.py** - `zad guide`: the whole CLI in one call. The command tree comes from Click, the examples from the docstrings that already carry them, the services from the registry and the settings from `SETTING_DOCS`. Only what is derivable from none of those is written out, in that module. Adding a list of commands, flags or service names here is what `tests/test_guide.py` exists to stop
- **config.py** - Read/write `~/.config/zad/config.toml` (`api_url`, `rollout`, `keycloak_url`, `keycloak_realm`, `keycloak_client_id`). `KNOWN_KEYS` is a closed set: `config set` refuses anything else. The file is hand-editable, so every reader takes the TOML *type* it finds — `rollout = false` is a real boolean, and testing that layer for truth instead of presence silently drops it
- **picker.py** - The arrow-key list (`zad project use` without a name). Rich draws it, the terminal's raw mode delivers the keys, everything goes to stderr; a numbered prompt is the fallback without raw mode
- **credentials.py** - `~/.config/zad/credentials.toml` (0600): project API keys, the SSO token, the active project. OS keyring when available, file as fallback.
- **auth.py** - SSO login against Keycloak: device grant first, authorization code + PKCE on a `127.0.0.1` listener as fallback. Which Keycloak is a *setting* (never derived from the API host); the scope to ask with comes from the realm's `scopes_supported`, and a token without `zad-api` in `aud` is refused rather than stored
- **manifest.py** - `-f/--file`, `--set dotted.path=value`, `@file` values, `--generate-skeleton`, and the local schema check that names the field path
- **commands/** - One file per command group:
  - project (list, create, use/select, status, refresh, pending, delete, subdomains, check-subdomain)
  - deployment (list, describe, create, update-image, refresh, delete)
  - component (list, add, assign, update, delete)
  - service (list, types, describe) and service config (get, set, clear, schema)
  - attachment (list, add, assign, update, delete)
  - values.py → env and alias (list, get, add, set, unset, clear) — one factory, two services
  - db (schema list/add/remove), registry (add)
  - resource (tune, sanitize), task (wait, status, list, cancel)
  - backup (create, list, status, delete, namespace, database, bucket)
  - restore (list, project, backup, pvc, database, bucket)
  - clone (database, bucket, check), logs, metrics (health, overview, cpu, memory, pods, network, query)
  - config_cmd (init, set, get, list, path), open_cmd (project, portal, domains), login (login, logout), guide (guide)
- **api/registry.py** - The service catalog: fetch, cache per API URL (24h TTL, `--refresh-catalog`), bundled snapshot fallback, and deriving each layer's config/values endpoint
- **api/spec.py** - Reads the vendored OpenAPI spec: which operations accept `rollout`, and each operation's request schema
- **api/client.py** - httpx client with retry logic and verbose mode. Mutating ops use v2 async endpoints (return 202, poll via /api/tasks/{id})
- **api/models.py** - Pydantic request/response models (UpsertDeploymentRequest, CloneDatabaseRequest, CloneBucketRequest, etc.)
- **output/formatter.py** - Output: table (Rich), json, yaml. Data to stdout, status to stderr. `formatter.console` is the public Rich Console instance.

## CLI Design Principles

These are binding rules. Every new command must follow them. The automated API sync agent and any contributor must treat these as non-negotiable.

### Noun-verb command structure

Commands follow `zad <noun> <verb>` (e.g. `zad deployment create`, `zad service config set`). One file per noun group in `commands/`. Register sub-apps in `cli.py`. Exceptions: `logs`, `login`, `logout` and `version` are direct commands on the root app.

**Everything in `zad service list` is reachable under `zad service <name>`.** Services with a config document use the generic `zad service config`; the ones that carry *values* (`attachments`, `user-env-vars`, `aliases`) need their own verbs and are registered under `service` by the name the catalog shows, plus a shorter top-level alias (`zad attachment`, `zad env`, `zad alias`) that is the same app registered twice. A new service of that kind goes in both places: having to remember which services are the exception is worse than two spellings of one thing. `tests/commands/test_service_config.py` enforces it.

### Verb vocabulary

Use these verbs with their exact semantics:

| Verb | Meaning | Example |
|------|---------|---------|
| `list` | List all resources | `project list`, `task list` |
| `create` | Create a new top-level resource | `deployment create`, `backup create` |
| `add` | Attach something to an existing resource | `component add`, `env add` |
| `delete` | Remove a resource (NEVER `remove`, `drop`, `rm`) | `deployment delete`, `service delete` |
| `describe` | Show detailed single-resource info | `deployment describe` |
| `status` | Show current state | `project status`, `backup status` |
| `refresh` | Re-fetch from source (git) | `project refresh`, `deployment refresh` |
| `update-image` | Mutate a specific field | `deployment update-image` |
| `check` | Read-only validation | `clone check`, `project check-subdomain` |
| `assign` | Bind one resource to another | `component assign`, `attachment assign` |
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
- Deployment name: always positional when targeting a single deployment (`zad deployment delete <name>`, `zad backup create <deployment>`)
- Component/service name: positional when targeting a single item (`zad service delete <name>`)
- Task ID: positional (`zad task status <id>`)
- Never use `-d` to identify a deployment target. `-d` is only a filter option on list commands.

**Options** for everything else:
- `--target` picks the config layer (`project`, `component`, `deployment`). Optional when the service has exactly one layer; **required, never defaulted, when it has more than one** — writing project-wide config when a deployment override was meant is not something a default may decide.
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
2. `--yes, -y` flag: calls `confirm_action(message, yes)` before executing. Prompt format: `"Delete deployment 'X' in project 'Y'?"`.
3. `@handle_api_errors` decorator on the command function.
4. Success message via `formatter.render_success(f"Component '{name}' added.")` after the operation.

Read-only commands (`list`, `describe`, `status`, `check`, `schema`) do NOT need `--yes` or `--dry-run`.

### Services come from the registry

Never write a service name into a list, a validator, or an endpoint table.

- Resolve a name with `require_service(ctx, name)`; it fails naming the valid services.
- Pick a layer with `resolve_target(entry, target)`.
- Build the endpoint with `entry.config_endpoint(layer, ...)` or `entry.values_endpoint(...)`, which prefer the `config_endpoint` the API publishes per layer and otherwise follow the documented path pattern.
- Get a body's schema from `api/spec.py`, not from a hand-written model.

`tests/test_registry.py` fails the build if any module names two or more services on one line. A single name is allowed only where the command genuinely acts on that one service (`deployment update-image --recreate-storage`, `zad db schema`, `zad env`/`zad alias`).

### Rollout

`--rollout` and `--no-rollout` are global, and the Typer option is `bool | None`: only that
keeps "the user typed `--rollout`" apart from "nobody said anything", which is what makes
the layering work. `Settings.resolve()` decides it — **flag > `ZAD_ROLLOUT` > `config.toml`
`rollout` > `true`** — and records the winning layer in `Settings.sources`, which is what
`zad config list` shows. The client adds the `rollout` query parameter only to operations
the vendored spec says accept it — never from a list in the code. After a mutation that did
not roll out, the CLI says how many changes are waiting and how to roll them out.

### Authentication

Every project-scoped call uses `X-API-Key`. `project list` and `project create` are the two exceptions: they take `Authorization: Bearer <SSO token>`, because you need the project name before you can have its key. Both responses carry API keys — mask them in table output, store them in the credentials file, and never log them. `--verbose` prints method, path, body and params, never headers.

### Project handling

Most commands need a project. Get it via `project = require_project(ctx)`. The project comes from the global `-p` flag or `ZAD_PROJECT_ID` env var. Do not add a per-command project option.

Exceptions that don't require project: `project list`, `project check-subdomain`, `service types`, cluster-wide `metrics` commands, admin/restore operations that take cluster/namespace directly.

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

    $ zad service delete postgresql-database
"""
```

- First line: brief, shown in `--help` command list
- Use Rich markup (`[bold]`, `[/bold]`) for formatting
- Include at least one example with `$ zad ...`
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

- `deployment create` is an upsert - requires `--yes` confirmation
- `check-subdomain` lives under `project` group (not `deployment`)
- `clone check` validates configuration without executing (read-only)
- `task list` uses `--filter-project` (not `--project`) to avoid collision with global `-p`
- `restore database/bucket` take deployment name (like backup) and resolve namespace internally via `client.resolve_namespace()`
- `service types` is kept as an alias of `service list` for scripts that already call it
- `zad env` and `zad alias` are both built by `commands/values.py`; a third key/value service costs one line
- `attachment add` writes the catalog, `attachment assign` writes the coupling — the mount path belongs to the coupling, so the same file can land elsewhere per component
- `admin cleanup` and `admin reconcile` default to a dry run, like the API; `--apply` is what actually changes something
- Autocompletion: use `complete_deployment`, `complete_component` and `complete_service` callbacks from `helpers.py` on relevant arguments

## Configuration

Precedence: flags > env vars / `.env` > credentials store > config file > defaults

| Setting | Flag | Env var / `.env` | Config file |
|---------|------|------------------|-------------|
| API key | `--api-key` | `ZAD_API_KEY` | `credentials.toml`, per project |
| Project | `-p` | `ZAD_PROJECT_ID` | `credentials.toml`, `active_project` |
| API URL | `--api-url` | `ZAD_API_URL` | `config.toml`, `api_url` |
| Roll out | `--rollout` / `--no-rollout` | `ZAD_ROLLOUT` | `config.toml`, `rollout` |
| SSO token | `zad login --token` | `ZAD_SSO_TOKEN` | `credentials.toml`, `token` |
| Keycloak URL | `--keycloak-url` | `ZAD_KEYCLOAK_URL` | `config.toml`, `keycloak_url` (default `https://keycloak.rijksapp.nl`) |
| Keycloak realm | `--keycloak-realm` | `ZAD_KEYCLOAK_REALM` | `config.toml`, `keycloak_realm` (default `rig-platform`) |
| Keycloak client | `--keycloak-client-id` | `ZAD_SSO_CLIENT_ID` / `ZAD_KEYCLOAK_CLIENT_ID` | `config.toml`, `keycloak_client_id` (default `zad-cli`) |
| SSO issuer | - | `ZAD_SSO_ISSUER` | composed: `{keycloak_url}/realms/{keycloak_realm}` |
| Catalog offline | - | `ZAD_CATALOG_OFFLINE` | - |

`config list` shows every setting in effect with the layer that decided it (from
`Settings.sources`), plus the `.env` and `~/.config/zad/config.toml` contents. The credentials
file holds secrets and is written with mode 0600; `zad project use` sets the active project,
which is a *fallback* — `-p` and `ZAD_PROJECT_ID` still win.

## Testing

- `respx` for httpx mocking (test_client.py) and for command tests via `typer.testing.CliRunner`
- `subprocess` for CLI integration tests (test_cli.py)
- `capsys` for output tests (test_output.py)

**No real API calls in tests.** `tests/conftest.py` enforces this for every test: it points
the credentials store at a temporary directory and sets `ZAD_CATALOG_OFFLINE=1`, so the
service catalog comes from the snapshot bundled at `src/zad_cli/data/services-snapshot.json`
instead of the network. Tests that exercise catalog fetching opt out and mock it with respx.

Refresh the snapshot together with the spec:

```bash
python scripts/fetch_openapi.py --url https://zad.sandbox.rijksapp.dev/api --key <key>
curl -s https://zad.sandbox.rijksapp.dev/api/v2/services > src/zad_cli/data/services-snapshot.json
python scripts/check_coverage.py
```

## Compatibility policy

**Additive within a major.** Other teams depend on this CLI, so within a major version the
old rules hold in full:

- **No removing** CLI commands, options, or positional arguments
- **No renaming** commands or flags
- **No changing** argument positions or types
- **Additive changes only**: new commands, new options, new output fields
- **Deprecation before removal**: add a deprecation warning for at least 2 minor versions before removing anything
- **Same rules for `ZadClient`**: no removing public methods, no breaking signature changes, only new methods and new optional kwargs

A major release may break these, and 1.0 did: `service add` and `service delete` are gone,
because the endpoints behind them were deprecated and withdrawn upstream. Configuration is
now written per layer with `service config set` / `service config clear`.

When a major release removes something:

1. Edit the baseline in `tests/test_backwards_compat.py` — never delete a line silently.
2. Add the removal to `REMOVED_IN_1_0` (or its successor) with what replaced it. The test then checks the command is really gone, so a half-removal cannot ship.
3. Say so in `CHANGELOG.md` and `README.md`.

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
