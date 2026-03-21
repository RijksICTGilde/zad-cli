---
name: zad
description: >-
  Deploy, manage, and troubleshoot applications on the ZAD platform. Use when
  the user mentions 'zad', 'deploy to zad', 'deployment', 'ZAD_API_KEY',
  'operations manager', 'backup', 'restore', 'zad project', 'zad logs'.
---

# zad - ZAD platform operations

You are helping the user operate the ZAD (Zelfservice Applicatie Deployment) platform using the `zad` CLI.

## Prerequisites

```bash
zad version            # verify installed
echo $ZAD_API_KEY      # must be set
echo $ZAD_PROJECT_ID   # optional, avoids repeating project ID
```

If `zad` is not installed: `uv tool install -e /path/to/zad-cli`.
If ZAD_API_KEY is not set: the user gets it from the Operations Manager web UI (project page).

## Common workflows

### Deploy

```bash
# With ZAD_PROJECT_ID set:
zad project deploy -d pr-42 --component web --image ghcr.io/org/app:pr-42

# Or explicit project:
zad project deploy my-project -d pr-42 --component web --image ghcr.io/org/app:pr-42

# Multi-component:
zad project deploy -d pr-42 \
  --components '[{"name":"web","image":"..."},{"name":"api","image":"..."}]'

# Clone config from existing deployment:
zad project deploy -d pr-42 --component web --image ... --clone-from production
```

### Create a new project

```bash
zad project create  # opens the self-service portal in the browser
```

### Check status

```bash
zad metrics health
zad metrics overview
zad project subdomains
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
zad restore run <backup-run-id> --yes
```

### Update image / delete

```bash
zad deployment update-image production --component web --image ghcr.io/org/app:v2.0
zad deployment delete pr-42 --yes
zad project delete --yes
```

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

1. **"Deploy my app"** - `zad project deploy` with flags
2. **"Check if it's running"** - `zad metrics health` + `zad logs show`
3. **"Something is broken"** - `zad logs show` + `zad metrics overview`
4. **"Roll back"** - `zad restore` or `zad deployment update-image` to pin old version
5. **"Clean up PR environments"** - `zad deployment delete`
6. **"Cluster resources"** - `zad metrics cpu/memory/pods`
7. **"Custom query"** - `zad metrics query '<promql>'`
