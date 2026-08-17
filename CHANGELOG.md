# CHANGELOG

<!--
Automatically maintained by python-semantic-release.
See: https://python-semantic-release.readthedocs.io/
-->

## Unreleased

### Fixed
- **`deployment create -c a -c b -c c --image x` attached only `c`.** `--component` was a
  single value, so Click kept the last one and the other two vanished: no error, no warning,
  and `deployment describe` afterwards was the first place it showed. It is repeatable now
  and every component named gets the image — which is the ordinary shape of an app whose
  parts come out of one repository.
- **`config get api_key` printed the project's key.** So did `config get token` with the SSO
  token. That is the hole `project list --show-keys` was removed for, one command over: an
  agent quoting the output into a transcript leaked a credential that does not expire.
  Secrets are now reported as `(set)` / `(not set)`, and the SSO token as the same expiry
  line `config list` shows. There is deliberately no flag to override it.
- **`config get sso_token` said "not set" about a token it had just displayed.** `config
  list` names the setting `sso_token`; the env file calls the variable `token`. Both
  spellings resolve now, because reading a name the CLI itself prints and being told it is
  unset is the worst of the two answers.
- **`project status` printed a literal `[green]Healthy[/green]`** wherever there was no
  terminal. Escaping every cell was right — a config `pattern` with square brackets was
  being swallowed — but it also escaped the one string that really was markup. The status
  cell says so by its type now.
- **A truncated error no longer wins over the whole one.** The platform sends the same
  failure twice: flat and cut to a fixed length, and again on the subtask that raised it, in
  full. A practice run read `...lists the actions that put s` as its explanation while the
  complete sentence sat three lines lower. When the short one is the start of the long one,
  the long one is shown. Nothing is invented: it picks between two strings the API sent.
- `zadctl service temp-storage add --help` gave an example mounting at `/data`. The two
  storage groups come out of one factory, and the mount path did not travel with the service
  name; `/tmp` is where an ephemeral volume goes.
- **`service assign` bound nothing whenever the service was already configured — and the
  platform fixed it the same evening.** `POST /services` used to short-circuit the whole
  request the moment the service was already selected for the project, while still answering
  `components_updated` with the names you asked for. A practice run lost an
  `authorization-wall` to that: `success`, `components updated: frontend`, no binding, and a
  public URL answering 200 with no wall in front of it. Since configuring a service before
  binding it is the normal order, the broken branch was the common one.

  Reported as point 19; the endpoint now binds the components either way and says so in its
  description. The workaround this CLI carried for a few hours — the binding through
  `add_services` on each component — is gone again, measured against the sandbox before it
  was removed. What stays is the guard: playbook 01 binds a service configured one step
  earlier and then reads `component list`, instead of believing the answer.
- **`project check-subdomain` needs a project, and works.** The endpoint moved to
  `/v2/projects/{p}/subdomains/check/{sub}`, which is what made it answer at all: the
  platform legitimises an API key against the project it finds in the *route*, so the old
  route without one refused every call — 401 for a week, then 404. Two practice runs read
  that refusal as "this name is taken". `ZadClient.check_subdomain` takes the project as its
  first argument; the two-argument form called a path that no longer exists, so the baseline
  in `tests/test_backwards_compat.py` moved with it.
- **A union error now names the shapes it will take.** `--set restrict-access.enabled=true`
  answered "does not match any of the accepted shapes for this field", while the schema three
  lines down spells out that enabling the restriction means naming a `role` or a
  `realm-role`. Someone had to open the raw schema to find that out. It now reads: *needs one
  of enabled=false; with 'role'; with 'realm-role'.* And `anyOf: [X, null]` — how a
  Pydantic-generated spec spells every optional field — no longer counts as "two accepted
  shapes"; the complaint from the one real branch is reported instead.
- **The 404 hint no longer sends you to `zadctl deployment list`.** It said that for every
  404 in the CLI, including a subdomain check, because it has no idea which kind of name you
  referenced. It now names `zadctl project describe`, which is true for all of them.

### Added
- **The playbook runner takes several playbooks, and `-j` plays them at once.** Each in its
  own process with its own working directory and its own project, so nothing is shared and
  the teardown guarantees hold per playbook. Measured: 6:02 for all four against 8 minutes
  one after another — a quarter faster, not the two thirds "the longest instead of the sum"
  suggests, because they do share one cluster and four rollouts wait on each other. The
  sign-in is serialised with a lock: four concurrent headless logins as the same user left
  three waiting for a callback that never came, and `login-headless.py` now also prints the
  page it got stuck on instead of a bare playwright timeout.
- **`--base-domain` and `--domain-format` complete on `deployment create`.** The domains a
  project's cluster offers live behind an `x-choices-source` that only `service describe`
  resolved, so a practice run read the platform's source to learn its own domain was on
  offer. The lookup is by field name across the spec's schemas — the spec hangs the source on
  the field, not on the flag — so a second command that writes the same field gets it free.
  `--domain-format` reads its eleven templates off the enum in the request schema.

### Changed
- **`zadctl login` no longer asks whether to pick a project.** It asked "Pick an active
  project now?" and opened the picker on yes, which is a question standing in front of an
  answer: you came to sign in and got a prompt about something else. It now names the ways
  on — `project use` to pick from a list, `project use <name>` when you know it — and picks
  nothing by itself. It also does not print the project list: someone who is a member of
  thirty gets a screen of names they did not ask for and still has to type one. The list is
  one command away for whoever wants it.
- **`GET .../clusters` is no longer listed as deferred**, which it should never have been:
  the CLI already calls it — that is where `service describe publish-on-web` gets its base
  domains — and it is the only place those domains are written down. It moves to the generic
  coverage list, where an endpoint reached through a path built at run time belongs.
