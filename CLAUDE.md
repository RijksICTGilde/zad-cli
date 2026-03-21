# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

## What is zad-cli?

zad-cli is a CLI for ZAD (Zelfservice Applicatie Deployment), the self-service Kubernetes deployment platform used by the Dutch government (RijksICTGilde). It wraps the Operations Manager REST API.

## Commands

```bash
uv sync                # Install
uv run pytest          # Run tests
uv run ruff check .    # Lint
uv run ruff format .   # Format
uv run zad --help      # Run the CLI
```

## Architecture

Typer-based CLI with noun-verb command structure (`zad project deploy`, `zad backup create`).

- **cli.py** - Typer app, global options (--output, --api-key, --api-url, --project)
- **helpers.py** - Shared `get_helpers()` and `require_project()` used by all command modules
- **settings.py** - Settings from env vars and flags (no config files)
- **commands/** - One file per command group (project, deployment, backup, restore, clone, logs, metrics, invite)
- **api/client.py** - httpx client with retry logic and async task polling
- **api/models.py** - Pydantic request/response models
- **output/formatter.py** - Output: table (Rich), json, yaml. Data to stdout, status to stderr

## Environment variables

| Variable | Description |
|----------|-------------|
| `ZAD_API_KEY` | API key (required, per-project) |
| `ZAD_PROJECT_ID` | Default project ID |
| `ZAD_API_URL` | API base URL (optional, has default) |

## Testing

- `respx` for httpx mocking (test_client.py)
- `subprocess` for CLI integration tests (test_cli.py)
- `capsys` for output tests (test_output.py)

No real API calls in tests.
