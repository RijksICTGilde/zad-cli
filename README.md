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

Sign in with your own account, pick a project, and its API key is stored for you:

```bash
zad login
zad project list
zad project use my-project
```

Already have an API key? `zad config init` writes a `.env` interactively, or write one yourself:

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

## Discovering what ZAD offers

The CLI has no built-in list of services. It reads the platform's own catalog, so a
service added upstream shows up without a CLI release — and so a script or an agent can
find out what is possible without being told:

```bash
zad service list                                    # every service, and what you can set on each
zad service describe postgresql-database            # the full explanation, in Dutch, plus its variables
zad service config schema postgresql-database -o json   # the JSON Schema for a valid body
```

Configuring a service is the same command for every service:

```bash
zad service config set postgresql-database --set scope=project
zad service config set publish-on-web --component web -f web.yaml
zad service config clear redis
```

A service can accept config at more than one layer (`project`, `component`, `deployment`).
With one layer, `--target` is optional; with more than one it is required, because writing
project-wide config when you meant a deployment override is not something a default should
decide for you.

## Saving without rolling out

Saving a change and rolling it out to the cluster are two different things:

```bash
zad --no-rollout service config set redis --set instances=2
zad project pending      # what is saved but not live yet
zad project refresh      # roll everything out at once
```

`--rollout` is the default, so nothing changes unless you ask for it.

## Configuration

| Setting | Flag | Env var / `.env` | Stored | Default |
|---------|------|------------------|--------|---------|
| API key | `--api-key` | `ZAD_API_KEY` | `credentials.toml`, per project | - |
| Project | `-p` | `ZAD_PROJECT_ID` | `credentials.toml` (`zad project use`) | - |
| API URL | `--api-url` | `ZAD_API_URL` | `config.toml` | production URL |
| SSO token | `zad login --token` | `ZAD_SSO_TOKEN` | `credentials.toml` (`zad login`) | - |
| Output | `-o` | `ZAD_OUTPUT_FORMAT` | - | `table` |
| Roll out | `--rollout` / `--no-rollout` | - | - | roll out |
| No wait | `--no-wait` | - | - | wait |
| Strict | `--strict` | - | - | off |
| Refresh catalog | `--refresh-catalog` | - | - | cached 24h |

Precedence: **flags > env vars / `.env` > credentials store > config file > defaults**

`~/.config/zad/credentials.toml` holds secrets and is written with mode 0600 (an OS keyring
is used instead when one is available). `zad project use` records a *default* project;
`-p` and `ZAD_PROJECT_ID` still win, so existing scripts keep behaving the same. To hand
the settings to something else:

```bash
eval "$(zad project use my-project --export)"
zad project use my-project --write-env .env
```

Only `zad project list` and `zad project create` use the SSO token — you need a project's
name before you can have its key. Everything else uses the project API key. Both responses
carry API keys, so they are masked in output unless you pass `--show-keys`, and never logged.

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

Errors tell you **what's wrong and what to do next**, with a neutral label for where
to look (your request, your application, your configuration, your credentials, or the
ZAD platform) instead of a bare HTTP code. A failed image pull points you straight at
the image and registry (`Source: your application (cluster runtime)`) with the fix.

Each error carries a structured diagnosis. In `--output json` it's a single object
on stdout you can branch on in CI/CD:

```bash
zad deployment create app -c web=img:tag -o json > out.json || jq -r .fault out.json
# UserInput | UserApp | UserConfig | Auth | Platform | Network | Unknown
```

Exit codes:

| Code | Meaning |
|------|---------|
| `0` | success |
| `1` | your fault, fix it (bad input, app/config failure, auth) |
| `2` | platform/network, transient and safe to retry |
| `3` | unknown, the API gave no signal to attribute the failure (check the logs) |

`--strict` makes a command that *succeeds but reports warnings* (e.g. the deploy
applied but a component is crash-looping) exit non-zero, so a pipeline fails the
build instead of going green on an unhealthy app. Diagnostics go to **stderr**;
data (and the json error object) go to **stdout**, so pipes stay clean.

## Commands

```
zad login / logout                sign in with your own account, forget the credentials
zad config      init, set, get, list, path
zad project     list, create, use, status, refresh, pending, delete, subdomains, check-subdomain
zad deployment  list, describe, create, update-image, refresh, delete
zad component   list, add, assign, update, delete
zad service     list, types, describe
zad service config  get, set, clear, schema
zad attachment  list, add, assign, update, delete
zad env         list, get, add, set, unset, clear      (a component's own variables)
zad alias       list, get, add, set, unset, clear      (platform variables under the names your app expects)
zad db schema   list, add, remove
zad registry    add
zad resource    tune, sanitize
zad task        wait, status, list, cancel
zad backup      create, list, status, delete, namespace, database, bucket
zad restore     list, project, backup, pvc, database, bucket
zad clone       database, bucket, check
zad logs        [DEPLOYMENT] [-c component] [-n lines] [--since 1h]
zad metrics     health, overview, cpu, memory, pods, network, query
zad admin       list, delete, orphan-report, orphan-confirm, cleanup, reconcile
zad open        project, portal, domains
zad version
```

On `env` and `alias`, the four verbs are four different endpoints and none of them is a
synonym for another: `add` refuses a key that already exists, `set` requires one that does,
`unset` removes named keys, `clear` removes everything at that layer.

### Changed in 1.0

`zad service add` and `zad service delete` are gone; the endpoints behind them were
deprecated and withdrawn upstream. Configure a service per layer instead:

| Before | Now |
|---|---|
| `zad service add postgresql-database` | `zad service config set postgresql-database --set scope=shared` |
| `zad service delete postgresql-database` | `zad service config clear postgresql-database` |
| `zad service types` | `zad service list` (`types` still works as an alias) |
| `zad project list` (API key) | `zad project list` (after `zad login`) |

## Development

```bash
uv sync
uv run pytest
uv run ruff check .
uv run zad --help
```

The CLI's map of the API is vendored: `api/upstream-openapi.json` (which operations exist,
what each body looks like, which accept `rollout`) and `src/zad_cli/data/services-snapshot.json`
(the service catalog, used when the API cannot be reached). Refresh both together and check
the result:

```bash
python scripts/fetch_openapi.py --url https://zad.sandbox.rijksapp.dev/api --key <key>
curl -s https://zad.sandbox.rijksapp.dev/api/v2/services > src/zad_cli/data/services-snapshot.json
python scripts/check_coverage.py
```

## License

EUPL-1.2