- The guide says to quote anything with brackets. `zsh` treats `--set roles[0].name=x` as a
  glob and refuses the command before this CLI is started at all, so nothing here can catch
  it; two calls in a practice run died that way.

### Removed (breaking)
- **`deployment create --components '<json>'`.** The flag took the component list as a JSON
  string on the command line; `-f/--file` takes the same list as a document and builds an
  identical request. It has warned since it was deprecated, and the one consumer that used
  it — `zad-actions`, in its `deploy` action — moved to `-f -` in its v0.10.0 bump, so there
  is nothing left pinned to it. This is the "we changed our mind" kind of removal, not the
  "it never worked" kind: JSON quoting inside a shell argument is a way to lose an hour to a
  quote, and a second spelling of the same thing is a second thing to keep working.

  If you still pass it, the shape is the same one level up:

  ```sh
  # was
  zadctl deployment create staging --components '[{"name":"web","image":"ghcr.io/org/app:v1"}]'
  # now
  echo '{"components":[{"name":"web","image":"ghcr.io/org/app:v1"}]}' | zadctl deployment create staging -f -
  ```

  `tests/test_backwards_compat.py` gained a `REMOVED_OPTIONS` baseline alongside
  `REMOVED_COMMANDS`, which checks the flag is gone from the help *and* refused when passed.
  An option that is only undocumented still works, and that is the worst of the three
  states: nobody can find it and nobody can ever drop it.

### Changed
- **A refused approval fails `--strict`; a pending one does not.** The platform made
  `approvals.status` a real enum this week — `none | requested | denied` — and said why in
  the schema: a pipeline should fall over on a refusal and wait on a request. A refused
  domain does not stop a deployment, it publishes on the cluster's own address instead:
  healthy, answering, on a name nobody asked for, which is exactly the state that should
  not pass quietly. A conformance test pins those three values, so a fourth arrives as a red
  build rather than as silence.
- **A value the platform filled in is shown.** Leave an invitation key empty and it
  generates one, reported under `generated` — and the write is the only place you ever see
  it. Swallowed, the invite you just made cannot be sent to anybody.
- **A write is validated against the spec of the API you are pointed at.** `describe` read
  the live spec from the day it learned to; `config set`, `config patch` and `config schema`
  kept reading the copy that shipped with the CLI — and that is the half where it costs
  something. The platform expressed a rule this week that it had only enforced at rollout
  time (`restrict-access` needs a role), so validating against last month's copy meant
  sending a body the API refuses for a reason we could have named locally. It now refuses
  it here.
- **A field the platform writes is not named as a casualty.** The warning about what a
  `set` would drop listed `keycloak.realms`, which the API marks `x-platform-managed` and
  describes as "carried over on a write, so a caller neither has to send it nor can lose it
  by leaving it out". That is not a warning, it is a false alarm about the one part of the
  document nobody can break.
- **Every service shows a line you can run.** `zadctl service describe aliases` printed the
  service, its layers and its variables, and not one example of using it — and the same held
  for `attachments`, `user-env-vars` and the two storage services. The examples were built
  from the config schema, so a service that carries a *set of entries*, or values instead of
  config, or no layer at all, produced no field table and lost the example with it. Those
  five are driven by verbs of their own, so the examples now come from those verbs' own
  docstrings, which is where this CLI already keeps them and where `zadctl guide` already
  reads them: one copy, and `zadctl service <name> --help` carries it too. For the four the
  platform runs by itself (`platform`, `deployment-health`, `resource-tuning`,
  `namespace-redis`) there is no call to show, and that is now a sentence saying so rather
  than an empty space where the example should have been.
- **`zadctl service temp-storage` stops giving persistent-storage examples.** One factory
  builds both groups and the example lines were written out once, so every `--help` under
  temp storage named the other service — harmless to read, wrong to paste.
- **`service config set` says which settings it would drop.** It writes the document whole
  — a field you do not name is removed, not left alone — and the only place that was said
  out loud was the list-shaped blocks. A practice run set `restrict-access.enabled` on
  keycloak and lost the `template=sso-only` from an hour earlier, with nothing on screen to
  say so; `--dry-run` shows the body going out, which is exactly the half that looks like a
  merge. The current document is read first, and the warning names what this call does not:
  "template, realm-roles would be removed". Only when there is something to lose, so a first
  write stays quiet, and it is a read for the warning only — what gets sent is still exactly
  what you asked for, so no merge this CLI invented can lose a race.
- **Tables are drawn with lines by default, not ascii.** Ascii had its own good reason — it
  survives every terminal, every font and every paste into a ticket — but it made the table
  the odd one out: the panels, the rules and the diagnoses around it are all drawn with box
  characters, so an ascii table in the middle read as something pasted in from another
  program. `zadctl config set table_style ascii` is one command away and still there. A
  console whose encoding cannot carry the characters still gets ascii, because that is not
  taste: a table of replacement glyphs is worse than a plain one.
- **`component list` lists components, not deployment couplings.** The rows came from the
  deployments endpoint, so a component that was only defined — the state `component add`
  without `--deployment` calls a valid one — was invisible until something referenced it:
  three successful adds followed by "No results.". The list now comes from the project's
  component definitions, with deployments as a column, so unattached components show up
  with `-`. `-d` still filters, now on the attachment. The old `namespace` column moved to
  `deployment describe`, where it answers a question about a deployment.
- **`--dry-run` no longer demands an API key it would never send.** Any string satisfied
  the check, because nothing called the API — which is the whole point of a dry run.
  Checking a command before you have credentials is now the intended path, not a
  `ZAD_API_KEY=dummy-key` workaround.
