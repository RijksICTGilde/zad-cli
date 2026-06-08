# zad-cli

CLI for ZAD (Zelfservice Applicatie Deployment) - the self-service Kubernetes deployment platform.

## Installation

```bash
uv tool install git+https://github.com/RijksICTGilde/zad-cli.git
```

Or pin a specific version:

```bash
uv tool install git+https://github.com/RijksICTGilde/zad-cli.git@v0.1.0
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
| Strict | `--strict` | - | - | off |

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

## Errors & exit codes

Errors tell you **where the fault lives** — your request, your application, your
configuration, your credentials, or the ZAD platform — instead of a bare HTTP code.
A failed image pull is labelled `Source: your application (cluster runtime)`, not
"the backend is down".

Each error carries a structured diagnosis. In `--output json` it's a single object
on stdout you can branch on in CI/CD:

```bash
zad deployment create app -c web=img:tag -o json 2>err.json || jq -r .fault err.json
# UserInput | UserApp | UserConfig | Auth | Platform | Network | Unknown
```

Exit codes:

| Code | Meaning |
|------|---------|
| `0` | success |
| `1` | your fault — fix it (bad input, app/config failure, auth) |
| `2` | platform/network — transient, safe to retry |

`--strict` makes a command that *succeeds but reports warnings* (e.g. the deploy
applied but a component is crash-looping) exit non-zero, so a pipeline fails the
build instead of going green on an unhealthy app. Diagnostics go to **stderr**;
data (and the json error object) go to **stdout**, so pipes stay clean.

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
