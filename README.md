# zad-cli

CLI for ZAD (Zelfservice Applicatie Deployment) - the self-service Kubernetes deployment platform.

## Installation

The command is `zadctl`. `zad` is the same program under a second name, kept because that
is what existing scripts and pipelines type.

### A standalone binary (no Python needed)

Every release carries a binary per platform. Nothing else has to be installed.

They go in `~/.local/bin`, not `/usr/local/bin`: no `sudo`, nothing outside your own home
directory, and removing the CLI is deleting one file. Most shells already have it on
`PATH`; the check below says so if yours does not.

**macOS** (Apple Silicon: `darwin_arm64`, Intel: `darwin_amd64`)

```bash
mkdir -p ~/.local/bin
curl -fsSL https://github.com/RijksICTGilde/zad-cli/releases/latest/download/zadctl_darwin_arm64.tar.gz \
  | tar -xzf - -C ~/.local/bin zadctl
xattr -d com.apple.quarantine ~/.local/bin/zadctl 2>/dev/null || true
zadctl --version
```

That `xattr` line is the whole trick to avoiding *"zadctl cannot be opened because the
developer cannot be verified"*. macOS marks every downloaded file with a quarantine flag,
and Gatekeeper refuses anything unsigned that carries it. Removing the flag on a file you
fetched yourself, from a URL you can read in the command, is the same decision as the
right-click → Open dance, made once and visibly. Without the flag there is no warning, no
dialog, and no trip to System Settings.

**Linux** (`linux_amd64`)

```bash
mkdir -p ~/.local/bin
curl -fsSL https://github.com/RijksICTGilde/zad-cli/releases/latest/download/zadctl_linux_amd64.tar.gz \
  | tar -xzf - -C ~/.local/bin zadctl
zadctl --version
```

**Windows** (PowerShell, `windows_amd64`)

```powershell
$dir = "$env:LOCALAPPDATA\Programs\zadctl"
New-Item -ItemType Directory -Force -Path $dir | Out-Null
Invoke-WebRequest -Uri "https://github.com/RijksICTGilde/zad-cli/releases/latest/download/zadctl_windows_amd64.zip" -OutFile "$env:TEMP\zadctl.zip"
Expand-Archive -Force "$env:TEMP\zadctl.zip" -DestinationPath $dir
Unblock-File "$dir\zadctl.exe"
[Environment]::SetEnvironmentVariable("Path", "$([Environment]::GetEnvironmentVariable('Path','User'));$dir", "User")
```

`Unblock-File` is the Windows equivalent of the `xattr` line: it clears the "downloaded
from the internet" mark that makes SmartScreen interrupt. Open a new terminal afterwards so
the changed `PATH` applies.