- **`config unset` accepts `project` and `api_key`.** `config list` showed both among the
  settings but refused to remove them, so dropping an active project meant stripping lines
  by hand or throwing the whole session away with `logout`. Setting them stays with
  `zadctl project use`, which writes project, key and API URL together; the list now names
  that in a "managed by" column instead of letting the refusal be the discovery.
- **`config list` and `config path` warn when a directory holds both `.env` and
  `.env.zadctl`.** Only one of them is read, and without the warning the other one looks
  loaded while it is not — the quietest way to talk to the wrong API.
- **`deployment describe` draws its tables like every other command** (it silently used
  Unicode boxes, ignoring `table_style=ascii`) and shows what its own endpoint does not
  carry: ports, services and attachments per component, from the project's definitions.
- **`project create` says that the creation itself counts as a saved change.** The API
  records it as one, so `project pending` shows 1 right after a create even with rollout
  on; without the note that reads as the rollout setting being ignored.
- **`attachment unassign` names the binding it leaves behind.** Uncoupling the file does
  not take `attachments` out of the component's service list, which then reads as "has
  attachments" where none are left; the note points at `service unassign attachments`.
- **A layer nobody can write is labelled in the guide table and in the `--target` error,
  not offered as a valid pick.** `service describe` already marked it; the other two now
  say the same thing.
- `config list` says when the refresh token has expired too, not just the access token;
  "EXPIRED — run `zadctl login`" used to leave open whether a refresh would still save you.
- The `alias` help quotes its example: `'POSTGRES_HOST=$DATABASE_SERVER_HOST'`. Unquoted,
  the shell expands the `$` to nothing and the API's 422 is where you find out.
- **`component update --service` adds instead of replacing.** It used to send exactly the
  services you named, so binding one unbound every other one — on a command whose own help
  says "Only the fields you specify change; all others remain as-is". A practice run lost
  its attachment coupling that way while unpublishing a component, with nothing on screen
  to say so. Taking a service away is now `--remove-service`, and `--replace-services`
  makes your list the complete one; both say out loud what they do.

  The list is no longer assembled here either. Naming one service used to mean sending all
  of them, and a list rebuilt from bare names lost the per-component config behind each —
  attachment couplings, storage mounts, `tls`. The API grew `add_services` and
  `remove_services` in answer to that, so the merge happens where the data is: nothing is
  read first, and two callers adding at the same moment cannot overwrite each other.
- `service describe` and `service list` mark a config layer this CLI cannot write, instead
  of advertising it like any other. `publish-on-web` lists `deployment-component` with no
  endpoint behind it; trying it gave a good error, but you had to try.
- Waiting for a task starts at 0.3s and grows to the same 3s ceiling, instead of sleeping a
  flat 3s from the first look. The sleep also sat at the *end* of the loop, so a task the
  platform finished in a second still cost three: measured against the sandbox, `env add`
  took 3.07s of which 1.4s was the platform. Twenty mutating steps in a playbook spent over
  half a minute waiting for nothing. A rollout is still polled once every three seconds,
  which is where a gentle rate is actually wanted.
- **The settings file is `.env.zadctl`.** `.env` is the name every other tool in a directory
  also claims, and writing there meant editing a file that is not ours and setting it to
  0600 — a permission change nobody asked for on a file docker compose or a dotenv loader is
  also reading — with an SSO token in it. `.env.zadctl` is covered by the usual `.env*`
  ignore rule, so the token stays out of git by default. A `.env` that already carries
  `ZAD_` variables keeps being used, read *and* written, so no working setup breaks; after
  writing to one, the CLI says once what it changed and how to move over. A `.env` without
  `ZAD_` variables is now left completely alone.
- `attachment list` answers with one shape in every state. It used to return couplings
  (`reference`, `component`, …) once something was coupled and a catalogue (`id`,
  `filename`, …) before that, so a script reading `.reference` worked only after the first
  `assign` — and the run that uploaded the file was exactly the run where it did not. A file
  nothing uses yet is now a row with the coupling columns empty, and every row carries the
  filename.
- **The command is called `zadctl`.** `zad` stays as a second name for the same entry
  point, so existing scripts, playbooks and pinned pipelines keep working, but the help,
  the guide, the examples and the documentation all say `zadctl` now. A tool whose
  documentation names a different program than the one you installed is a tool you have to
  second-guess.
- `zadctl version` names any *other* install answering to the other name, with its path and
  the version that binary reports, and says so on stderr. Two names are one program until
  they come from two installs; before this, that difference read as a platform behaving
  differently from one minute to the next.

### Added
- **`zadctl service sleep-mode status` and `wake`.** The two endpoints the CLI deferred as
  "a separate feature" until a practice run turned sleep-mode on and had no way to show it
  worked. A caveat measured against the sandbox rather than read off the spec: the platform
  gates both on an `X-Wake-Token` header instead of the project API key, and documents
  neither the header nor where a token comes from, so the commands take `--wake-token`
  (`ZAD_WAKE_TOKEN`) and say why.
- **`zadctl env add backend APP_MODE=demo`**, with the component first, the way
  `attachment assign` has taken it for a while. It used to fail with "Missing option
  '--component'". Only where it cannot be misread: a value is `KEY=VALUE`, so a first word
  without an `=` is not one. `unset` and `list` take bare keys and keep `-c`, because there
  a leading word could be either and guessing would eventually delete the wrong thing.
