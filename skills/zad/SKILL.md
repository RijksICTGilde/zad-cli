---
name: zad
description: >-
  Deploy, manage, and troubleshoot applications on the ZAD platform. Use when
  the user mentions 'zad', 'zadctl', 'deploy to zad', 'deployment', 'ZAD_API_KEY',
  'operations manager', 'backup', 'restore', 'zad project', 'zad logs',
  'component', 'service', 'resource tuning'.
---

# zad - ZAD platform operations

You are helping the user operate the ZAD (Zelfservice Applicatie Deployment) platform. The
command is `zadctl`. `zad` is a second name for the same entry point, kept because existing
scripts and pipelines type it; both run the same program.

## Prerequisites

```bash
zadctl version
```

`version` also names a second install answering to the other name, with its path and the
version that binary reports. Two names are one program until they come from two installs,
and then the CLI seems to behave differently from one command to the next.

Not installed? The recommended way is the standalone binary from the releases page: no
Python, no `sudo`, one file in `~/.local/bin`. See the Installation section of the
repository README for the per-platform commands. From source it is
`uv tool install git+https://github.com/RijksICTGilde/zad-cli.git`.

The CLI keeps everything it remembers in one env file in the directory you run from, written
mode 0600. Nothing is stored under `~`, so two checkouts can work on two projects without
deciding for each other which one is active. `zadctl config path` says which file it is and
`zadctl config list` says what is in it and which layer decided each setting:

```
ZAD_API_KEY=sk-...
ZAD_PROJECT_ID=my-project
```

`zadctl config init` writes it interactively. `zadctl login` followed by `zadctl project use`
writes it for you, project and API key together.

## Before you script anything

**Answer the confirmations up front.** `zadctl config set yes true`, or `ZAD_YES=true`, or
`--yes` per command. Only taking something away or writing older data over it still asks:
the `delete` and `remove` verbs, `clear`, `unset`, the `restore` commands and the `admin`
purges. Creating and updating just act. A script that does not expect the remaining prompts
hangs on one rather than failing.

**Rehearse with `--dry-run`.** Every command that changes something prints the method, the
endpoint and the body it would send, and makes no call. It is the cheapest way to check a
`--set` landed as the type you meant.

**Use `-o json`.** Data goes to stdout, status and diagnostics to stderr, so stdout stays
parseable. `zadctl guide --output json` is the whole CLI as structure, and it needs no
credentials.

## The model

1. **The catalog is the platform's, not the CLI's.** `zadctl service list` reads what the
   platform offers, so a service added upstream shows up without a CLI release. Never
   assume a service name; look it up.
2. **Configuration sits in layers per service**: `project`, `component`, `deployment`. Which
   layers a service accepts comes from the catalog. With one layer `--target` is optional,
   with more than one it is required.
3. **Saving and rolling out are two things.** `--no-rollout` saves and leaves the cluster
   alone; `zadctl project pending` says what is waiting; `zadctl project refresh` rolls it
   all out.
4. **Configuring a service is not the same as binding it.** These are two halves of one
   thing, and both are needed. `service config set` sets the service up and provisions it;
   `component add --service <name>` is what makes the platform inject that service's
   variables into a component. Without the binding the component starts with no `DATABASE_*`,
   `REDIS_*` or `S3_*` variable at all, every command still succeeds, and nothing warns you.

## Common workflows

### Sign in and pick a project

```bash
zadctl login                  # opens the browser; --no-open prints the URL
zadctl project use            # pick from the projects you are a member of
zadctl project use my-project # or name it
```

Picking needs a terminal. In a pipeline or with `-o json` it asks for a name instead of
guessing.

### Look at what is there

```bash
zadctl project describe                    # services, components and deployments
zadctl project describe --part services
zadctl project status                      # the state, not just the contents
zadctl deployment list
zadctl deployment describe productie
zadctl deployment url productie -c web     # one address, nothing else
```

`deployment url` exists for `URL=$(zadctl deployment url productie -c web)`. An address
exists as soon as the project file asks for one, so a component that is saved but not
rolled out has a URL that nothing answers on yet. `deployment describe` says so above the
addresses when there are changes waiting.

