# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

## What is zad-cli?

zad-cli is a CLI for ZAD (Zelfservice Applicatie Deployment), the self-service Kubernetes deployment platform used by the Dutch government (RijksICTGilde). It wraps the Operations Manager REST API (v2 async endpoints).

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

- **cli.py** - Typer app, global options (--output, --api-key, --api-url, -p, --no-wait, --verbose). Loads `.env` at startup. `logs` is a direct command (not a sub-app).
- **helpers.py** - Shared `get_helpers()`, `require_project()`, `render_dry_run()` used by all command modules
- **settings.py** - Resolves settings: flags > env vars / .env > config file > defaults
- **config.py** - Read/write `~/.config/zad/config.toml` (only for api_url)
- **services.py** - Valid service names list and validation
- **commands/** - One file per command group:
  - project (list, status, refresh, delete, subdomains, check-subdomain)
  - deployment (list, describe, create, update-image, refresh, delete)
  - component (list, add, assign, delete)
  - service (types, add, delete)
  - resource (tune, sanitize), task (wait, status, list, cancel)
  - backup (create, list, status, delete, namespace, database, bucket)
  - restore (list, project, backup, pvc, database, bucket)
  - clone (database, bucket, check), logs, metrics (health, overview, cpu, memory, pods, network, query)
  - config_cmd (init, set, get, list, path), open_cmd (project, portal, domains)
- **api/client.py** - httpx client with retry logic and verbose mode. Mutating ops use v2 async endpoints (return 202, poll via /api/tasks/{id})
- **api/models.py** - Pydantic request/response models (UpsertDeploymentRequest, CloneDatabaseRequest, CloneBucketRequest, etc.)
- **output/formatter.py** - Output: table (Rich), json, yaml. Data to stdout, status to stderr. `formatter.console` is the public Rich Console instance.

## CLI Design Principles

These are binding rules. Every new command must follow them. The automated API sync agent and any contributor must treat these as non-negotiable.

### Noun-verb command structure

Commands follow `zad <noun> <verb>` (e.g. `zad deployment create`, `zad service add`). One file per noun group in `commands/`. Register sub-apps in `cli.py`. Exception: `logs` is a direct command on the root app, not a sub-app.

### Verb vocabulary

Use these verbs with their exact semantics:

| Verb | Meaning | Example |
|------|---------|---------|
| `list` | List all resources | `project list`, `task list` |
| `create` | Create a new top-level resource | `deployment create`, `backup create` |
| `add` | Attach something to an existing resource | `component add`, `service add` |
| `delete` | Remove a resource (NEVER `remove`, `drop`, `rm`) | `deployment delete`, `service delete` |
| `describe` | Show detailed single-resource info | `deployment describe` |
| `status` | Show current state | `project status`, `backup status` |
| `refresh` | Re-fetch from source (git) | `project refresh`, `deployment refresh` |
| `update-image` | Mutate a specific field | `deployment update-image` |
| `check` | Read-only validation | `clone check`, `project check-subdomain` |
| `assign` | Bind one resource to another | `component assign` |

Multi-word commands use kebab-case: `update-image`, `check-subdomain`.

### Argument rules

**Positional arguments** identify the primary target resource:
- Deployment name: always positional when targeting a single deployment (`zad deployment delete <name>`, `zad backup create <deployment>`)
- Component/service name: positional when targeting a single item (`zad service delete <name>`)
- Task ID: positional (`zad task status <id>`)
- Never use `-d` to identify a deployment target. `-d` is only a filter option on list commands.

**Options** for everything else:
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

Read-only commands (`list`, `describe`, `status`, `check`) do NOT need `--yes` or `--dry-run`.

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
```

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
- Autocompletion: use `complete_deployment` and `complete_component` callbacks from `helpers.py` on relevant arguments

## Configuration

Precedence: flags > env vars / `.env` > config file > defaults

| Setting | Flag | Env var / `.env` | Config file |
|---------|------|------------------|-------------|
| API key | `--api-key` | `ZAD_API_KEY` | - |
| Project | `-p` | `ZAD_PROJECT_ID` | - |
| API URL | `--api-url` | `ZAD_API_URL` | `api_url` |

`config list` shows both `.env` and `~/.config/zad/config.toml` contents.

## Testing

- `respx` for httpx mocking (test_client.py)
- `subprocess` for CLI integration tests (test_cli.py)
- `capsys` for output tests (test_output.py)

No real API calls in tests.

## Backwards Compatibility Policy

zad-cli follows a strict additive-only change policy. Other teams depend on this CLI.

- **No removing** CLI commands, options, or positional arguments
- **No renaming** commands or flags
- **No changing** argument positions or types
- **Additive changes only**: new commands, new options, new output fields
- **Deprecation before removal**: add a deprecation warning for at least 2 minor versions before removing anything
- **Same rules for `ZadClient`**: no removing public methods, no breaking signature changes, only new methods and new optional kwargs

The `tests/test_backwards_compat.py` test enforces this by checking the CLI command tree and client method list against a stored baseline. CI fails if any command or method disappears.

## API Monitoring

The upstream Operations Manager API (repo: `RijksICTGilde/RIG-Cluster`) is a FastAPI app with an auto-generated OpenAPI spec at `/openapi.json`.

A scheduled GitHub Actions workflow (`.github/workflows/api-sync.yml`) runs daily on weekdays:
1. Fetches the latest OpenAPI spec from the deployed instance
2. Diffs it against `api/upstream-openapi.json` using [oasdiff](https://github.com/oasdiff/oasdiff)
3. Runs `scripts/check_coverage.py` to find upstream endpoints not yet covered by the CLI
4. If gaps are found, Claude implements new client methods, CLI commands, and tests
5. Creates a PR for human review

Breaking upstream changes get flagged with a `breaking-api-change` label but are not auto-implemented.
