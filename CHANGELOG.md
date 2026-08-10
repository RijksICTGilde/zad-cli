# CHANGELOG

<!--
Automatically maintained by python-semantic-release.
See: https://python-semantic-release.readthedocs.io/
-->

## Unreleased

### Added
- `zad project use` without a name opens a list of the projects you are a member of and
  makes the one you pick active. `zad project select` is the same command. The list shows
  no API keys; without a terminal (a pipe, CI, `-o json`) it asks for a name instead of
  guessing.
- `zad project list` marks the active project with a `*`.
- `zad login` ends with who you are and the next step: the picker when there is a terminal
  and no active project yet, otherwise the command to run.
- The rollout default is a setting: **flag > `ZAD_ROLLOUT` > `zad config set rollout` >
  roll out**. `zad config list` shows every setting in effect and which layer decided it.
- The Keycloak `zad login` uses is three settings — `keycloak_url`, `keycloak_realm` and
  `keycloak_client_id` — each through **flag > env (`ZAD_KEYCLOAK_*`) > config > default**.
  The issuer is composed as `{keycloak_url}/realms/{keycloak_realm}`, so pointing the CLI
  at a test Keycloak is one setting and leaves the realm and client alone. `ZAD_SSO_ISSUER`
  and `ZAD_SSO_CLIENT_ID` keep working as overrides.
- `zad login` checks that the access token carries the `zad-api` audience the API demands,
  and refuses to store one that does not, naming the client that needs an audience mapper
  instead of leaving you with a bare 401 on the next command.
- The output format is a setting too: **flag > `ZAD_OUTPUT_FORMAT` > `zad config set output`
  > table**. A format the formatter cannot render is refused when it is written, not on the
  run that reads it back.
- `--json` and `--yaml` as shorthand for `--output json` / `--output yaml`. Combining the two,
  or contradicting an explicit `--output`, is refused rather than silently resolved.

### Changed
- `zad project create` takes a **display name** instead of a technical name, following the
  API: `zad project create "Mijn Project" --description "..."`. The platform derives the
  technical name and returns it as `project_name`, and that derived name is what the API key
  is stored under and what becomes the active project — storing it under the name that was
  typed would file it under a project that does not exist. `--display-name` is gone; it is
  the positional now.
- `zad config set` refuses keys the CLI does not read, naming the ones it does, so a typo
  no longer disappears silently into the config file.
- The login defaults now point at production (`https://keycloak.rijksapp.nl`, realm
  `rig-platform`, client `zad-cli`) instead of the sandbox, and the Keycloak host is no
  longer derived from the API host — that guess was wrong for production.
- Falling back to the bundled service catalog says so loudly, names the API that did not
  answer and how to point elsewhere. The snapshot is close enough to the real catalog that
  the difference does not show in the output, so a quiet line above a full-screen table read
  as a correct answer.
- `zad service` help says the catalog is per-environment and points at `zad service list`,
  instead of leaving the service names undiscoverable from `--help`.

### Fixed
- A hand-written `config.toml` with a real TOML boolean is read correctly. `rollout = true`
  crashed every command, and `rollout = false` was silently ignored (falling through to the
  default and rolling out anyway) — which is exactly the class of mistake the closed key set
  in this release is meant to prevent.
- `ZAD_OUTPUT_FORMAT` is now actually read: the `-o` flag no longer shadows it with its
  own default.

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
