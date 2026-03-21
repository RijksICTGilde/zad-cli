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

## CLI conventions

- Deployment name is always a positional argument (never -d) when it identifies a single deployment
- `-d` is used only as a filter option (`component list -d`) — never as a repeatable target
- `component add` uses `--deployment` (long form only, no `-d`) since it's repeatable
- `logs` takes deployment as an optional positional argument: `zad logs [DEPLOYMENT]`
- Destructive and mutating commands use `--yes`/`-y` for skip confirmation and `--dry-run`
- `deployment create` is an upsert — it requires `--yes` confirmation
- All deletion commands use the verb `delete` (not `remove`)
- `check-subdomain` lives under the `project` group (not `deployment`)
- `clone check` validates configuration without executing (read-only)
- "Requires ZAD_API_KEY..." is in the Typer group help, not repeated per command
- `service types` and all list commands respect `--output` format via the formatter
- `task list` uses `--filter-project` (not `--project`) to avoid collision with global `-p`
- `restore database/bucket` take deployment name (like backup) and resolve namespace internally

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