**If the shell cannot find it afterwards**, `~/.local/bin` is not on your `PATH`:

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc   # or ~/.bashrc
```

**Verify what you downloaded.** Every release has a `SHA256SUMS` file next to the archives:

```bash
curl -fsSLO https://github.com/RijksICTGilde/zad-cli/releases/latest/download/SHA256SUMS
sha256sum -c SHA256SUMS --ignore-missing      # Linux
shasum -a 256 -c SHA256SUMS --ignore-missing  # macOS, which has no sha256sum
```

**Upgrading** is downloading again over the same file. **Removing** is `rm ~/.local/bin/zadctl`.

### With uv, from source

The binary is the way in. Choose this one instead when you are working on the CLI itself,
when you want a commit that has not been released yet, or when you import `zad_cli` as a
Python package rather than calling the command:

```bash
uv tool install git+https://github.com/RijksICTGilde/zad-cli.git      # latest
uv tool install git+https://github.com/RijksICTGilde/zad-cli.git@v0.10.0
```

`uv` brings its own Python, so this needs no Python installed either.

```bash
git clone https://github.com/RijksICTGilde/zad-cli.git
cd zad-cli
uv sync
uv run zadctl --help
```

The two installs are the same program: the binary is this code compiled, built from the
same flags by `scripts/build-binary.sh` and by the release workflow, and it is checked on
every build that it still reads short options such as `-c` and still carries the vendored
API spec and the service catalogue with it.

### When two installs get in each other's way

Having both is where "it behaved differently a minute ago" comes from: two names, two
places on `PATH`, and nothing on screen saying which one answered. `zadctl version` says
so, and warns on stderr when the other name is a different install:

```bash
zadctl version
# `zad` on your PATH is a different install: /usr/local/bin/zad reports zadctl 0.9.1.
```

Then pick one. `uv tool uninstall zad-cli` removes the Python install,
`rm ~/.local/bin/zadctl` removes the binary. If both survive, the one earlier on `PATH`
wins, and `command -v zadctl` tells you which that is.

### Tab completion

```bash
zadctl --install-completion       # bash, zsh, fish or powershell
```

Deployment, component and service names complete too. Service names come from the cached
catalogue and are instant; deployment and component names are fetched from the API, so
those cost a round trip per press.

## Quick start

Sign in with your own account, pick a project, and its API key is stored for you:

```bash
zadctl login
zadctl project use          # pick from a list of the projects you are a member of
```

`zadctl project use <name>` works too, and `zadctl project select` is the same command. Picking
needs a terminal: in a pipeline or with `-o json` it asks for a name instead of guessing.
After picking, nothing else has to be set: the project, its API key and the API they belong
to are written together, so later commands in this directory need no flags at all.

Already have an API key? `zadctl config init` writes a `.env.zadctl` interactively, or write one yourself:

```
ZAD_API_KEY=sk-...
ZAD_PROJECT_ID=my-project
```

Then use the CLI:

```bash
zadctl deployment create staging --component web --image ghcr.io/org/app:v1.0
zadctl logs production
zadctl backup create production
```

## The whole CLI in one call

```bash
zadctl guide                 # everything, as markdown on stdout
zadctl guide > GUIDE.md      # or into a file
zadctl guide --output json   # the same content as structure
zadctl guide --section auth  # one part; --section names the rest
```

`zadctl guide` is the answer to "how does this thing work" without running `--help` 100 times.
It carries the conceptual model, every command with its parameters and examples, the
service catalog and every setting with the layer that decides it. The command tree, the
examples, the services and the settings are read from the code and the API, so the guide
cannot fall behind them. It needs no credentials, so an agent can find out what ZAD offers
before logging in. For a worked end-to-end walkthrough against the sandbox, see
[docs/proefrit.md](docs/proefrit.md). What the CLI runs into and cannot fix on its own side
is collected in [docs/vragen-aan-rig-cluster.md](docs/vragen-aan-rig-cluster.md), one
document rather than a trail through commit messages; the handful of those that need an
answer before we can act is
[docs/rig-cluster-antwoord-gevraagd.md](docs/rig-cluster-antwoord-gevraagd.md).

## Discovering what ZAD offers

The CLI has no built-in list of services. It reads the platform's own catalog, so a
service added upstream shows up without a CLI release, and so a script or an agent can
find out what is possible without being told:

```bash
zadctl service list                                    # every service, and what you can set on each
zadctl service describe postgresql-database            # the full explanation, in Dutch, plus its variables
zadctl service config schema postgresql-database -o json   # the JSON Schema for a valid body
```

Configuring a service is the same command for every service:

```bash
zadctl service config set postgresql-database --set scope=project
zadctl service config set publish-on-web --component web -f web.yaml
zadctl service config clear redis
```

A service can accept config at more than one layer (`project`, `component`, `deployment`).
With one layer, `--target` is optional; with more than one it is required, because writing
project-wide config when you meant a deployment override is not something a default should
decide for you.

**Configuring a service is not the same as binding it**, and both are needed. `service
config set` sets the service up and provisions it; `--service` on a component is what makes
the platform inject that service's variables there:

```bash
zadctl component add web --service postgresql-database --service redis
zadctl component update web --service postgresql-database --service redis   # replaces the list
```

Leave the binding out and the component starts with no `DATABASE_*`, `REDIS_*` or `S3_*`
variable at all, however well the service itself is configured. Every command still
succeeds and nothing warns you, so the application is what finds out. `zadctl service
describe <name>` says which services need this: `binding: component` means each component
has to name it. Configure the service before you add the component that uses it, because a
component naming a service that is not configured yet is refused.

## Saving without rolling out

Saving a change and rolling it out to the cluster are two different things:

```bash
zadctl --no-rollout service config set redis --set instances=2
zadctl project pending      # what is saved but not live yet
zadctl project refresh      # roll everything out at once
```

`--rollout` is the default, so nothing changes unless you ask for it. That default is a
setting, so a project where changes are reviewed before they land can flip it once:

```bash
zadctl config set rollout false     # save by default
zadctl --rollout deployment create staging ...   # the flag still wins, per command
```

Precedence is **flag > `ZAD_ROLLOUT` > `zadctl config set rollout` > roll out**. With rollout
off, every mutating command ends by saying how many changes are waiting and how to roll
them out.

## Where can I reach it

```bash
zadctl deployment url production -c web    # one address, and nothing else
zadctl deployment describe production      # every address, with the state next to it
```

`deployment url` is there for `URL=$(zadctl deployment url production -c web)`, so a script
does not have to dig a value out of a task result whose shape was never promised.

An address exists as soon as the project file asks for one, which means a component that is
saved but not rolled out already has a URL that nothing answers on yet. `deployment
describe` prints the number of waiting changes above the addresses when that is the case,
so a 404 there reads as "not rolled out" rather than as a broken platform.

## What the CLI asks before it acts

Only taking something away, or writing older data over it, still asks: the `delete` and
`remove` verbs, `clear`, `unset`, the `restore` commands and the `admin` purges. Adding,
setting, updating, creating a deployment or a backup all just act. Thirty confirmations a
day teach you to type `y` without reading, and that habit is worth more than the prompts it
defeats.

Set `zadctl config set yes true` (or `ZAD_YES=true`, or `--yes` per command) and there are
none at all, which is what a script or an agent wants. Every command that changes something
also takes `--dry-run`, printing the method, the endpoint and the body it would send without
making the call.

## Configuration

| Setting | Flag | Env var / `.env.zadctl` | Default |
|---------|------|------------------|---------|
| API key | `--api-key` | `ZAD_API_KEY` | - |
| Project | `-p` | `ZAD_PROJECT_ID` | - |
| API URL | `--api-url` | `ZAD_API_URL` | production URL |
| SSO token | `zadctl login --token` | `ZAD_SSO_TOKEN` | - |
| Keycloak URL | `--keycloak-url` | `ZAD_KEYCLOAK_URL` | `https://keycloak.rijksapp.nl` |
| Keycloak realm | `--keycloak-realm` | `ZAD_KEYCLOAK_REALM` | `rig-platform` |
| Keycloak client | `--keycloak-client-id` | `ZAD_KEYCLOAK_CLIENT_ID` | `zad-cli` |
| Output | `-o` | `ZAD_OUTPUT_FORMAT` | `table` |
| Confirm | `--yes` | `ZAD_YES` | ask |
| Roll out | `--rollout` / `--no-rollout` | `ZAD_ROLLOUT` | roll out |
| No wait | `--no-wait` | - | wait |
| Strict | `--strict` | - | off |
| Refresh catalog | `--refresh-catalog` | - | cached 24h |