- **`--set <TAB>` completes the options of the service you are configuring, and their
  values.** Before the `=` the options `describe` lists, nested ones included, so
  `inbound[0].from.` keeps going. After it the values: what the API states as choices, the
  examples it offers, and for a project-dependent field the endpoint it names — which is
  what `x-choices-source` was for. `--set waker-component=<TAB>` offers your components.

  It needed a repair underneath: completion callbacks read `ctx.obj["settings"]`, and a
  completion runs before the command does. Click builds the contexts it needs to work out
  what you are typing but never invokes the callback that fills `ctx.obj`, so every one of
  them got `None`, returned an empty list, and looked exactly like "nothing matches".
  Service names, deployment names and component names have never completed. They resolve
  their own settings now, from the environment and this directory's env file.
- **`zadctl service <name>` works for every service, and its `--help` is the short form of
  `describe`.** It answered "No such command" for sixteen of the twenty-one, while five
  (`attachments`, `aliases`, `user-env-vars` and the two storages) did work — because those
  happen to need their own verbs. Which five is not something anyone can be expected to
  know, and "it depends on the shape of its config document" is not an answer to give
  someone who typed the name of a service. Every name now resolves, from the catalog rather
  than from a list in the code, so a service the platform adds tomorrow works tomorrow; the
  five keep their verbs, and the rest describe themselves. `zadctl service <name> --help`
  is the short version — what it is, the command that configures it, its options and their
  values — and `zadctl service describe <name>` stays the long one. A near miss now names
  the service it thinks you meant.
