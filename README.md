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

```bash
ZAD_API_KEY=sk-...
ZAD_PROJECT_ID=my-project
```

Then use the CLI:

```bash
# Deploy
zad project deploy -d pr-42 --component web --image ghcr.io/org/app:pr-42

# View logs
zad logs show -d production

# Create backup
zad backup create production
```

## Environment variables

Set these in `.env`, your shell, or as flags:

| Variable | Flag | Required | Description |
|----------|------|----------|-------------|
| `ZAD_API_KEY` | `--api-key` | yes | API key (from the project page) |
| `ZAD_PROJECT_ID` | `-p` | yes | Project identifier |
| `ZAD_API_URL` | `--api-url` | no | API base URL (has default) |
| `ZAD_OUTPUT_FORMAT` | `-o` | no | Output format: table, json, yaml |

All can also be passed as flags: `--api-key`, `-p`/`--project`, `--api-url`, `-o`/`--output`.

## Output formats

Every command supports `--output` / `-o`:

- `table` (default) - Rich tables
- `json` - for scripting and agents
- `yaml` - YAML output

```bash
zad metrics overview --output json | jq '.cpu_usage'
```

## Commands

```
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