Precedence: **flags > exported environment variables > `.env.zadctl` in the working directory >
defaults**.

**There is one file: the `.env.zadctl` in the directory you run from.** Everything the CLI
remembers goes there, next to the project it belongs to. Nothing is written under `~`, so
two checkouts can work on two projects at the same time without deciding for each other
which one is active. The file is written mode 0600 because it holds the API key and the
access token, and `zadctl config list` warns when git would not ignore it.

Not plain `.env`: that name belongs to whoever reaches the directory first — docker compose,
a dotenv loader, a colleague's script. Writing there means editing a shared file and setting
it to 0600, which is a permission change nobody asked for, and it puts an SSO token in the
file most likely to be read by something else. `.env.zadctl` is covered by the usual `.env*`
ignore rule, so the token stays out of git without anyone having to think of it.

A `.env` that already carries `ZAD_` variables keeps being used, read and written, exactly as
before: a setup that worked yesterday does not break over a rename. After writing to one, the
CLI says once what it changed and how to move to `.env.zadctl`.

An exported variable still beats the file, which is what lets a script or a CI job be
explicit. `zadctl config list` says per setting which layer decided it, so a `.env.zadctl` that is
being overruled does not look like a bug.

```bash
zadctl config set api_url https://staging.example.com/api
zadctl config set rollout false     # save changes without rolling them out
zadctl config set yes true          # stop asking to confirm the obvious
zadctl config list                  # what is in effect, and why
```

`api_url`, `output`, `rollout`, `yes`, `keycloak_url`, `keycloak_realm` and
`keycloak_client_id` are the keys `config set` accepts; anything else is refused, so a typo
cannot sit in the file quietly changing nothing. The file may be edited by hand: it is a
plain `.env.zadctl`, and `ZAD_ROLLOUT=false` means the same as what `config set` writes.

`zadctl project use` writes the project **and its API key** together, so switching projects
cannot leave the previous key behind. To hand the settings to something else:

```bash
eval "$(zadctl project use my-project --export)"
```

Only `zadctl project list` and `zadctl project create` use the SSO token: you need a project's
name before you can have its key. Everything else uses the project API key.

No key is ever printed. `project list` answers with name, role and description in every
output format, so `-o json` is not a way around it, and there is no flag that turns it back
on: one command that can put every key you hold into a screen or a transcript is one command
too many. `project create` returns a key once and stores it for you, showing `(set)` rather
than the value. Nothing is logged, and `--verbose` prints method, path, body and params, but
never headers.

