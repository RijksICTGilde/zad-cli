# CHANGELOG

<!--
Automatically maintained by python-semantic-release.
See: https://python-semantic-release.readthedocs.io/
-->

## v1.0.0

The Operations Manager became a registry, and the CLI follows it. The goal of this release
is that the CLI can do everything the web UI can, and that a script or an agent can find
out what ZAD offers without any built-in knowledge.

### Removed (breaking)
- `zad service add` and `zad service delete` — the endpoints behind them were deprecated
  and withdrawn upstream. Configure a service per layer instead: `zad service config set`
  and `zad service config clear`.
- `src/zad_cli/services.py`, which hardcoded 11 service names and was already out of date.
  Service names now come from `GET /api/v2/services`.

### Added
- `zad service list|describe` — the platform's own catalog, including the Dutch explanation
  and each service's variables. No API key needed.
- `zad service config get|set|clear|schema` — one command per verb for every service, at
  every layer, driven by the registry rather than a table of ~50 endpoints.
- `--set dotted.path=value`, `-f/--file` manifests (YAML or JSON, `-` for stdin), `@file`
  values, `--generate-skeleton`, and a local schema check that names the field path.
- `--rollout` / `--no-rollout` and `zad project pending`: saving and rolling out are two
  things. After a `--no-rollout` change the CLI says what is waiting and how to roll it out.
- `zad attachment list|add|assign|update|delete` — the project's file catalog and the
  per-component coupling, kept apart. `--mount-path` belongs to the coupling.
- `zad env` and `zad alias` — a component's own variables and the aliases for platform
  variables, with `add`/`set`/`unset`/`clear` mapping to the API's four distinct endpoints.
- `zad login` / `zad logout`, `zad project list|create|use` — SSO sign-in and a credentials
  store at `~/.config/zad/credentials.toml` (mode 0600, OS keyring when available).
  Returned API keys are stored, masked in output and never logged.
- `zad db schema list|add|remove`, `zad admin cleanup|reconcile`, `zad registry add`.
- `zad version` now reports the server's version alongside the CLI's, instead of being a
  deprecated alias.
- `--refresh-catalog`, and a bundled catalog snapshot so the CLI still works offline.

### Changed
- The compatibility policy is now "additive within a major" rather than additive forever.
  A removal must edit the baseline in `tests/test_backwards_compat.py` and be listed with
  what replaced it.
- `zad project list` authenticates with an SSO token instead of an API key; the v1 endpoint
  it used no longer exists.
- `api/upstream-openapi.json` refreshed. `scripts/check_coverage.py` understands the
  registry-driven commands and reports the endpoints left out of 1.0, each with a reason.

## v0.1.0 (2026-04-07)

### Added
- Full v2 async API support (all mutating operations use fire-and-forget with task polling)
- `zad component add` - add components with ports, services, CPU/memory limits, env vars
- `zad component assign` - assign existing component to a deployment
- `zad service add` - add services (postgresql-database, keycloak, redis, etc.) with validation
- `zad resource tune` - auto-tune CPU/memory from Prometheus usage data
- `zad resource sanitize` - detect and disable broken deployments
- `zad task status|list|cancel` - manage async tasks
- `zad deployment refresh` - refresh a single deployment from git
- `zad clone check` - pre-flight checks before cloning
- Docker-style `-e KEY=VALUE` and `--env-file` for environment variables
- `.env` file support via python-dotenv
- Global `--project`/`-p` flag and `ZAD_PROJECT_ID` env var
- Global config file at `~/.config/zad/config.toml` for api_url
- Output formatting: table (Rich), json, yaml
- Claude Code skill for AI-assisted operations
