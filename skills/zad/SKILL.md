---
name: zad
description: >-
  Deploy, manage, and troubleshoot applications on the ZAD platform. Use when
  the user mentions 'zad', 'deploy to zad', 'deployment', 'ZAD_API_KEY',
  'operations manager', 'backup', 'restore', 'zad project', 'zad logs',
  'component', 'service', 'resource tuning'.
---

# zad - ZAD platform operations

You are helping the user operate the ZAD (Zelfservice Applicatie Deployment) platform using the `zad` CLI.

## Prerequisites

```bash
zad version
```

If not installed: `uv tool install -e /path/to/zad-cli`.

The user needs a `.env` file (or environment variables) with:

```
ZAD_API_KEY=sk-...
ZAD_PROJECT_ID=my-project
```

The API key comes from the Operations Manager web UI (project page).

## Common workflows

### Deploy

```bash
zad project deploy -d pr-42 --component web --image ghcr.io/org/app:pr-42

# Multi-component:
zad project deploy -d pr-42 \
  --components '[{"name":"web","image":"..."},{"name":"api","image":"..."}]'

# Clone config from existing deployment:
zad project deploy -d pr-42 --component web --image ... --clone-from production
```

### Add a component

```bash
zad component add api --image ghcr.io/org/api:v1 -d production \
  --port 8080 \
  -s postgresql-database \
  --memory-limit 512Mi \
  -e DB_HOST=localhost -e API_KEY=secret

# Or with env file:
zad component add api --image ... -d production --env-file .env.api

# Assign existing component to another deployment:
zad component assign api staging --image ghcr.io/org/api:v1
```

### Add a service

```bash
zad service add postgresql-database -c api -c worker
zad service add keycloak
```

### Resource tuning

```bash
zad resource tune                   # auto-tune all deployments
zad resource tune production        # tune specific deployment
zad resource sanitize               # disable broken deployments
```

### Create a new project

```bash
zad project create  # opens the self-service portal in the browser
```

### Refresh

```bash
zad project refresh                 # refresh all deployments from git
zad deployment refresh production   # refresh single deployment
```

### View logs

```bash
zad logs show -d production
zad logs show -d production --tail 100
zad logs stream -d production
```

### Backup and restore

```bash
zad backup create production
zad backup list production
zad restore project --yes
zad restore run production <backup-run-id> --yes
```

### Update image / delete

```bash
zad deployment update-image production --component web --image ghcr.io/org/app:v2.0
zad deployment delete pr-42 --yes
zad project delete --yes
```

### Task management

```bash
zad task list                       # list async tasks
zad task status <task-id>           # check task progress
zad task cancel <task-id> --yes     # cancel running task
```

## Configuration

Precedence: flags > env vars / `.env` > config file > defaults

| Setting | Flag | Env var / `.env` | Config file |
|---------|------|------------------|-------------|
| API key | `--api-key` | `ZAD_API_KEY` | - |
| Project | `-p` | `ZAD_PROJECT_ID` | - |
| API URL | `--api-url` | `ZAD_API_URL` | `api_url` in `~/.config/zad/config.toml` |

## Output formats

```bash
zad metrics overview --output json | jq '.cpu_usage'
zad backup list production --output yaml
```

## Error recovery

| HTTP Code | Diagnosis | Fix |
|-----------|-----------|-----|
| 0 | Network problem | Check connectivity, verify ZAD_API_URL |
| 401 | API key invalid | Get a fresh key from the Operations Manager web UI |
| 403 | Wrong project | Verify ZAD_API_KEY matches the project |
| 404 | Not found | Check project/deployment name spelling |
| 429 | Rate limited | Automatic retry with backoff |
| 5xx | Server error | Automatic retry |

## How to handle user requests

1. **"Deploy my app"** - `zad project deploy`
2. **"Add a database"** - `zad service add postgresql-database -c <component>`
3. **"Add a new component"** - `zad component add`
4. **"Tune memory/CPU"** - `zad resource tune`
5. **"Check if it's running"** - `zad metrics health` + `zad logs show`
6. **"Something is broken"** - `zad resource sanitize` + `zad logs show`
7. **"Roll back"** - `zad restore` or `zad deployment update-image`
8. **"Clean up PR environments"** - `zad deployment delete`
9. **"What's my task doing?"** - `zad task status <id>`
