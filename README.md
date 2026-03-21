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

Create a `.env` file in your project directory:

```
ZAD_API_KEY=sk-...
ZAD_PROJECT_ID=my-project
```

Then use the CLI:

```bash
zad project deploy -d pr-42 --component web --image ghcr.io/org/app:pr-42
zad logs show -d production
zad backup create production
```

## Configuration

| Setting | Flag | Env var / `.env` | Config file | Default |
|---------|------|------------------|-------------|---------|
| API key | `--api-key` | `ZAD_API_KEY` | - | - |
| Project | `-p` | `ZAD_PROJECT_ID` | - | - |
| API URL | `--api-url` | `ZAD_API_URL` | `api_url` | production URL |
| Output | `-o` | `ZAD_OUTPUT_FORMAT` | - | `table` |

Precedence: **flags > env vars / `.env` > config file > defaults**

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
zad config     set, get, list, path
zad project    create, deploy, refresh, delete, subdomains
zad deployment update-image, delete, check-subdomain
zad backup     create, list, status, delete, namespace, database, bucket
zad restore    list, project, run, pvc, database, bucket
zad clone      database, bucket
zad logs       show, stream
zad metrics    health, overview, cpu, memory, pods, network, query
zad invite     send
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