Use `--no-wait` to return a task ID immediately instead of waiting for async operations to
complete. Check progress with `zadctl task status <id>`.

### Which Keycloak `zadctl login` talks to

Three settings, not one issuer URL, because only the first one moves when you point the
CLI at another environment:

```bash
zadctl config set keycloak_url https://keycloak.test.example   # realm and client stay as they are
```

The issuer is composed as `{keycloak_url}/realms/{keycloak_realm}`; `ZAD_SSO_ISSUER` hands
over a full issuer URL and skips the composition. The access token must carry `zad-api` in
its `aud` or the API rejects it. `zadctl login` reads that claim (no signature check, that is
the API's job) and refuses to store a token without it, naming the client that needs an
audience mapper.

> `zadctl login` against production waits on Keycloak, not on this CLI: the client `zad-cli`
> does not exist in realm `rig-platform` yet. It has to be created as a public client with
> the device grant enabled, a `http://127.0.0.1:<port>/callback` redirect URI, and an
> audience mapper for `zad-api`. Until then, use `zadctl login --token` or `ZAD_SSO_TOKEN`.

## Output formats

Every command supports `--output` / `-o`: `table` (default), `json`, `yaml`. `--json` and
`--yaml` are shorthand for the same thing.

```bash
zadctl deployment list -o json | jq -r '.[].deployment'
zadctl service config get postgresql-database --yaml
zadctl config set output json          # make it the default here
```

Tables are drawn in ascii by default so they survive a copy, a paste and a terminal that
is not yours. `ZAD_TABLE_STYLE` takes `lines`, `ascii` or `plain`.

## Errors & exit codes

Errors tell you **what's wrong and what to do next**, with a neutral label for where
to look (your request, your application, your configuration, your credentials, or the
ZAD platform) instead of a bare HTTP code. A failed image pull points you straight at
the image and registry (`Source: your application (cluster runtime)`) with the fix.

Each error carries a structured diagnosis. In `--output json` it's a single object
on stdout you can branch on in CI/CD:

```bash
zadctl deployment create app -c web=img:tag -o json > out.json || jq -r .fault out.json
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
zadctl login / logout                sign in with your own account, forget the credentials
zadctl config      init, set, get, unset, list, path
zadctl project     list, create, use, describe, status, refresh, pending, delete, subdomains, check-subdomain
zadctl deployment  list, url, describe, create, update-image, refresh, delete
zadctl component   list, add, assign, update, delete
zadctl service     list, types, describe
zadctl service config  get, set, clear, schema
zadctl attachment  list, add, assign, update, delete
zadctl env         list, get, add, set, unset, clear      (a component's own variables)
zadctl alias       list, get, add, set, unset, clear      (platform variables under the names your app expects)
zadctl db schema   list, add, remove
zadctl registry    add
zadctl resource    tune, sanitize
zadctl task        wait, status, list, cancel
zadctl backup      create, list, status, delete
zadctl restore     list, project, backup, pvc, pvc-snapshots, database, deployment, bucket
zadctl clone       database, bucket, check
zadctl logs        [DEPLOYMENT] [-c component] [-n lines] [--since 1h]
zadctl admin       list, delete, orphan-report, orphan-confirm, cleanup, reconcile
zadctl open        project, portal, domains
zadctl version
```

On `env` and `alias`, the four verbs are four different endpoints and none of them is a
synonym for another: `add` refuses a key that already exists, `set` requires one that does,
`unset` removes named keys, `clear` removes everything at that layer.

### Commands that were removed

`zadctl service add` and `zadctl service delete` are gone; the endpoints behind them were
deprecated and withdrawn upstream. Configure a service per layer instead:

| Before | Now |
|---|---|
| `zadctl service add postgresql-database` | `zadctl service config set postgresql-database --set scope=shared` |
| `zadctl service delete postgresql-database` | `zadctl service config clear postgresql-database` |
| `zadctl service types` | `zadctl service list` (`types` still works as an alias) |
| `zadctl project list` (API key) | `zadctl project list` (after `zadctl login`) |

## Development

```bash
uv sync
uv run pytest
uv run ruff check .
uv run zadctl --help
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

Building the standalone binary locally, with the same flags the release uses:

```bash
scripts/build-binary.sh              # into dist/
scripts/build-binary.sh --install    # and into ~/.local/bin
```

It takes a few minutes, because Nuitka compiles rather than bundles, and it ends with the
same smoke test the release runs: the binary answers, and it brought the vendored spec and
the service catalogue along.

## License

EUPL-1.2