- **A field whose values come from your project shows your project's values.** The API
  marks those with `x-choices-source` — 21 fields, and the ones where a wrong guess costs
  you a 422: `waker-component` and `root-component` are your components, `attachment` is
  your catalogue, the `cross-domain-access` peer fields are the projects you may see. It
  cannot be an `enum`, and the spec says why: "An enumeration here would be one project's
  snapshot and wrong for every other." So it names the endpoint that has the real list, and
  `describe` now calls it: `waker-component` reads `worker | backend | frontend` instead of
  `<text>`. Without a project or a key it names the source instead ("the components of this
  project"), because `describe` answers without credentials and must keep doing so, and a
  placeholder this run cannot fill (`{peer_project}`) is never guessed at. `-o json` carries
  the whole source object, so an agent can call that endpoint itself. One request per
  endpoint per table, no retries: an enrichment that fails must cost nothing.

  Those values are marked `+` and the table says which project they came from, because the
  cell reads exactly like a platform rule (`auto | confirm | manual`) while it is one
  project's answer at one moment — and a transcript keeps neither the project nor the
  moment. `zadctl service <name> --help` reads them too when a project is selected: it
  already fetches the spec, so "select a project to see the current ones" printed to
  someone who *has* one selected was the CLI not knowing what it had just done. Without a
  project it names the source instead. The help text is built when it is asked for, so
  running `zadctl service sleep-mode` does not fetch a list it never shows.
- **The examples the API offers are shown, and the example line survives your shell.**
  `match` on sleep-mode — "which deployments are in scope", with a syntax of its own — read
  `<text>`, while the platform answers it with `pr-*`, `*-preview`, `acceptatie`. They sit
  on the *item* of the array, so reading the field alone missed them; 72 fields across the
  spec carry examples and none of them were shown. They appear as `e.g. ...`, because
  illustrations are not a rule.

  And a `--set` flag is now quoted when a shell would take it apart. `--set match[0]=pr-*`
  is two globs in one flag: zsh answers "no matches found" and the command never runs, and
  `<value>` is a redirection. The rule is the same one the `alias` example already followed
  after the `$` in `$DATABASE_SERVER_HOST` expanded to nothing.
- **A menu is not presented as the closed set.** The API documents the difference and it
  changes what the column means: `enum` is "those values and nothing else", `x-choices` is
  what the portal offers — and without an `enum` the field takes more than the list shows
  (`sleep-after-deploy` accepts any duration, `90m` included). Listing the eight it offers
  as if they were the rule is how a reader concludes `90m` is invalid and works around a
  restriction that was never there. An open list now reads `e.g. 5m | 4h | ...`; a closed
  one stays bare.
- **The spec the CLI reads is the one the API publishes.** It was the copy vendored at
  release time, and what that copy lacks is exactly what a reader wants: the platform has
  since annotated a dozen fields with `x-choices` — the values it accepts, each with a
  label — so `sleep-after-deploy` could only be described as `<text>` while the API had
  been listing `5m | 4h | 8h | 12h | 24h | 48h | 72h | 168h` all along. A command whose
  whole job is "what does this platform offer" cannot answer from a snapshot of last
  month. It is read the way the service catalog already is: live, cached for an hour
  (`--refresh-catalog` forces a fetch, `ZAD_CATALOG_OFFLINE` forbids one), and the bundled
  copy when the network says no — so `describe` still answers without a project, a key or
  a connection. The spec is public and needs no credentials, and lives beside the API
  rather than under it (`/openapi.json`, not `/api/openapi.json`).
- **`service describe` states every constraint the API states.** Not just enums: a range
  (`<number 1024-65535>`), a length, a pattern, `multipleOf`, `minItems`/`uniqueItems` on a
  list. Each was already in the spec and each was a 422 waiting to happen. In `-o json`
  every choice also carries its label (`168h` is "7 dagen"), which is the form an agent
  reads and the terminal has no width for.
- **`service describe` shows what you can set, and a line that sets it.** It named the
  command (`use: zadctl service config set sleep-mode`) and stopped there, so the first
  field was one call further on in `service config schema` — which is where a reader who
  came to `describe` asking "how do I use this" stops looking. Every layer now gets a table
  of its options and an example built from that schema rather than written out per service.

  The table is in the CLI's words, not the schema's: the option column is the key as you
  type it after `--set` (so `match[0]`, and `inbound[0].from.project` for a nested one,
  because a list is set per entry and a bare name earns a 422), and the values column is
  what may follow the `=`. Where the API constrains that, it says so — `true | false`,
  `auto | confirm | manual`, `<number 1024-65535>`, `<text: max 40, ^[a-z0-9]([-a-z0-9]*[a-z0-9])?$>`.
  Where it does not, a placeholder. `zadctl service config schema` still prints the schema
  itself, for validating a manifest.

  Two rules about the example, both learned from what the first version generated. A body
  with more than one shape is described per shape: `postgresql-database` is a `oneOf`, and
  reading only the top level showed nothing at all for it; the variants are labelled by the
  field that picks them (`scope=shared`, `scope=project`). And an example never demonstrates
  switching something off — the first version proposed `--set acl-key-prefix=false` for
  redis, which drops the restriction to the project's own keys, and `--set scheme=none` for
  health-check, which disables the probes. Both were "the value that changes something",
  which is the wrong thing to optimise for in the one line someone is most likely to paste.
- `zadctl config list` shows the SSO token: valid until when, or expired and how to fix it.
  It is the credential that decides whether `project list` and `project create` work at
  all, and it was the one setting the table did not mention. Two independent practice runs
  lost their first minutes to a token that had expired overnight while every other setting
  looked right. The expiry is in the token, so this costs no call.
- A table that does not fit shows the columns that do, in the order the command asked for,
  and names the ones left out on stderr. `attachment list` in an 80-column terminal used to
  render "Referen…", "Compone…" and "/etc/ap…": truncated to a stub is worse than absent,
  because it looks like an answer.
- `zadctl project delete --ignore-not-found`, spelling the same idea as on `deployment
  delete`: a teardown step runs precisely when something earlier went wrong, so "it is
  already gone" is the outcome it wanted. It covers both ways a project can be absent —
  the API not knowing it, and there being no active project left, which is what the *first*
  successful delete leaves behind when it clears the .env.
- `zadctl guide` explains the whole CLI in one call: the model behind ZAD, every command with
  its parameters and examples, the service catalog and the settings with their precedence.
  Markdown on stdout (`zadctl guide > GUIDE.md`), `--output json` for the same content as
  structure, `--section <name>` for one part. It needs no credentials, and the command tree,
  examples, services and settings are all derived — a new command lands in the guide by
  existing, and CI fails if it does not.
- `zadctl project use` without a name opens a list of the projects you are a member of and
  makes the one you pick active. `zadctl project select` is the same command. The list shows
  no API keys; without a terminal (a pipe, CI, `-o json`) it asks for a name instead of
  guessing.
- `zadctl project list` marks the active project with a `*`.
- `zadctl login` ends with who you are and the next step: the picker when there is a terminal
  and no active project yet, otherwise the command to run.
- The rollout default is a setting: **flag > `ZAD_ROLLOUT` > `zadctl config set rollout` >
  roll out**. `zadctl config list` shows every setting in effect and which layer decided it.
- The Keycloak `zadctl login` uses is three settings — `keycloak_url`, `keycloak_realm` and
  `keycloak_client_id` — each through **flag > env (`ZAD_KEYCLOAK_*`) > config > default**.
  The issuer is composed as `{keycloak_url}/realms/{keycloak_realm}`, so pointing the CLI
  at a test Keycloak is one setting and leaves the realm and client alone. `ZAD_SSO_ISSUER`
  and `ZAD_SSO_CLIENT_ID` keep working as overrides.
- `zadctl login` checks that the access token carries the `zad-api` audience the API demands,
  and refuses to store one that does not, naming the client that needs an audience mapper
  instead of leaving you with a bare 401 on the next command.
- The output format is a setting too: **flag > `ZAD_OUTPUT_FORMAT` > `zadctl config set output`
  > table**. A format the formatter cannot render is refused when it is written, not on the
  run that reads it back.
- `--json` and `--yaml` as shorthand for `--output json` / `--output yaml`. Combining the two,
  or contradicting an explicit `--output`, is refused rather than silently resolved.
- `zadctl component add --rewrite` and `zadctl component update --rewrite`: the path the ingress
  rewrites `--path` to before the request reaches the container. `--path /api --rewrite /`
  is what an off-the-shelf image that listens on the root needs. Without it a non-root path
  is matched but not rewritten, so that image answers 404 on `/api` while the deployment is
  Healthy — which is now said in the help rather than found out. Nothing is sent when the
  flag is absent: the API has no default, so components that never asked for a rewrite keep
  passing their path on unchanged.
- `zadctl component delete --force` deletes a component that something still uses, removing
  those references in the same change. Without it the API refuses with a conflict that
  names what uses the component, which is the list you want to read before forcing.

### Changed
- `zadctl project create` takes a **display name** instead of a technical name, following the
  API: `zadctl project create "Mijn Project" --description "..."`. The platform derives the
  technical name and returns it as `project_name`, and that derived name is what the API key
  is stored under and what becomes the active project — storing it under the name that was
  typed would file it under a project that does not exist. `--display-name` still works and
  means the same thing, so a script can spell out what the value is; giving both a positional
  and a `--display-name` that disagree is refused rather than silently resolved.
- `zadctl config set` refuses keys the CLI does not read, naming the ones it does, so a typo
  no longer disappears silently into the config file.
- The login defaults now point at production (`https://keycloak.rijksapp.nl`, realm
  `rig-platform`, client `zad-cli`) instead of the sandbox, and the Keycloak host is no
  longer derived from the API host — that guess was wrong for production.
- Falling back to the bundled service catalog says so loudly, names the API that did not
  answer and how to point elsewhere. The snapshot is close enough to the real catalog that
  the difference does not show in the output, so a quiet line above a full-screen table read
  as a correct answer.
- `zadctl service` help says the catalog is per-environment and points at `zadctl service list`,
  instead of leaving the service names undiscoverable from `--help`.
- `zadctl version` shows `pod` and `image`: which instance answered, and what the cluster
  actually started. During a rollout two pods serve one address, so two calls can report
  two commits — that looked like a failed build twice, and both times it was a rollout in
  progress. Compare the pod name first, the commit second.

### Removed (breaking)
- `zadctl project list --show-keys`, and every trace of an API key in that command's answer.
  Not masked, not a "yes/no" column: the rows carry name, role and description only, in
  every output format, so `-o json` is not a way around it. One command that can put every
  key you hold into a screen or a transcript is one command too many, and the caller is as
  often a script or an agent as a person. `zadctl project use <name>` stores the key where the
  CLI needs it.

### Added
- `zadctl deployment url <deployment> [-c <component>]` prints the address and nothing else,
  so `URL=$(zadctl deployment url productie -c web)` works. Downstream tooling was digging it
  out of a deploy's raw task result with `jq -r '.urls."$D".urls."$C"'`: a nesting this CLI
  never promised, so nothing here would have failed if it changed, and one that until
  13 August could carry an address for a component with no ingress at all. A component
  without one is an error naming the components that do have one.
- **Standalone binaries.** Every release now carries one per platform (Linux x86-64, macOS
  arm64 and x86-64, Windows x86-64), built with Nuitka, so the CLI can be used without
  installing Python. One file, ~19 MB, ~0.25s to start. The README says how to install
  into `~/.local/bin` without `sudo`, and how to clear the macOS quarantine flag and the
  Windows "downloaded from the internet" mark so neither Gatekeeper nor SmartScreen
  interrupts.
- The plural reaches the same place: `zad deployments list` is `zadctl deployment list`. The
  nouns stay singular because the noun names the kind rather than the count, but everybody
  types the plural when listing. Derived by stripping the ending, so a new command group
  gets its plural without anyone maintaining a table.
- A 404 on a name says which names do exist, so finding a spelling is not a second command.
- `zadctl project describe` lists the URLs, per deployment and per component. The API computes
  them and hands them over on every deployment; leaving them out sent the reader to a second
  command for the question they most often have there: where is it, then?
- `zadctl` is the command; `zad` stays as a second name for it, because that is what every
  existing script, playbook and pinned pipeline types.

### Changed
- The CLI stops asking permission to do its job. It asks before it removes something or
  overwrites it with older data - delete, remove, clear, unset, purge, restore - and acts
  on everything else. Adding a component, setting config, creating a deployment or a backup
  used to prompt as well, which is thirty-odd questions that train you to answer "y"
  without reading, and that habit is worth more than the prompts it defeats. `--yes`,
  `ZAD_YES=true` and `zadctl config set yes true` still silence the rest, so a script or an
  agent meets no prompt at all.
- Masking gives away nothing at all. `(set)` replaces the form that kept the first four and
  last two characters of a secret, in `zadctl config list`, in `--dry-run` payloads and in the
  answer to `zadctl project create`. Being able to tell two keys apart is worth less than never
  leaking one.
- Tables are drawn in ASCII by default (`+---+` and `|`), and it is a setting:
  `zadctl config set table_style ascii|lines|plain`, or `ZAD_TABLE_STYLE`. Taste is not
  something to hard-code, and ASCII survives every terminal, font and paste into a ticket.
- A single record is laid out downwards instead of across, and a nested value is rendered as
  YAML rather than a Python repr. `zadctl project refresh` used to answer with its URLs cut up
  over five columns two words wide; they are now readable in full.
- `zadctl restore database` and `zadctl restore bucket` no longer require a target. The API made
  those fields optional on 13 August and reads their absence as "the project's own database
  or bucket", which is what most restores are. Giving *half* a target is refused here: the
  API would read two of four as "no target" and restore into the project while the caller
  believed they were writing somewhere else.
- A failure that names its own `error_category` is attributed by that, not by the status
  code. A restore into an unreachable target is a 500 by transport and a wrong value by
  cause, and exit code 2 told CI to retry a hostname that will not start resolving. An
  explicit `"Unknown"` in that field now means exit 3 (unattributable) rather than 2: the
  API had a place to attribute it and said it did not know, so retrying is not the answer.
- `ErrorCategory` gained `InvalidTarget`, mapped to your input (exit 1).
- Failed steps say what they acted on, from the new `subject` field: two lines reading
  "Diensten bijwerken" are two steps you cannot tell apart, and with the subject they are
  two components by name.

### Fixed
- Every command that waits for a task now says what came back. `component add`, `component
  assign`, `component delete`, `deployment delete` and `admin delete` polled a task and
  then reported only their own success line, so the platform's hand-over message ("a newer
  task covering this change took over the rollout") appeared after `env add` and not after
  `component assign` — a practice run recorded the same event twice, once as normal and
  once as a failure, and had no way to tell which reading was right. The same omission hid
  component failures and warnings on those five commands, which is what `--strict` exists
  to catch. `tests/test_uniformity.py` now reads the client for the methods that poll and
  fails on the next command that leaves the answer unread.
- `zadctl guide` says what the settings file is when it is not `.env.zadctl`. It stated
  "There is one file, and it is that `.env.zadctl`" while the CLI, by design, keeps using
  an existing `.env` that already carries `ZAD_` variables — and says so after every write.
  Three sources, two answers: the guide now describes the fallback and points at `zadctl
  config path` for which file this directory actually uses.
- **A value with square brackets in it arrives whole.** Rich reads `[...]` as a style tag,
  and table cells were never escaped, so any API value carrying brackets was quietly
  altered on its way to the screen. A config `pattern` showed it worst:
  `^[a-z0-9]([-a-z0-9]*[a-z0-9])?$` arrived as `^([-a-z0-9]*)?$` — a regex that is wrong in
  a way the reader cannot see, which is the worst kind. Cells are escaped now. The
  exception is the handful this CLI colours itself (`issues_cell`, so a degraded deployment
  is never silently green); those say so by their type, `Markup`, instead of being
  indistinguishable from data that isn't.
- Table output stopped cutting values off. A value wider than its column was ellipsized —
  `https://zad.sandbox.rijks…` in `config list`, a realm name in `project describe` — which
  was Rich's default rather than anyone's decision: this module set the box, the columns
  and the widths, and never the overflow. It hurts identifiers most, because a URL or a
  realm is one unbreakable word that wrapping cannot shorten, and an ellipsis is a value
  you cannot copy, cannot compare, and cannot tell from a shorter one that really ends
  there. Long values now fold onto another line and arrive whole. It is the rule this
  module already applied to entire columns, which it names when it leaves one out: saying
  less is honest, saying half without a word is not. Tables with long values get taller;
  `-o json` is still the answer when a row has to stay on one line.
- The "column(s) did not fit" hint names `COLUMNS=200` before "widen the terminal". Neither
  CI nor an agent has a terminal to widen, and both get 80 columns by default, so the one
  fix that worked there was the one the message did not mention.
- `zadctl guide` documents that `status: superseded` is a success that exits 0, and that
  `--strict` does not fail on it: it is a hand-over between rollouts, not a warning.
- `zadctl attachment list` shows the couplings that exist. It found none, because it hunted
  for dictionaries carrying a "reference" key and looked one level into a list before
  giving up, while every real coupling sits at `configurations[].config[]` under a
  component. It then fell back to printing the whole document: pages of AGE-encrypted
  content in place of the one line the reader asked for. It now reads the document's own
  structure, where `config` is a dict on the project layer and a list on a component
  layer -- assuming one of those shapes crashed the command outright with
  `AttributeError: 'list' object has no attribute 'get'` on any project that had ever
  used an attachment. The tests that covered this invented a document shape the API never
  returns and passed for months against nothing.
- One idea, one spelling. `--component` now takes `-c` everywhere it appears, including
  `deployment create` and `deployment update-image`; `attachment assign` and
  `attachment list` accept the component as an argument *and* as that option, the way the
  rest of the CLI does. `task cancel` gained the `--dry-run` every other mutating command
  has. `tests/test_uniformity.py` walks the command tree and fails on the next exception,
  because the cost of a CLI is not learning it once but checking it every time: if
  nineteen commands take `-c` and the twentieth does not, you go back to reading all
  twenty.
- The walkthrough in `zadctl guide` puts the services before the components that use them.
  `component add --service keycloak` is refused until keycloak is configured at project
  level, and the guide showed the order that fails. Two agents lost a run to it.
- A usage error exits 1, not Click's 2. This CLI publishes what its exit codes mean, and
  2 says "platform, worth retrying": a mistyped flag looked retryable to the one reader
  that cannot tell from the message.
- `zadctl guide` no longer claims every mutating command asks for confirmation. It stopped
  being true the moment that changed, and a guide that is wrong is worse than one that is
  silent.
- `zadctl attachment list <component>` works. `add` and `assign` take the component
  positionally, so refusing it here was a difference with no reason behind it.
- `zadctl attachment list` with nothing coupled yet names the files and their sizes instead
  of printing every one's AGE-encrypted contents down the terminal.
- `--set field=none` sends the word `none`, not null. YAML does not read `none` as null
  either, so this was our own invention, and an expensive one: "none" is an ordinary enum
  value ("no scheme", "no probe"), and turning it into null does not send "none" but
  nothing at all, which the API reads as "use the default" - the opposite of what was
  typed. `null` and `~` still mean null, because those say so.
- Short options work in the standalone binary. `zadctl env add -c web` died with "the program
  tried to call itself with '-c' argument": a compiled binary reads short flags that Python
  itself uses before the CLI sees them. The build disables that guard now, and the smoke
  test uses `-c`, so it cannot ship broken again for the reason it did the first time.
- Two builds carrying the same version no longer collide. The unpacked runtime was cached
  under company/product/version, so a second build of the same version found the first
  one's payload there and was killed on start: no message, exit 137. Every release
  candidate reports the same version once its suffix is stripped, so trying rc2 after rc1
  would have handed someone a binary that dies instantly. The commit is in the cache path
  now. CI cannot find this class of fault, because every runner starts with an empty cache;
  it is made impossible rather than tested for.
- `zadctl restore database` and `zadctl restore bucket` address the right cluster and namespace.
  The cluster was guessed from the namespace's first dash-separated part (`c1-ij8` became
  `c1`, a 400) and the namespace came from the v2 deployment, which reports `<project>`
  where the real one is `rig-<project>` (a 403). Both now come from the backup-runs
  endpoint, the only one that publishes them in the form the restore endpoints accept.
