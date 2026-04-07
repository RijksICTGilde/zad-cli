# CHANGELOG

<!--
Automatically maintained by python-semantic-release.
See: https://python-semantic-release.readthedocs.io/
-->

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
