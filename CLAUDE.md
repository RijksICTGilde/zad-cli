# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

## What is zad-cli?

zad-cli is a CLI tool for ZAD (Zelfservice Applicatie Deployment), the self-service Kubernetes deployment platform used by the Dutch government (RijksICTGilde). It wraps the Operations Manager REST API and covers deploying, managing backups/restores, viewing logs and metrics, and managing configuration.

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

- **cli.py** - Typer app, registers sub-command groups, global options (--output, --api-key, --api-url, --project, --context)
- **helpers.py** - Shared `get_helpers()` and `resolve_project()` used by all command modules
- **commands/** - One file per command group (project, deployment, backup, restore, clone, logs, metrics, config_cmd, invite)
- **api/client.py** - Synchronous httpx client with retry logic (exponential backoff on 429/5xx) and async task polling
- **api/models.py** - Pydantic models for validation. Uses `^[a-zA-Z0-9._-]+$` pattern from zad-actions
- **config/context.py** - Context/profile management for ~/.zad/config.yml
- **config/settings.py** - Config hierarchy: CLI flags > env vars (ZAD_*) > config file > defaults
- **output/formatter.py** - Output formatting: table (Rich), json, yaml. Data to stdout, status to stderr

## Environment variables

| Variable | Description |
|----------|-------------|
| `ZAD_API_KEY` | API key (required, per-project) |
| `ZAD_PROJECT_ID` | Default project ID (optional, avoids repeating it) |
| `ZAD_API_URL` | API base URL (optional, has default) |

## Testing

- `respx` for httpx HTTP mocking (test_client.py)
- `tmp_path` + `unittest.mock.patch` for config file I/O (test_config.py)
- `subprocess` for CLI integration tests (test_cli.py)
- `capsys` for output formatting tests (test_output.py)

No real API calls in tests.

## Related repositories

- **RIG-cluster** - The ZAD platform (Operations Manager FastAPI backend)
- **zad-actions** - GitHub Actions for deploying to ZAD
- **stuc** - Sister CLI for fleet-wide repo updates (same tech stack)