- Failures no longer drop the part of the answer that says why. A 409 nests its reason in
  `detail.detail` and lists what blocks the action in `used_by`; a failed `clone check`
  puts it in `validation.checks`. Both were read past, leaving a generic headline on screen
  while the sentence explaining it sat unread in the same response. A conflict that names
  references also stops advising you to wait for it to settle, which it never will.
- `zadctl project delete` removes the deleted project's name and key from the `.env`. Leaving
  them turned every later command into an authentication error about a project that was
  simply gone. The sign-in is kept.
- `zadctl component delete` printed its success line twice.
- The poll URL no longer doubles the API's path prefix. The API hands out
  `poll_url: /api/tasks/<id>` and the base URL ends in `/api` in every real deployment, so
  joining the two produced `/api/api/tasks/<id>` and a 404. Nothing hit it until
  `zadctl project create` started waiting on the server's own value: every other async
  operation builds `/tasks/<id>` itself.
- `zadctl restore project`, `zadctl restore database` and `zadctl restore bucket` send the request
  body their endpoints require. All three returned 422 on every call, because they sent no
  body at all while the vendored spec declared one as required. They now take the target
  they write to: `--deployment/--component/--storage` for a storage volume,
  `--target-host/--target-dbname/--target-username/--target-password` for a database, and
  `--target-endpoint/--target-bucket/--target-access-key/--target-secret-key` for a bucket.
  The passwords can come from the environment instead. Nothing is derived from the
  deployment: a restore that picks its own destination is one you find out about afterwards.
  `ZadClient.restore_project|restore_database|restore_bucket` gained a required `payload`
  argument, which breaks callers of a method that has never worked.