### Deploy

```bash
zadctl deployment create pr-42 --component web --image ghcr.io/org/app:pr-42

# More than one component belongs in a manifest, not on a command line:
zadctl deployment create pr-42 --generate-skeleton > pr-42.yaml
zadctl deployment create pr-42 -f pr-42.yaml
zadctl deployment create pr-42 -f pr-42.yaml --set components[0].image=ghcr.io/org/app:v1.3

# Clone the configuration of an existing deployment:
zadctl deployment create pr-42 --component web --image ... --clone-from production
```

`deployment create` is an upsert: an existing deployment is updated rather than refused.

`--set` reads its value the way YAML does, so `true`, `false`, `null`, `~` and anything
numeric arrive typed. Quote to keep a string: `--set version="1.0"` is text, `--set
version=1.0` is a number. `none` is the word `none`, not null.

### Add a component

```bash
zadctl component add api --image ghcr.io/org/api:v1 --deployment production \
  --port 8080 \
  --service postgresql-database \
  --memory-limit 512Mi \
  -e DB_HOST=localhost -e API_KEY=secret

# Or read the variables from a file:
zadctl component add api --image ... --deployment production --env-file .env.api

# Define a component without running it anywhere yet, and attach it later:
zadctl component add worker
zadctl component assign api staging --image ghcr.io/org/api:v1
```

Two things account for most first crashes. **The image has to run as a non-root user**:
the platform starts containers unprivileged, so stock `nginx` crashloops on
`mkdir /var/cache/nginx: Permission denied` and needs `nginxinc/nginx-unprivileged` or
another image built for it. And **a port below 1024 cannot be bound**, so listen on 8080
rather than 80, which is also why `health-check` refuses a port under 1024.

`--path` is matched but not rewritten unless you say so. With `--path /api` the application
has to answer on `/api`; add `--rewrite /` to strip the prefix, which is what an
off-the-shelf image needs. Without it you get a 404 from the application while the
deployment reads as Healthy, because the platform did its part.

### Use a service

```bash
zadctl service list                                  # what the platform offers
zadctl service describe postgresql-database          # the full explanation, in Dutch
zadctl service config schema postgresql-database -o json   # the fields a valid body takes

zadctl service config set postgresql-database --set scope=shared
zadctl service config set publish-on-web --component web --set tls=standard
zadctl service config get postgresql-database
zadctl service config clear redis
```

And bind it to every component that needs its variables:

```bash
zadctl component add web --service postgresql-database --service redis
zadctl component update web --service postgresql-database --service redis   # replaces the whole list
```

`service describe` says which of the two a service needs: `binding: component` means it has
to be named on each component, `binding: deployment` means it is configured per deployment
and has no per-component binding.

### Environment variables and aliases

```bash
zadctl env list -c web
zadctl env add -c web FOO=bar            # a key that exists is a conflict
zadctl env set -c web FOO=baz            # a key that does not exist is an error
zadctl env unset -c web FOO
zadctl env clear -c web
zadctl env add -c web --deployment productie FOO=only-here
```

`add` and `set` look only at the layer you address. The deployment layer is its own store,
so the first override there is `add` even when the name already exists component-wide.
`zadctl alias` is the same set of verbs for platform variables under the names your
application expects.

### Save without rolling out

```bash
zadctl --no-rollout service config set redis --set instances=2
zadctl project pending      # what is saved but not live
zadctl project refresh      # roll everything out at once
```

`zadctl config set rollout false` makes saving the default; the flag still wins per command.

### Refresh

```bash
zadctl project refresh                 # every deployment, from git
zadctl deployment refresh production   # one deployment
```

### Resource tuning

```bash
zadctl resource tune                   # auto-tune all deployments
zadctl resource tune production        # one deployment
zadctl resource sanitize               # disable broken deployments
```

### View logs

```bash
zadctl logs production
zadctl logs production -n 100
zadctl logs production -c web
zadctl logs production --since 1h
```

### Backup and restore

