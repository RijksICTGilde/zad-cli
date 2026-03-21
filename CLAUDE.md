# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

## What is zad-cli?

zad-cli is a CLI tool for ZAD (Zelfservice Applicatie Deployment), the self-service Kubernetes deployment platform used by the Dutch government (RijksICTGilde). It wraps the Operations Manager REST API and covers deploying, managing backups/restores, viewing logs and metrics, and managing configuration.

## Commands

```bash
# Install
uv sync

# Run tests
uv run pytest

# Run a single test
uv run pytest tests/test_client.py::test_retry_on_500

# Lint
uv run ruff check .

# Format
uv run ruff format .

# Run the CLI
uv run zad --help
```

## Architecture

The CLI uses Typer with noun-verb command structure (`zad project deploy`, `zad backup create`). Each command group is a separate file in `src/zad_cli/commands/`.

- **cli.py** - Main Typer app, registers sub-command groups, global options (--output, --api-key, --api-url, --context). Lazily creates the API client when a command needs it.
- **commands/** - One file per command group (project, deployment, backup, restore, clone, logs, metrics, config_cmd, invite). Each defines a `typer.Typer()` sub-app.
- **api/client.py** - Synchronous httpx client with retry logic (exponential backoff on 429/5xx) and async task polling (POST returns poll_url, poll until completed/failed/timeout).
- **api/models.py** - Pydantic models for request/response validation. Input validation uses `^[a-zA-Z0-9._-]+$` pattern from zad-actions.
- **config/context.py** - Context/profile management for ~/.zad/config.yml (like kubectl contexts).
- **config/settings.py** - Configuration hierarchy: CLI flags > env vars (ZAD_*) > config file > defaults.
- **output/formatter.py** - Output formatting: table (Rich), json, yaml. Data to stdout, status to stderr.
- **output/progress.py** - Rich spinner for task polling progress.

## Authentication

API key via environment variable or flag. No login flow.

```bash
export ZAD_API_KEY=sk-...       # environment (recommended)
zad --api-key sk-... ...        # flag (one-off)
```

## Testing

Tests use pytest with:
- `respx` for httpx HTTP mocking (test_client.py)
- `tmp_path` + `unittest.mock.patch` for config file I/O (test_config.py)
- `subprocess` for CLI integration tests (test_cli.py)
- `capsys` for output formatting tests (test_output.py)

No real API calls in tests.

## Related repositories

- **RIG-cluster** - The ZAD platform (Operations Manager FastAPI backend, Kubernetes infrastructure)
- **zad-actions** - GitHub Actions for deploying to ZAD (deploy, cleanup, scheduled-cleanup)
- **stuc** - Sister CLI tool for fleet-wide repo updates (same tech stack: Typer, Rich, uv)