- `--dry-run` no longer prints secrets in the clear. `zadctl clone database --dry-run` showed
  the source password; masking now happens in `render_dry_run` itself, so no command can
  forget it. The `values` document of `zadctl env` and `zadctl alias` is left alone on purpose:
  there the value is the point of the command, and `KEY=@file` has to stay checkable.
- `zadctl project create` waits until the project exists before returning. The API key in the
  202 answers 401 for the first few seconds, so the next command in a script failed for a
  reason that had nothing to do with that command. The wait polls with the bearer token
  that created the project. The key is stored before the wait, so a setup that fails is not
  also a key you no longer have. `--no-wait` returns immediately as before.
- `scripts/check_coverage.py` asks a third question: does every call carry the body its
  endpoint requires? The other two checks compare paths, and by that measure a call with no
  body looks like full coverage. It runs in `pytest` now, against the vendored spec, rather
  than only in the api-sync workflow against a freshly fetched one: a call that has been
  broken since December looks identical in every diff, because it never changed.
- A hand-written `config.toml` with a real TOML boolean is read correctly. `rollout = true`
  crashed every command, and `rollout = false` was silently ignored (falling through to the
  default and rolling out anyway) — which is exactly the class of mistake the closed key set
  in this release is meant to prevent.
- `ZAD_OUTPUT_FORMAT` is now actually read: the `-o` flag no longer shadows it with its
  own default.

