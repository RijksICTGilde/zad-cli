# zad-cli

CLI for ZAD (Zelfservice Applicatie Deployment) - the self-service Kubernetes deployment platform.

## Installation

```bash
uv tool install git+https://github.com/RijksICTGilde/zad-cli.git
```

Or for development:

```bash
git clone https://github.com/RijksICTGilde/zad-cli.git
cd zad-cli
uv sync
```

## Quick start

```bash
zad config init   # interactive setup: creates .env with API key and project ID
```

Or create a `.env` file manually:

```
ZAD_API_KEY=sk-...
ZAD_PROJECT_ID=my-project
```

Then use the CLI:

```bash
zad deployment create staging --component web --image ghcr.io/org/app:v1.0
zad logs production
zad backup create production
```

## Configuration

| Setting | Flag | Env var / `.env` | Config file | Default |
|---------|------|------------------|-------------|---------|
| API key | `--api-key` | `ZAD_API_KEY` | - | - |
| Project | `-p` | `ZAD_PROJECT_ID` | - | - |
| API URL | `--api-url` | `ZAD_API_URL` | `api_url` | production URL |
| Output | `-o` | `ZAD_OUTPUT_FORMAT` | - | `table` |
| No wait | `--no-wait` | - | - | wait |

Precedence: **flags > env vars / `.env` > config file > defaults**

Use `--no-wait` to return a task ID immediately instead of waiting for async operations to complete. Check progress with `zad task status <id>`.

The config file (`~/.config/zad/config.toml`) is for settings that rarely change:

```bash
zad config set api_url https://staging.example.com/api
```

## Output formats

Every command supports `--output` / `-o`: `table` (default), `json`, `yaml`.

```bash
zad metrics overview --output json | jq '.cpu_usage'
```

## Commands

```
zad config      init, set, get, list, path
zad project     list, status, refresh, delete, subdomains, check-subdomain
zad deployment  list, describe, create, update-image, refresh, delete
zad component   list, add, assign, delete
zad service     types, add, delete
zad resource    tune, sanitize
zad task        wait, status, list, cancel
zad backup      create, list, status, delete, namespace, database, bucket
zad restore     list, project, backup, pvc, database, bucket
zad clone       database, bucket, check
zad logs        [DEPLOYMENT] [-c component] [-n lines] [--since 1h]
zad metrics     health, overview, cpu, memory, pods, network, query
zad open        project, portal, domains
zad version
```

## Development

```bash
uv sync
uv run pytest
uv run ruff check .
uv run zad --help
```

## License

EUPL-1.2
