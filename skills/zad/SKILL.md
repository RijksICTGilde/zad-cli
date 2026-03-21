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

Verify `zad` is installed and the API key is set:

```bash
zad version
echo $ZAD_API_KEY  # must be set
```

If `zad` is not installed: `uv tool install -e /path/to/zad-cli`.
If ZAD_API_KEY is not set: the user needs to get it from the Operations Manager web UI (project settings page).

## Common workflows

### Deploy a project

```bash
# Single component
ZAD_API_KEY=sk-... zad project deploy my-project \
  -d pr-42 \
  --component web \
  --image ghcr.io/org/app:pr-42

# Multi-component
zad project deploy my-project \
  -d pr-42 \
  --components '[{"name":"web","image":"..."},{"name":"api","image":"..."}]'

# Clone from existing deployment
zad project deploy my-project \
  -d pr-42 \
  --component web \
  --image ghcr.io/org/app:pr-42 \
  --clone-from production
```

### Create a new project

```bash
zad project create  # opens the self-service portal in the browser
```

### Check deployment status

```bash
zad metrics health
zad metrics overview
zad project subdomains my-project
```

### View logs

```bash
zad logs show my-project -d production
zad logs show my-project -d production --tail 100
zad logs stream my-project -d production
```

### Backup before risky operations

```bash
zad backup create my-project production
zad backup list my-project production
```

### Restore from backup

```bash
zad restore list <cluster> <namespace>
zad restore project my-project --yes
zad restore run my-project <backup-run-id> --yes
```

### Update a container image

```bash
zad deployment update-image my-project production --component web --image ghcr.io/org/app:v2.0
```

### Delete a deployment

```bash
zad deployment delete my-project pr-42 --yes
zad project delete my-project --yes
```

## Output formats

Every command supports `--output` / `-o`:

```bash
zad metrics overview --output json | jq '.cpu_usage'
zad backup list my-project prod --output yaml
```

## Error recovery

| HTTP Code | Diagnosis | Fix |
|-----------|-----------|-----|
| 0 | Network problem | Check connectivity, verify ZAD_API_URL |
| 401 | API key invalid or expired | Get a fresh key from the Operations Manager web UI |
| 403 | Key lacks permission for this project | Verify the key matches the project |
| 404 | Project or deployment not found | Check spelling |
| 429 | Rate limited | Automatic retry with backoff |
| 5xx | Server error | Automatic retry. If persistent, check platform status |

## How to handle user requests

1. **"Deploy my app"** - `zad project deploy` with appropriate flags
2. **"Check if it's running"** - `zad metrics health` and `zad logs show`
3. **"Something is broken"** - `zad logs show` and `zad metrics overview`
4. **"Roll back"** - `zad restore` from backup, or `zad deployment update-image` to pin old version
5. **"Clean up PR environments"** - `zad deployment delete`
6. **"Check cluster resources"** - `zad metrics cpu/memory/pods`
7. **"Custom Prometheus query"** - `zad metrics query '<promql>'`
