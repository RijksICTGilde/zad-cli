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
zad project use          # pick from a list of the projects you are a member of
```

`zad project use <name>` works too, and `zad project select` is the same command. Picking
needs a terminal: in a pipeline or with `-o json` it asks for a name instead of guessing.
After picking, nothing else has to be set — the project and its API key come from the
credentials store.

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

## The whole CLI in one call

```bash
zad guide                 # everything, as markdown on stdout
zad guide > GUIDE.md      # or into a file
zad guide --output json   # the same content as structure
zad guide --section auth  # one part; --section names the rest
```

`zad guide` is the answer to "how does this thing work" without running `--help` 100 times.
It carries the conceptual model, every command with its parameters and examples, the
service catalog and every setting with the layer that decides it. The command tree, the
examples, the services and the settings are read from the code and the API, so the guide
cannot fall behind them. It needs no credentials — an agent can find out what ZAD offers
before logging in. For a worked end-to-end walkthrough against the sandbox, see
[docs/proefrit.md](docs/proefrit.md).

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

`--rollout` is the default, so nothing changes unless you ask for it. That default is a
setting, so a project where changes are reviewed before they land can flip it once:

```bash
zad config set rollout false     # save by default
zad --rollout deployment create staging ...   # the flag still wins, per command
```

Precedence is **flag > `ZAD_ROLLOUT` > `zad config set rollout` > roll out**. With rollout
off, every mutating command ends by saying how many changes are waiting and how to roll
them out.

## Configuration

| Setting | Flag | Env var / `.env` | Default |
|---------|------|------------------|---------|
| API key | `--api-key` | `ZAD_API_KEY` | - |
| Project | `-p` | `ZAD_PROJECT_ID` | - |
| API URL | `--api-url` | `ZAD_API_URL` | production URL |
| SSO token | `zad login --token` | `ZAD_SSO_TOKEN` | - |
| Keycloak URL | `--keycloak-url` | `ZAD_KEYCLOAK_URL` | `https://keycloak.rijksapp.nl` |
| Keycloak realm | `--keycloak-realm` | `ZAD_KEYCLOAK_REALM` | `rig-platform` |
| Keycloak client | `--keycloak-client-id` | `ZAD_KEYCLOAK_CLIENT_ID` | `zad-cli` |
| Output | `-o` | `ZAD_OUTPUT_FORMAT` | `table` |
| Confirm | `--yes` | `ZAD_YES` | ask |
| Roll out | `--rollout` / `--no-rollout` | `ZAD_ROLLOUT` | roll out |
| No wait | `--no-wait` | - | wait |
| Strict | `--strict` | - | off |
| Refresh catalog | `--refresh-catalog` | - | cached 24h |

Precedence: **flags > exported environment variables > `.env` in the working directory >
defaults**.

**There is one file: the `.env` in the directory you run from.** Everything the CLI
remembers goes there, next to the project it belongs to. Nothing is written under `~`, so
two checkouts can work on two projects at the same time without deciding for each other
which one is active. The file is written mode 0600 because it holds the API key and the
access token, and `zad config list` warns when git would not ignore it.

An exported variable still beats the file, which is what lets a script or a CI job be
explicit. `zad config list` says per setting which layer decided it, so a `.env` that is
being overruled does not look like a bug.

```bash
zad config set api_url https://staging.example.com/api
zad config set rollout false     # save changes without rolling them out
zad config set yes true          # stop asking to confirm the obvious
zad config list                  # what is in effect, and why
```

`api_url`, `output`, `rollout`, `yes`, `keycloak_url`, `keycloak_realm` and
`keycloak_client_id` are the keys `config set` accepts; anything else is refused, so a typo
cannot sit in the file quietly changing nothing. The file may be edited by hand: it is a
plain `.env`, and `ZAD_ROLLOUT=false` means the same as what `config set` writes.

`zad project use` writes the project **and its API key** together, so switching projects
cannot leave the previous key behind. To hand the settings to something else:

```bash
eval "$(zad project use my-project --export)"
```

Only `zad project list` and `zad project create` use the SSO token: you need a project's
name before you can have its key. Everything else uses the project API key. Both responses
carry API keys, so they are masked in output unless you pass `--show-keys`, and never
logged.

Use `--no-wait` to return a task ID immediately instead of waiting for async operations to
complete. Check progress with `zad task status <id>`.

### Which Keycloak `zad login` talks to

Three settings, not one issuer URL, because only the first one moves when you point the
CLI at another environment:

```bash
zad config set keycloak_url https://keycloak.test.example   # realm and client stay as they are
```

The issuer is composed as `{keycloak_url}/realms/{keycloak_realm}`; `ZAD_SSO_ISSUER` hands
over a full issuer URL and skips the composition. The access token must carry `zad-api` in
its `aud` or the API rejects it — `zad login` reads that claim (no signature check, that is
the API's job) and refuses to store a token without it, naming the client that needs an
audience mapper.

> `zad login` against production waits on Keycloak, not on this CLI: the client `zad-cli`
> does not exist in realm `rig-platform` yet. It has to be created as a public client with
> the device grant enabled, a `http://127.0.0.1:<port>/callback` redirect URI, and an
> audience mapper for `zad-api`. Until then, use `zad login --token` or `ZAD_SSO_TOKEN`.

## Output formats

Every command supports `--output` / `-o`: `table` (default), `json`, `yaml`.

```bash
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
zad config      init, set, get, unset, list, path
zad project     list, create, use, describe, status, refresh, pending, delete, subdomains, check-subdomain
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
zad backup      create, list, status, delete
zad restore     list, project, backup, pvc, database, bucket
zad clone       database, bucket, check
zad logs        [DEPLOYMENT] [-c component] [-n lines] [--since 1h]
zad admin       list, delete, orphan-report, orphan-confirm, cleanup, reconcile
zad open        project, portal, domains
zad version
```

On `env` and `alias`, the four verbs are four different endpoints and none of them is a
synonym for another: `add` refuses a key that already exists, `set` requires one that does,
`unset` removes named keys, `clear` removes everything at that layer.

### Commands that were removed

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