```bash
zadctl backup create production
zadctl backup list production
zadctl restore list
zadctl restore backup production <backup-run-id> --yes
zadctl restore project --deployment production -c web --storage data --yes
```

`restore project` restores one storage volume of one component, not the whole project.
`zadctl restore list` says which snapshots exist.

### Update image, delete

```bash
zadctl deployment update-image production --component web --image ghcr.io/org/app:v2.0
zadctl deployment delete pr-42 --yes
zadctl project delete --yes
```

A new image on an existing deployment is `deployment update-image`, not another
`deployment create`.

### Tasks

```bash
zadctl task list                       # list async tasks
zadctl task status <task-id>           # check task progress
zadctl task wait <task-id>             # block until it completes
zadctl task cancel <task-id> --yes     # cancel a running task
```

Mutating commands wait for their task by default. `--no-wait` returns the task ID instead.

### Create a new project

```bash
zadctl project create "My Project" --description "What this project is for"
zadctl open portal   # or do it in the self-service portal
```

You give a display name; the technical name is derived from it and comes back in the
response, together with the API key, which is stored for you.

## Configuration

Precedence: **flags > exported environment variables > the env file in the working directory >
defaults**. `zadctl config list` says per setting which layer decided it.

| Setting | Flag | Env var | Default |
|---------|------|---------|---------|
| API key | `--api-key` | `ZAD_API_KEY` | - |
| Project | `-p` | `ZAD_PROJECT_ID` | - |
| API URL | `--api-url` | `ZAD_API_URL` | production URL |
| Output | `-o` | `ZAD_OUTPUT_FORMAT` | `table` |
| Confirm | `--yes` | `ZAD_YES` | ask |
| Roll out | `--rollout` / `--no-rollout` | `ZAD_ROLLOUT` | roll out |

## Output formats

```bash
zadctl deployment list --output json | jq '.[].deployment'
zadctl backup list production --output yaml
```

## Error recovery

Errors carry a diagnosis: what is wrong, a neutral label for where to look, and a next
step. In `--output json` it is one object on stdout with a `fault` field to branch on:
`UserInput`, `UserApp`, `UserConfig`, `Auth`, `Platform`, `Network` or `Unknown`.

| Exit code | Meaning | What to do |
|-----------|---------|------------|
| `0` | success | - |
| `1` | your fault: bad input, application or configuration failure, auth | fix it and retry |
| `2` | platform or network, transient | retry |
| `3` | unknown, the API gave no signal to attribute it | check the logs |

`--strict` makes a command that succeeds but reports warnings, such as a deploy that
applied while a component is crash-looping, exit non-zero, so a pipeline fails instead of
going green on an unhealthy application.

## Commands that no longer exist

| Before | Now |
|---|---|
| `zad service add <name>` | `zadctl service config set <name> ...` plus `zadctl component add --service <name>` |
| `zad service delete <name>` | `zadctl service config clear <name>` |
| `zad metrics overview` / `zad metrics health` | `zadctl deployment describe` and `zadctl project status` |
| `zad service types` | `zadctl service list` (`types` still works as an alias) |

## How to handle user requests

1. **"Deploy my app"** - `zadctl deployment create`
2. **"Add a database"** - `zadctl service config set postgresql-database ...` and then
   `zadctl component add <component> --service postgresql-database`, because configuring
   without binding gives the component nothing
3. **"Add a new component"** - `zadctl component add`
4. **"Tune memory/CPU"** - `zadctl resource tune`
5. **"Check if it's running"** - `zadctl deployment describe` + `zadctl logs`
6. **"Where can I reach it"** - `zadctl deployment url <deployment> -c <component>`
7. **"Something is broken"** - `zadctl project status`, `zadctl logs`, `zadctl resource sanitize`
8. **"Why is nothing happening"** - `zadctl project pending`, then `zadctl project refresh`
9. **"Roll back"** - `zadctl restore` or `zadctl deployment update-image`
10. **"Clean up PR environments"** - `zadctl deployment delete`
11. **"What's my task doing?"** - `zadctl task status <id>`
12. **"What can this platform do?"** - `zadctl guide` and `zadctl service list`, neither of
    which needs credentials
