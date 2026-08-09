# TODO / Ontwerpnotities

Vastgelegd 2026-07-31. Uitkomst van een ontwerpsessie over CLI-ergonomie, SSO-projectcreatie
en file-attachments, plus bevindingen over de api-sync pijplijn.

Status per item: **[nu]** = kan direct, geen afhankelijkheden · **[upstream]** = wacht op
RIG-Cluster (Operations Manager API) · **[keuze]** = vraagt eerst een beslissing.

---

## 0. Api-sync pijplijn — openstaande punten

De sync werkt (cron ma-vr 07:00 UTC, `.github/workflows/api-sync.yml`), maar de output blijft liggen.

- [ ] **[nu]** PR #34 reviewen en mergen (`zad component update` via PATCH, `--ports` op
      `component add`). PR #32 en #33 sluiten als achterhaald — #34 bevat hun inhoud.
      Alle checks groen, geblokkeerd op `REVIEW_REQUIRED`. Laatste gemergede sync: #29, 19 juni.
- [ ] **[nu]** Bug: commit-prefix klopt niet. `Determine commit type`
      (`api-sync.yml:349-360`) doet `git diff origin/main...HEAD`, maar `actions/checkout`
      cloont shallow → `origin/main` bestaat niet → altijd `chore`. Gevolg: syncs die echt
      code toevoegen triggeren geen release. Bewijs: `b81418d` (#26) voegde `commands/admin.py`
      +62 regels toe en heet `chore`; `f49223d` (#18) raakte geen enkele `src/`-regel en heet `feat`.
      Fix: `fetch-depth: 0` of expliciet `git fetch origin main` vóór de diff.
- [ ] **[nu]** De `implement`-job draait alléén als de spec-file wijzigt. Structurele
      dekkingsgaten worden daardoor nooit ingehaald, ook al staan ze in het coverage-rapport
      dat aan de agent wordt doorgegeven. Voorstel: ook triggeren op coverage-drift.
- [ ] **[nu]** Omgekeerde dekkingscheck toevoegen. De client roept 13 paden aan die **niet in
      de spec staan**: de hele `zad metrics`-groep (7), `GET /projects` (= `zad project list`!),
      `POST /v1/backup/namespace|database|bucket`, `DELETE /v2/.../components/{p}` en
      `.../services/{p}`. `oasdiff` kan verdwijnen daarvan nooit signaleren — wat niet in de
      spec staat, kan ook niet als "deleted" gediffd worden. Uitzoeken: incomplete spec of
      ongedocumenteerde endpoints?
- [ ] **[upstream]** Resterende dekkingsgaten (10 van 48 tegen de nieuwste spec):
      `GET /api/federation/health`, `GET /api/federation/peers`,
      `POST /api/v2/admin/cleanup/trigger`, `POST /api/v2/admin/reconciliation/trigger`,
      `POST /api/tasks`, `POST /api/v1/projects/{p}/images/push`,
      `POST .../registries/by-credentials`, `.../registries/by-secret` (v1-deprecated maar
      zonder v2-equivalent), `GET /version`.

Ter info: **zad-actions heeft geen eigen API-koppeling meer.** Sinds v4.0.0 (7 april) is de
curl/jq/polling-laag daar geschrapt; die repo pint zad-cli op één regel
(`scripts/zad-common.sh:8` → `ZAD_CLI_VERSION`) en gebruikt maar twee commando's
(`deployment create`, `deployment delete`). Die pin wordt **handmatig** gebumpt — Dependabot
volgt daar alleen `github-actions`. Alle API-kennis hoort dus in zad-cli thuis.

---

## 1. CLI-leesbaarheid: van 15 flags naar een manifest

**Probleem.** `component add` heeft 15 flags. De escape hatch is erger:
`zad deployment create staging --components '[{"name":"web","image":"…"}]'` — JSON in een
shell-string: geen validatie, geen editor-support, quoting-hel. In
`zad-actions/deploy/action.yml:261-265` wordt die array in bash aan elkaar geplakt.
Op één regel is niet te zien wat bij elkaar hoort.

**Referentiepatronen** (de goede CLI's combineren ze):

| Patroon | Wie | Vorm |
|---|---|---|
| Declaratief manifest | kubectl, compose, terraform | `kubectl apply -f x.yaml`, ook `-f -` |
| Skeleton genereren | AWS CLI | `--generate-cli-skeleton` → invullen → `--cli-input-json file://x.json` |
| Waarde uit bestand | gh, az | `gh api -F body=@body.md`, `--body-file`, `@file` |
| Laag + overrides | Helm | `-f values.yaml --set image.tag=v2` |
| Compacte shorthand | docker, aws | `--mount type=bind,source=/x,target=/y` |

Rode draad bij kubectl: een bewust **dubbele interface** — imperatief blijft expres simpel,
alles met structuur gaat via een file.

### Werkitems, oplopend in investering

- [ ] **[nu] (a) Flag-groepen in `--help`.** Typer/Click `rich_help_panel="…"`. Groepen:
      Netwerk (`--port/--ports/--path/--root`), Resources (`--cpu-limit/--memory-limit`),
      Services, Domein (`--domain-format/--subdomain/--base-domain`). Lost "wat hoort bij
      elkaar?" op zonder één regel syntax te wijzigen. Kleinste ingreep met de meeste winst.
- [ ] **[nu] (b) `-f/--file` op de muterende commando's.** YAML (JSON is een subset, dus
      gratis), `-` voor stdin, flags overriden de file (Helm-model).

      ```yaml
      # component.yaml
      name: api
      image: ghcr.io/org/api:v2
      deployments: [prod, staging]
      network:
        port: 8080
        path: /api
      resources:
        cpu: 500m
        memory: 512Mi
      services: [postgresql-database, minio-bucket]
      env:
        DB_HOST: db
      ```
      ```bash
      zad component add -f component.yaml --image ghcr.io/org/api:$SHA
      ```
- [ ] **[nu] (c) Schema genereren uit de Pydantic-modellen** (`api/models.py`). Levert
      `--generate-skeleton` én een publiceerbaar JSON Schema. Met een
      `# yaml-language-server: $schema=…` regel bovenin de manifest krijg je autocomplete en
      inline docs in VS Code/IntelliJ. Sluit aan bij de spec-driven, los-gekoppelde aanpak:
      schema en CLI kunnen niet uit elkaar lopen.
- [ ] **[nu] (d) `--set pad.naar.veld=waarde`** voor chirurgische CI-overrides zonder
      templating-stap.
- [ ] **[nu] (e) Generieke `@file` / `file://` waarde-loader** op elke optie.
      `--env-file` in `component add` is daar al een eenmalige variant van. Fundament voor §3.
- [ ] **[keuze] (f) `zad apply -f zad.yaml`** voor een heel project. De API is al
      upsert-gebaseerd (`:upsert-deployment`, PATCH op components in #34), dus het mapt netjes.
      Verdient een eigen ontwerp inclusief `zad diff`/plan-stap. **Niet in de eerste ronde.**

### Openstaande beslissing

- [ ] **[keuze]** Additief of opruimen? (b) kan puur additief (`--components` blijft), óf het
      wordt de aanleiding voor een **1.0 met opruiming**: `--components` JSON-string eruit,
      flagnamen consistent. Dat botst met de additive-only policy in `CLAUDE.md` — dus expliciet
      beslissen, inclusief wat het betekent voor de `ZAD_CLI_VERSION`-pin in zad-actions.

---

## 2. `zad project create` via SSO — het idee

**Kernpunt: dit kan, en het is minder werk dan het lijkt.** De browser-helft bestaat al —
`commands/open_cmd.py:36-46` (`zad open portal`) opent al `{web_url}/projects/new`. Wat
ontbreekt is puur de *terugweg*.

**Nu nog niet mogelijk:** er is geen `POST /api/projects` en geen enkele auth-route, ook niet in
de nieuwste spec (58 paths, PR #34). Volledig upstream werk. Dit is een richting, geen sprintitem.

### Beoogde UX

```
$ zad project create mijn-app
→ Opening browser for sign-in… (code: 7F2A)
   If nothing opens: https://…/projects/new?cli=7F2A

   [ browser: SSO-login → projectformulier → aanmaken ]

✓ Project 'mijn-app' created
✓ API key stored in ~/.config/zad/credentials.toml
✓ Active project set to 'mijn-app'

$ zad deployment list          # werkt meteen, gewoon via X-API-Key
```

Onder water: de CLI luistert op `http://127.0.0.1:<vrije poort>`, geeft dat adres plus een
eenmalige nonce mee aan het portaal, het portaal post na aanmaken projectnaam + API-key terug
naar die loopback, de CLI schrijft weg en sluit af. Patroon van `gcloud auth login`,
`aws sso login`, `gh auth login --web` (Authorization Code + PKCE met loopback, RFC 8252).

### Waarom dit conceptueel klopt: twee soorten credentials

| | SSO-identiteit | Project-API-key |
|---|---|---|
| Wie | een mens | een machine / CI |
| Levensduur | kort, sessie | lang |
| Waarvoor | *alleen* project aanmaken | alle andere calls |

De API bevestigt die tweedeling: de spec beschrijft dat de API-key wordt gevalideerd tegen een
server-side mapping van project-ID's naar keys. SSO is dus geen nieuwe autorisatielaag over de
hele CLI, maar een **eenmalige bootstrap die een key uitgeeft**. Daarmee vervalt refresh-flow,
tokenvernieuwing en scope-modellering — veel kleiner dan een volledige `zad login`.

### Belangrijk: een CLI kan de env van de parent shell niet muteren

"De env updaten naar het nieuwe project" moet dus via een van deze drie — voorstel: alle drie.

- [ ] **[nu, los van SSO bruikbaar]** Credential store `~/.config/zad/credentials.toml`
      (0600, per project) + default-context in `config.toml`, met `zad project use <naam>`.
      Het kubectl/gh-model. `ZAD_PROJECT_ID` wordt dan een override i.p.v. de enige bron.
      Nu slaat `config.py` alleen `api_url` op; key en project komen uitsluitend uit env/`.env`.
- [ ] **[nu]** `eval "$(zad project create foo --export)"` voor wie het in de shell wil.
- [ ] **[nu]** `--write-env .env` voor repo/CI — `cli.py` laadt al `.env`.

### Wat RIG-Cluster moet leveren

1. Het portaal accepteert `cli_callback` + `state` en post na succes naar de loopback.
   (Het portaal is al SSO-beveiligd — daar hoeft niets aan.)
2. Een endpoint dat bij projectcreatie een API-key uitgeeft, of de bestaande key teruggeeft
   aan de ingelogde eigenaar.
3. *Optioneel:* device-code-flow (RFC 8628) bij de IdP, alleen nodig voor headless.
   **Waarschijnlijk niet nodig:** CI maakt nooit projecten aan, die krijgt een bestaande key.
   Voor de zeldzame SSH-sessie volstaat "kan de browser niet openen, plak deze URL" + key plakken.

### Niet verprutsen

- **De key nooit in de query string** van de callback — belandt in browsergeschiedenis,
  proxy-logs en referrers. POST-body naar de loopback.
- **`state`-nonce verplicht**, listener alleen op `127.0.0.1` binden (niet `0.0.0.0`), één
  request en dan sluiten. Anders kan elke website op de machine de callback afvangen.
- **Opslag 0600**, redactie in `--verbose`, bij voorkeur OS-keyring met file-fallback.
  Gegeven de overheidscontext een reviewpunt, geen detail.

### Te verifiëren

- [ ] **Welke IdP zit achter het portaal?** Geen spoor van te vinden in zad-cli of zad-actions
      (Keycloak komt alleen voor als *aan te bieden service*, niet als platform-IdP). Is het
      Keycloak of een andere standaard OIDC-provider, dan is de device-flow later een kwestie
      van een grant aanzetten i.p.v. bouwen.
- [ ] `scripts/check_coverage.py:39-46` skipt `/auth/` en `/invite/` in `SKIP_PREFIXES`, maar
      die routes staan **niet** in de spec. Bestaan ze wél op de live server en ontbreken ze in
      de OpenAPI-output? Eerste ding om na te gaan.

### Tussenstap die vandaag al kan

- [ ] **[nu]** `zad project create --manual`: opent het portaal (bestaande `open portal`-code),
      vraagt daarna `Plak de API key:` en slaat op in de credential store. Lelijk, maar levert
      de opslag-, context- en `--export`-machinerie op die de echte flow later hergebruikt.

---

## 3. File-attachments

**Nu nog niet mogelijk:** geen attachment-endpoint in de spec (gecontroleerd 2026-08-06: 53
paths, enige multipart is `POST /api/v1/projects/{p}/images/push`). Upstream wordt de API hier
sowieso ingrijpend herzien; de endpoints komen daarbij duidelijker beschikbaar. De CLI-vorm kan
nu wel vastgelegd worden.

### Het model: opslag en binding zijn twee dingen

Bijgewerkt 2026-08-07 na navraag. Een attachment zit op meerdere niveaus tegelijk:

| Niveau | Wat |
|---|---|
| **Project** | waar het bestand altijd wordt opgeslagen — ook als het nog nergens gebruikt wordt |
| **Component** | de generieke componentdefinitie waaraan het gebonden is |
| **Deployment + component** | specifieker dan de generieke definitie; overschrijft die |

Dat is niet toevallig precies het patroon dat de CLI al heeft voor componenten:

```
zad component add    web …               → POST /v2/projects/{p}/components              (project)
zad component assign web production …    → POST /v2/projects/{p}/deployments/{d}/components  (specifiek)
```

Attachments spiegelen dat één-op-één. **Uploaden en binden zijn dus aparte commando's** — je
kunt een bestand naar het project uploaden zonder dat het al ergens gebruikt wordt, en het later
binden. `assign` is daarvoor het juiste verb; `CLAUDE.md` definieert dat al als "bind one
resource to another".

**Gevolg t.o.v. de vorige schets: `--mount-path` verhuist van `add` naar `assign`.** Het pad is
een eigenschap van de *binding*, niet van het bestand — hetzelfde attachment kan in twee
deployments op een ander pad landen. In de oude schets stond het op `add`; dat was fout.

### Voorgestelde syntax

```bash
# 1. uploaden — project-niveau, nog nergens in gebruik
zad attachment add config-yaml -f ./config/app.yaml \
  --description "Applicatieconfiguratie"

# 2. binden aan de generieke componentdefinitie
zad attachment assign config-yaml api --mount-path /etc/app/config.yaml

# 3. of specifieker: alleen in één deployment (overschrijft 2)
zad attachment assign config-yaml api --deployment prod \
  --mount-path /etc/app/config.prod.yaml

# nieuwe inhoud, bestaande bindingen blijven staan
zad attachment update config-yaml -f ./config/app.yaml

zad attachment list [--component api] [--deployment prod]
zad attachment delete config-yaml
```

Vastgelegde keuzes:

- **Top-level groep `zad attachment`**, enkelvoud, niet `zad service attachments` — drie niveaus
  en meervoud wijken beide af van het noun-verb-patroon in `CLAUDE.md`.
- **Naam als positional**, niet `--name` — positionals identificeren de primaire resource.
  Bij `assign` staat de component als tweede positional, net als `component assign <naam> <deployment>`.
- **Niet `--path`**: dat betekent in `component add` al *ingress path*. Bestemming in de
  container is `--mount-path`.
- **`add` + `update`** matcht het precedent uit PR #34 (`component add` + `component update`
  met PATCH). Update met alleen `-f` is precies partial-update-semantiek.

### Flag-conventie voor file-uploads (geldt generiek)

Besloten 2026-08-07. Twee soorten file-input mogen niet door elkaar lopen:

| Rol | Flag | Voorbeeld |
|---|---|---|
| **Manifest** — beschrijft wát het commando moet doen (§1b) | `-f` / `--file` | `zad component add -f component.yaml` |
| **Payload** — de inhoud die geüpload wordt | `--from-file`, met `-f` als alias | `zad attachment add x -f ./app.yaml` |

`--from-file` is de canonieke naam (precedent: `kubectl create secret generic --from-file=`).
Hij leest als "haal de inhoud hiervandaan" en kan niet verward worden met een eigenschap van de
attachment zelf — waar `--file` op een upload-commando wél verwarrend is.

`-f` werkt als korte alias op upload-commando's. Dat betekent bewust dat dezelfde letter per
commando iets anders aanwijst (manifest bij `component add`, payload bij `attachment add`).

> **Guard-regel die dat beheersbaar houdt:** `-f` wordt alleen geregistreerd als de *enige*
> file-input van dat commando. Krijgt een commando ooit zowel een manifest als een payload, dan
> blijft `-f` het manifest en gebruikt de payload uitsluitend `--from-file`. Nooit twee
> file-flags waarvan er één `-f` heet op hetzelfde commando.

### Werkitems

- [ ] **[nu]** `@file` / `file://` waarde-loader (= §1e). Client-side, werkt met bestaande
      endpoints, en attachments worden er straks een natuurlijke uitbreiding op.
- [ ] **[nu]** `--from-file -` (stdin) en een maximumgrootte; binair → base64 als de API JSON is.
- [ ] **[nu]** Guard-regel hierboven opnemen in de argumentregels van `CLAUDE.md`, zodat de
      api-sync-agent hem ook volgt.
- [ ] **[upstream]** Attachment-endpoints. Aan te vragen bij RIG-Cluster, in drie stukken die
      het model hierboven volgen: opslag op projectniveau, binding op component, binding op
      deployment+component. Meegeven dat het pad bij de *binding* hoort, niet bij het bestand.
- [ ] **[upstream]** Daarna `zad attachment add|update|assign|list|delete`.

---

## 4. `zad ci` — CI-bootstrap op GitHub en Forgejo — **GEPARKEERD**

> **Status: geparkeerd op 2026-08-06.** Haalbaarheid is uitgezocht en het antwoord is ja, maar
> het staat niet op de rol. Onderstaande blijft staan als vooronderzoek — de `[nu]`-markeringen
> hieronder betekenen "geen upstream-afhankelijkheid", niet "ingepland".

Vastgelegd 2026-08-06. Vraag: kan de CLI in een GitHub- of Forgejo-repo de CI-actie ophangen
én de projectsecret zetten, met de credentials van de gebruiker zelf?

**Antwoord: ja, en het is volledig client-side — geen enkel nieuw RIG-Cluster-endpoint nodig.**
Dat maakt het het enige grote item in deze lijst dat niet op upstream wacht. De auth-helft,
het punt waar de twijfel zat, hoeft niet gebouwd te worden: er is al een token.

### 4.1 Wat is geverifieerd

**Secrets zetten — beide providers hebben het, asymmetrie is klein.**

| | Forgejo/Gitea | GitHub |
|---|---|---|
| Endpoint | `PUT /api/v1/repos/{o}/{r}/actions/secrets/{name}` | `PUT /repos/{o}/{r}/actions/secrets/{name}` |
| Body | `{"data": "<plaintext>"}` | `{"encrypted_value": …, "key_id": …}` |
| Crypto client-side | geen | libsodium sealed box, key via `…/secrets/public-key` |
| Auth-header | `Authorization: token <t>` | `Authorization: Bearer <t>` |
| Ook op org-niveau | ✅ `/orgs/{org}/actions/secrets/{name}` | ✅ |
| Variables (niet-geheim) | ✅ `…/actions/variables/{name}` | ✅ |

Geverifieerd tegen de live swagger van Codeberg (Forgejo 16.0-dev) en de GitHub REST-docs.
Kosten van het GitHub-pad: één dependency (PyNaCl) en ~15 regels. Verder identiek.

**Het workflow-bestand plaatsen — hier zit de val.**

Er bestaat geen "workflow API"; je commit `.github/workflows/x.yml` via de Contents API.
Op GitHub vereist dát de aparte **`workflow` scope**. Gemeten op een dev-machine: de token van
de lokale `gh` heeft `repo, read:org, gist, project, admin:public_key, read:packages` —
**geen `workflow`**. Met precies die token kun je dus wél secrets zetten en géén workflow
pushen, tenzij de gebruiker eerst `gh auth refresh -s workflow` draait.

> **Besluit: het workflow-bestand wordt lokaal in de working tree geschreven, niet gepusht.**
> Geen extra scope, geen push-rechten, geen force-push-risico, en de gebruiker ziet het in
> `git diff` vóór het gecommit wordt. Alleen de secrets gaan over de API — die kún je niet
> lokaal zetten. Die scheiding is niet alleen veiliger, het is ook de eerlijke: een bestand
> hoort in git, een secret niet.

**Auth — niets te bouwen.** Vier lagen, in volgorde van proberen:

| | GitHub | Forgejo |
|---|---|---|
| 1. bestaande CLI-token | `gh auth token` | `~/.config/tea/config.yml` |
| 2. env var | `GITHUB_TOKEN`, `GH_TOKEN` | `FORGEJO_TOKEN`, `GITEA_TOKEN` |
| 3. PAT plakken → credential store (0600) | ✅ | ✅ scope `write:repository`, per-repo te beperken |
| 4. OAuth device flow | mogelijk, maar vereist een OAuth App onder RijksICTGilde | **bestaat niet** |

Twee bevindingen die laag 4 voor Forgejo afserveren:

- Device flow (RFC 8628) zit niet in Forgejo — open issue forgejo#4830.
- Belangrijker: **Forgejo heeft geen OAuth2-scopes.** De eigen docs zijn expliciet:
  *"OAuth2 scopes are not yet implemented … Third-party applications obtaining a token for a
  user via such an application will have administrative rights."* Een OAuth-token op Forgejo
  geeft dus volledige controle over het account van de gebruiker. In een overheidscontext is
  dat geen optie.

Forgejo-**PATs** hébben wél scopes én kunnen tot losse repo's beperkt worden. Op Forgejo is een
PAT dus niet het armoedige alternatief maar de veiligere keuze. Laag 1–3 dekken samen alle
gevallen, kosten ~100 regels, en ZAD beheert geen `client_id`, geen OAuth-app, geen redirect.

### 4.2 Scope-grens

Wel: secrets/variables zetten, de zad-workflow genereren, verifiëren, opruimen.
Niet: het bouwproces van de applicatie zélf genereren (taaldetectie, testrunners, Dockerfiles).
Dat is een generator-moeras zonder bodem. De grens ligt bij **de zad-helft van de pijplijn**:
image bouwen+pushen → deployen → PR-preview → cleanup. De build-stap is één sjabloonkeuze
(is er een Dockerfile, ja/nee), geen frameworkdetector.

### 4.3 Beoogde UX

```
$ zad ci init
Repo:    RijksICTGilde/mijn-app  (github, token via gh)   ← uit git remote
Project: mijn-app                                          ← uit -p / .env

Bouwproces?
  › Dockerfile in repo-root (gevonden)
    Dockerfile op een ander pad
    Image wordt elders gebouwd — alleen deployen

Wanneer deployen?
  [x] push naar main    → deployment 'production'
  [x] pull request      → preview 'pr-<nr>' + comment op de PR
  [x] PR gesloten       → preview opruimen

Plan:
  schrijf    .github/workflows/zad-deploy.yml       (nieuw)
  schrijf    .github/workflows/zad-cleanup.yml      (nieuw)
  secret     ZAD_API_KEY        → repo-secret       (nieuw)
  variable   ZAD_PROJECT_ID     → mijn-app          (nieuw)

Doorgaan? [y/N]
```

### 4.4 Commando's

Nieuwe noun-groep `zad ci`, conform de conventies in `CLAUDE.md`:

| Commando | |
|---|---|
| `zad ci init` | detecteren + genereren + secrets zetten — het "één loket"-commando |
| `zad ci status` | read-only: staat de secret er, staat de workflow er, welke pin |
| `zad ci check` | valideert repo-toegang + doet een `project status` mét die key |
| `zad ci secret set\|list\|delete` | losse primitives, ook zinnig zonder `init` |
| `zad ci variable set\|list\|delete` | idem |
| `zad ci login` | token detecteren of opslaan in de credential store |
| `zad ci upgrade` | bumpt de versie-pin in bestaande gegenereerde workflows |

`init` is een nieuw verb; precedent is `zad config init`. Alle muterende commando's krijgen
`--dry-run`, `--yes/-y`, `@handle_api_errors` en een `render_success`. `--dry-run` op `init`
print het volledige plan plus de workflow-inhoud naar stdout en raakt niets aan.

### 4.5 Architectuur

Nieuw pakket naast `api/` — het is een tweede, wezenlijk andere API. `ZadClient` blijft
ongemoeid, dus geen back-compat-risico:

```
src/zad_cli/forge/
  base.py       # Protocol: get_repo, set_secret, set_variable, list_secrets, delete_secret
  github.py     # + sealed box (PyNaCl)
  forgejo.py    # plain data-veld
  detect.py     # git remote → (provider, host, owner, repo)
  auth.py       # gh / tea / env / credential store, in die volgorde
  templates/    # f-strings, geen templating-dependency
```

- **Provider-detectie** uit `git remote get-url origin`. `github.com` → github; anders
  `GET {host}/api/v1/version` (Forgejo/Gitea antwoordt daarop) → forgejo. Overrides:
  `--provider`, `--repo owner/naam` voor mono-repos en mirrors.
- **PyNaCl** vast als dependency, niet als extra. Zonder werkt de helft van de use case niet,
  en een ImportError halverwege `ci init` is slechtere UX dan een paar MB wheel.

**Forgejo-valkuil.** Forgejo Actions haalt `uses:` standaard van de **eigen instance**, niet
van GitHub, tenzij de beheerder `DEFAULT_ACTIONS_URL=github` heeft gezet. Een gegenereerde
`uses: RijksICTGilde/zad-actions/deploy@v4` werkt daar dus mogelijk niet. Voor Forgejo genereren
we daarom een workflow die de CLI direct installeert:

```yaml
- run: uv tool install git+https://github.com/RijksICTGilde/zad-cli.git@v0.6.0
- run: zad deployment create pr-${{ … }} --component web --image ghcr.io/org/app:${{ … }}
```

Dat pleit ervoor die vorm óók op GitHub aan te bieden (`--flavor cli|action`): één sjabloon,
geen instance-afhankelijkheid, en zad-actions v4 is zelf al niets anders dan een wrapper om
zad-cli (zie §0). Voorstel: `cli` als default, `action` als opt-in voor wie de PR-comment- en
cleanup-extra's van zad-actions wil.

### 4.6 Aanpalend gat dat hier vanzelf bij hoort

De spec heeft `POST /api/projects/{p}/registries/by-credentials` (AGE-encrypted) en
`…/by-secret`; beide zitten **niet** in de CLI (staan als dekkingsgat in §0). Voor "de hele
build werkt" hoort dat erbij: de CI pusht naar ghcr.io, en ZAD moet die private registry kunnen
pullen. `zad ci init` kan dat in dezelfde flow aanbieden, met `zad registry add` als los
commando eronder.

### 4.7 Werkitems

- [ ] **[nu]** `forge/` met `detect.py` + `auth.py` + secret/variable-CRUD voor beide providers,
      en `zad ci secret|variable set|list|delete`. Op zichzelf al bruikbaar. (~1-2 dagen)
- [ ] **[nu]** Sjablonen + `zad ci init` + `--dry-run` + `ci status` + `ci check`. (~2 dagen)
- [ ] **[nu]** `zad registry add` (§4.6). (~halve dag)
- [ ] **[nu]** `zad ci upgrade` — de versie-pin in gegenereerde workflows bijwerken. Sluit aan
      op de handmatige `ZAD_CLI_VERSION`-bump die nu in zad-actions blijft liggen (§0).
- [ ] **[keuze]** Device flow voor GitHub. Vereist een geregistreerde OAuth App onder
      RijksICTGilde — een organisatiebesluit, geen codeprobleem. Alleen zinvol als laag 1-3
      in de praktijk tekortschieten. Voor Forgejo: niet doen (§4.1).
- [ ] **[verifiëren]** Draait RIG een eigen Forgejo-instance? Geen spoor van in zad-cli of
      zad-actions. Bepaalt of `forgejo.py` dag 1 of veel later is.

### 4.8 Risico's

- **Token-opslag** vraagt om precies de credential store uit §2 (0600, keyring met
  file-fallback, redactie in `--verbose`). Bouw die één keer, gebruik hem voor beide. In de
  overheidscontext een expliciet reviewpunt, geen detail.
- **Scope-creep** richting build-generator. Grens uit §4.2 hard houden.
- **Idempotentie**: `ci init` op een repo die het al heeft toont een diff en overschrijft niet
  blind. Ook secrets: melden dat je een bestaande waarde vervangt.
- **`ci init` schrijft in de working tree.** Alleen bij een schone tree, of expliciet `--force`.

---

## 5. Volgordevoorstel

1. §0 quick wins (PR #34 mergen, commit-type-bug) — klein, blokkeert niets.
2. §1a + §1b + §1c — lost de acute leesbaarheidspijn op, hangt nergens van af.
3. Beslissing §1f (additief vs. 1.0-opruiming) vóór er veel op `-f/--file` gebouwd wordt.
4. RFC richting RIG-Cluster voor de auth- en attachment-endpoints — parallel starten, want
   daar zit de doorlooptijd.
5. §2 credential store + `project use` — nuttig op zichzelf, en het fundament onder §4.

§4 staat buiten deze volgorde: geparkeerd.