## v0.10.0

> Was numbered 1.0.0 while it was being written, and rolled back to 0.10.0 before release.
> 1.0 is a compatibility promise, and three breaking changes landed in the four days around
> 12 August alone: `service add`/`service delete`, the `restore_*` signatures, and
> `project list --show-keys`. Every one was the same discovery, that a command had never
> worked. That is a 0.x, and the API underneath is still moving too.

The Operations Manager became a registry, and the CLI follows it. The goal of this release
is that the CLI can do everything the web UI can, and that a script or an agent can find
out what ZAD offers without any built-in knowledge.

### Removed (breaking)
- `zadctl service add` and `zadctl service delete` — the endpoints behind them were deprecated
  and withdrawn upstream. Configure a service per layer instead: `zadctl service config set`
  and `zadctl service config clear`.
- `src/zad_cli/services.py`, which hardcoded 11 service names and was already out of date.
  Service names now come from `GET /api/v2/services`.

### Added
- `zadctl service list|describe` — the platform's own catalog, including the Dutch explanation
  and each service's variables. No API key needed.
- `zadctl service config get|set|clear|schema` — one command per verb for every service, at
  every layer, driven by the registry rather than a table of ~50 endpoints.
- `--set dotted.path=value`, `-f/--file` manifests (YAML or JSON, `-` for stdin), `@file`
  values, `--generate-skeleton`, and a local schema check that names the field path.
- `--rollout` / `--no-rollout` and `zadctl project pending`: saving and rolling out are two
  things. After a `--no-rollout` change the CLI says what is waiting and how to roll it out.
- `zadctl attachment list|add|assign|update|delete` — the project's file catalog and the
  per-component coupling, kept apart. `--mount-path` belongs to the coupling.
- `zadctl env` and `zadctl alias` — a component's own variables and the aliases for platform
  variables, with `add`/`set`/`unset`/`clear` mapping to the API's four distinct endpoints.
- `zadctl login` / `zadctl logout`, `zadctl project list|create|use` — SSO sign-in and a credentials
  store at `~/.config/zad/credentials.toml` (mode 0600, OS keyring when available).
  Returned API keys are stored, masked in output and never logged.
- `zadctl db schema list|add|remove`, `zadctl admin cleanup|reconcile`, `zadctl registry add`.
- `zadctl version` now reports the server's version alongside the CLI's, instead of being a
  deprecated alias.
- `--refresh-catalog`, and a bundled catalog snapshot so the CLI still works offline.

### Changed
- The compatibility policy is now "additive within a major" rather than additive forever.
  A removal must edit the baseline in `tests/test_backwards_compat.py` and be listed with
  what replaced it.
- `zadctl project list` authenticates with an SSO token instead of an API key; the v1 endpoint
  it used no longer exists.
- `api/upstream-openapi.json` refreshed. `scripts/check_coverage.py` understands the
  registry-driven commands and reports the endpoints left out, each with a reason.

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
