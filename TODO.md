# zad-cli 1.0: alles wat de UI kan, vanaf de opdrachtregel

Dit bestand is het contract voor deze taak. Het is bewust volledig: alles wat nodig is om
te bouwen staat erin, zodat er niets opnieuw uitgezocht of uitgelegd hoeft te worden.
Werk het van boven naar beneden af en vink af.

Vastgesteld 2026-08-09, op basis van onderzoek tegen de draaiende sandbox.

---

## 0. Waar dit over gaat

De Operations Manager API is herbouwd. De nieuwe spec staat op
<https://zad.sandbox.rijksapp.dev/openapi.json> (98 paths, **125 operaties**, 168 schemas) en
draait op de sandbox vanaf de branch `branches-samenvoegen-naar-main`. De CLI dekt daarvan nu
**39 operaties; 86 niet**. Belangrijker dan het aantal is dat het *model* veranderd is:

1. **De API is een registry geworden.** `GET /api/v2/services` vertelt welke diensten er zijn en
   wat je aan elk kunt instellen; `GET /api/v2/services/{naam}` beschrijft er één volledig.
   Beide zijn publiek — geen project, geen API-key.
2. **Configuratie zit per dienst op lagen**: `project`, `component`, `deployment`. Welke lagen
   een dienst accepteert staat in de registry, niet in de CLI.
3. **Opslaan en uitrollen zijn twee dingen.** `rollout` is een parameter op 62 van de 100
   muterende operaties, met `GET /api/v2/projects/{p}/pending-rollout` ernaast.
4. **De oude vorm is deprecated.** `POST /api/v2/projects/{p}/services` — waar `zad service add`
   op draait — is als deprecated gemarkeerd, net als de hele `/api/projects/...`-reeks (17 ops).

Doel van 1.0: **de CLI kan alles wat de UI kan**, en een agent kan via de CLI zelfstandig
uitvinden wat ZAD te bieden heeft zonder ingebakken kennis.

### Besloten (niet heropenen)

| Beslissing | Uitkomst |
|---|---|
| Versiebeleid | **1.0 met opruiming.** Breken mag. `tests/test_backwards_compat.py` krijgt een nieuwe baseline; de additief-only policy in `CLAUDE.md` wordt herschreven naar "additief binnen een major". |
| Bron van waarheid | **De registry, niet de CLI.** Geen hardcoded dienstenlijsten. |
| Upload-flags | `-f`/`--file` = manifest. `--from-file` = payload, met `-f` als alias mits het de enige file-input van dat commando is. |
| Doeltaal hulpteksten | Nederlands voor `explanation`-doorgifte; de bestaande Engelse help-conventie blijft voor commando-hulp. |

### Gevolg buiten deze repo

`zad-actions` pint zad-cli op één regel (`scripts/zad-common.sh` → `ZAD_CLI_VERSION`) en gebruikt
`deployment create` en `deployment delete`. **Die twee commando's moeten in 1.0 blijven werken,
of de pin-bump moet gelijktijdig.** Controleer dit expliciet voordat je `deployment` aanraakt.

---

## 1. Vastgestelde feiten (niet opnieuw uitzoeken)

### 1.1 De dienstencatalogus

`GET /api/v2/services` → 21 diensten. Per dienst: `name`, `description`, `configurable`,
`targets`, `config_schema_version`, `value_targets`, `kind`, `binding`, `hidden`, `requires`.

```
aliases                        system  binding=component   targets=[]                      value_targets=[component]
attachments                    user    binding=component   targets=[component]
authorization-wall             user    binding=component   targets=[project]
cross-domain-access            user    binding=deployment  targets=[project, deployment]
deployment-health              system  binding=deployment  targets=[]
health-check                   user    binding=component   targets=[component]
invite                         user    binding=project     targets=[project]
keycloak                       user    binding=component   targets=[project]
metrics-scraper                user    binding=component   targets=[component]
minio-storage                  user    binding=deployment  targets=[project, deployment]
namespace-postgresql-database  user    binding=deployment  targets=[project]           hidden
namespace-redis                user    binding=deployment  targets=[]                  hidden
persistent-storage             user    binding=component   targets=[component]
platform                       system  binding=component   targets=[]
postgresql-database            user    binding=deployment  targets=[project]
publish-on-web                 user    binding=component   targets=[component]
redis                          user    binding=deployment  targets=[project]
resource-tuning                system  binding=deployment  targets=[]
sleep-mode                     user    binding=deployment  targets=[project]
temp-storage                   user    binding=component   targets=[component]
user-env-vars                  system  binding=component   targets=[]                  value_targets=[component, deployment-component]
```

`src/zad_cli/services.py` hardcodeert 11 namen en is dus al fout. Dat bestand verdwijnt.

`GET /api/v2/services/{naam}` geeft daarbovenop: `explanation` (volledige markdown in het
Nederlands), `layers[]` met per laag `target`, `yaml_path`, `roles`, **`config_endpoint`**
(letterlijk de aan te roepen method+path) en `has_form`, plus `variables[]` met `name`,
`description`, `source`, `aliases`, `secret_key`, en `requires` / `cleanup_strategy` /
`backup_label`.

> Dat `config_endpoint` per laag is het scharnierpunt van dit hele plan: de CLI hoeft de ~50
> config-endpoints niet te kennen, hij leest ze uit de registry.

Elke config-body heeft een echte JSON Schema in de spec (bv. `PostgresqlDatabaseProjectConfig`,
een `scope`-gediscrimineerde union van `SharedScopeConfig` / `ProjectScopeConfig`).

### 1.2 Wat er ongedekt is, per groep

| Groep | Ongedekt | Opmerking |
|---|---|---|
| service-config (alle diensten samen) | ~50 | `PUT`/`DELETE .../config/{project\|component/{c}\|deployment/{d}}` |
| user-env-vars | 10 | values op component én deployment-component |
| attachments | 7 | catalogus + koppeling aan component |
| aliases | 5 | values op component |
| postgresql-database schemas | 3 | list/add/remove extra schema's |
| projects | 3 | `GET`/`POST /api/v2/projects`, `GET .../pending-rollout` |
| services (introspectie) | 3 | `/api/v2/services`, `/{naam}`, `/{p}/services/{naam}/config` |
| admin | 3 | cleanup-trigger, reconciliation-trigger, `:reconcile` |
| overig | ~2 | `GET /version`, `POST /api/v1/projects/{p}/images/push` |

### 1.3 Authenticatie

De spec kent één securityScheme: `APIKeyHeader` (`X-API-Key`). **Maar** `GET /api/v2/projects`
en `POST /api/v2/projects` accepteren volgens hun beschrijving een **SSO bearer token**
(`Authorization: Bearer <token>`) — en dat kan niet anders, want je hebt de projectnaam nodig
vóór je zijn key kunt hebben.

Geverifieerd op de sandbox:

- IdP = **Keycloak**: `https://keycloak.sandbox.rijksapp.dev/realms/operations-manager`,
  client_id `rig-platform-operations-manager`.
- De realm adverteert `urn:ietf:params:oauth:grant-type:device_code` en
  `device_authorization_endpoint`, plus PKCE `S256`.
- `POST /api/v2/projects` geeft de nieuwe API-key **één keer** terug in de respons.
- `GET /api/v2/projects` geeft per project de API-key mee voor projecten die de caller beheert.
  **Die respons bevat dus geheimen** — nooit loggen, redigeren in `--verbose`.

Openstaand en te verifiëren tijdens het bouwen: of de device-grant op de *client*
`rig-platform-operations-manager` aanstaat (realm-brede support is niet genoeg). Zo niet:
authorization code + PKCE op een loopback-listener, en device flow als vervolg.

### 1.4 Sandbox en handmatig testen

Basis-URL `https://zad.sandbox.rijksapp.dev/api`. Er draait een omgeving waar je tegenaan mag
testen. **Je mag de sandbox niet aanpassen** — behandel bestaande projecten als read-only.

De catalogus-endpoints (`/api/v2/services`, `/api/v2/services/{naam}`) zijn zonder key te
raadplegen. Gebruik ze als fixture-bron, maar **doe geen echte calls in de testsuite**
(bestaande regel: `respx` voor httpx-mocking, `subprocess` voor CLI-integratie).

Er is een gedeelde sandbox-testcluster met turn-taking: `orch sandbox {status|claim|release}`.
Claim hem voordat je iets tegen de echte cluster draait, en geef hem daarna terug.

**API-tokens uitlezen.** Er is geen endpoint dat een plaintext API-key teruggeeft — dat is met
opzet zo. De tooling ervoor staat in de RIG-Cluster-repo op Forgejo, branch
`branches-samenvoegen-naar-main`. Check die uit in een tmp-map (niet in deze repo):

```bash
git clone --depth 1 --branch branches-samenvoegen-naar-main \
  <forgejo>/robbert/RIG-Cluster.git /tmp/rigc
cd /tmp/rigc/operations-manager/python
```

Twee bruikbare scripts in `operations-manager/python/scripts/`:

| Script | Waarvoor |
|---|---|
| `sandbox_project_tool.py` | **Eerste keus.** HTTP-only, seconden in plaats van een browser. `uv run python scripts/sandbox_project_tool.py api-key <project>`, plus `delete` en `set-config`. Defaults staan al op de sandbox. |
| `extract_project_api_key.py` | Zwaardere route: decrypt de AGE-versleutelde key uit het projectbestand via de clustermasterkey (kubectl) en Forgejo. Nodig als het HTTP-pad niet werkt. |

**SSO-testaccount (alleen sandbox):** gebruiker `admin`, wachtwoord `admin1234` op
`https://keycloak.sandbox.rijksapp.dev/realms/operations-manager`. Gebruik dit om `zad login`
(fase 7) end-to-end te proberen. Deze credentials horen bij een wegwerp-sandbox: nooit
overnemen in code, tests, fixtures of documentatie in deze repo.

Of je zelf een projectbestand kunt aanmaken op de sandbox is niet vastgesteld — probeer het, en
als het niet lukt, val terug op een bestaand project in read-only-modus en test de muterende
paden met `respx`.

---

## 2. Werk

Fasen in volgorde. Fase 1 en 2 zijn fundament — daarna kan de rest in willekeurige volgorde.
Werk per fase toe naar groen (`uv run pytest`, `uv run ruff check .`, `uv run ruff format .`).

### Fase 1 — De CLI leest de catalogus [fundament]

- [ ] `api/registry.py`: client + typed modellen voor `GET /api/v2/services` en
      `GET /api/v2/services/{naam}`. Geen API-key. Cache op schijf onder
      `~/.cache/zad/services-<hash-van-api-url>.json` met TTL (voorstel: 24u) en
      `--refresh-catalog` om te forceren. Val bij een cache-miss zonder netwerk terug op een
      meegeleverde snapshot, en zeg dat dan ook.
- [ ] `services.py` (hardcoded lijst) **verwijderen**. Alle validatie van dienstnamen gaat via
      de registry. Onbekende naam → foutmelding die de geldige namen noemt, zoals de API zelf doet.
- [ ] `zad service list` — de catalogus, met `kind`, `binding`, `targets`. Standaard zonder
      `hidden`-diensten; `--all` toont ze.
- [ ] `zad service describe <naam>` — rendert `explanation` als markdown (Rich), plus de
      `variables`-tabel (naam, beschrijving, aliassen) en `requires`.
- [ ] `zad service types` behouden als alias van `service list` óf laten vervallen — kies één en
      leg vast in `CLAUDE.md`.
- [ ] Autocompletion voor dienstnamen uit de gecachete catalogus.

**Klaar als:** `zad service list` toont 21 diensten uit de live API, `zad service describe
postgresql-database` toont de Nederlandse uitleg, en er staat nergens meer een dienstnaam in de
broncode.

### Fase 2 — Opslaan en uitrollen zijn twee dingen [fundament]

- [ ] Globale optie `--rollout / --no-rollout` (default: `--rollout`, gelijk aan het huidige
      gedrag). Wordt doorgegeven als `rollout`-queryparameter op elke muterende call die hem
      accepteert. Bepaal per endpoint uit de spec of hij hem accepteert — hardcodeer geen lijst.
- [ ] `zad project pending` → `GET /api/v2/projects/{p}/pending-rollout`. Toont wat er opgeslagen
      is maar nog niet uitgerold.
- [ ] Waarschuwing na een `--no-rollout`-mutatie: hoeveel wijzigingen er nu open staan en hoe je
      ze uitrolt (`zad project refresh`).
- [ ] `zad project refresh` documenteren als "rol alles in één keer uit".

**Klaar als:** een `--no-rollout`-mutatie zichtbaar is in `zad project pending` en pas landt na
een refresh.

### Fase 3 — Elke dienst is in te stellen

Dit is de grootste winst: ~50 endpoints via één generieke laag, gestuurd door `layers[].config_endpoint`.

- [ ] `zad service config get <dienst> [--target project|component|deployment] [--component c]
      [--deployment d]` → `GET /api/v2/projects/{p}/services/{naam}/config`.
- [ ] `zad service config set <dienst> ...` → de `PUT` uit `config_endpoint` van de gekozen laag.
      Waarden via `--set pad.naar.veld=waarde` (§4) én `-f manifest.yaml`.
- [ ] `zad service config clear <dienst> ...` → de `DELETE` uit dezelfde laag. Met `--yes`.
- [ ] Laag-keuze: als een dienst maar één `target` heeft, is `--target` optioneel en wordt die
      laag gekozen. Bij meer dan één is `--target` verplicht — geen stille default.
- [ ] Validatie vóór verzending tegen de JSON Schema uit de spec, met een leesbare fout die het
      veldpad noemt.
- [ ] `zad service config schema <dienst> --target <laag>` — print de JSON Schema. Dit is wat een
      agent nodig heeft om een geldige config te bouwen.

**Klaar als:** `zad service config set postgresql-database --set scope=project` werkt, en een
ongeldige waarde wordt lokaal afgevangen met een bruikbare fout.

### Fase 4 — Manifest, skeleton en `--set`

Overgenomen uit het oude §1; nu veel waardevoller omdat de spec 168 schemas heeft.

- [ ] Generieke `--set pad.naar.veld=waarde` loader (herhaalbaar, dotted paths, lijst-indices).
- [ ] `-f/--file` op de muterende commando's: YAML (JSON is een subset), `-` voor stdin, flags
      overriden de file (Helm-model).
- [ ] `--generate-skeleton` per commando, afgeleid uit de spec-schemas.
- [ ] JSON Schema publiceren zodat een manifest een `# yaml-language-server: $schema=…`-regel kan
      dragen en editors autocomplete geven.
- [ ] Generieke `@file` / `file://` waarde-loader op elke optie.
- [ ] `rich_help_panel` groepen in `--help`: Netwerk, Resources, Services, Domein.

### Fase 5 — Bijlagen

Endpoints (7). Let op: de API kent een **catalogus** (project-niveau) en een **koppeling**
(component-niveau) — precies de scheiding die hieronder in de commando's terugkomt.

```
POST   .../services/attachments/attachment                                   catalogus: aanmaken
PUT    .../services/attachments/attachment/{id}                              catalogus: bijwerken
DELETE .../services/attachments/attachment/{id}                              catalogus: verwijderen
POST   .../services/attachments/component/{c}/attachment                     koppelen (nieuw of by reference)
PUT    .../services/attachments/component/{c}/attachment/{id}                koppeling bijwerken
PUT    .../services/attachments/config/component/{c}                         config-laag
DELETE .../services/attachments/config/component/{c}                         config-laag wissen
```

- [ ] `zad attachment add <naam> --from-file ./app.yaml [--description …]` → catalogus. Uploaden
      zonder te koppelen moet kunnen.
- [ ] `zad attachment assign <naam> <component> [--deployment d] --mount-path /etc/app/conf.yaml`
      → koppeling. **`--mount-path` hoort bij de koppeling, niet bij het bestand**: hetzelfde
      bestand kan per deployment op een ander pad landen.
- [ ] `zad attachment update <naam> --from-file ./app.yaml` → nieuwe inhoud, koppelingen blijven.
- [ ] `zad attachment list [--component c]`, `zad attachment delete <naam>`.
- [ ] `--from-file -` (stdin) plus een maximumgrootte; binair → base64 als de API JSON verwacht.
- [ ] Guard-regel uit §0 opnemen in de argumentregels van `CLAUDE.md`.

### Fase 6 — Omgevingsvariabelen en aliassen

`user-env-vars` (10 ops) en `aliases` (5 ops). Beide zijn `kind=system` met `value_targets`, niet
`targets` — ze hebben *values*, geen config. Houd dat onderscheid in de commando's vast.

- [ ] `zad env set|get|list|unset --component c [--deployment d]` op user-env-vars. De
      deployment-variant is specifieker dan de component-variant en overschrijft die.
- [ ] Bulk: `--env-file` en `--from-file`. Let op `POST` (toevoegen) vs `PATCH` (wijzigen) vs
      `/:delete` (meerdere weghalen) vs `DELETE /{key}` (één weghalen) — vier verschillende
      semantieken, geen van alle inwisselbaar.
- [ ] `zad alias set|list|unset --component c`. Een onbekende verwijzing is hier volgens de API
      een **harde fout**, anders dan bij een eigen env-var; laat dat terugkomen in de foutmelding.

### Fase 7 — Projecten aanmaken en terugvinden

Hangt op §1.3. Doe de credential store vóór de rest van deze fase.

- [ ] Credential store `~/.config/zad/credentials.toml`, 0600, per project, met OS-keyring als
      dat kan en file als fallback. Redactie in `--verbose`.
- [ ] `zad login` — device flow tegen Keycloak (verifieer eerst of de grant op de client
      aanstaat; zo niet: authorization code + PKCE op een loopback op `127.0.0.1`, nooit
      `0.0.0.0`, met verplichte `state`-nonce en één request).
- [ ] `zad project list` → `GET /api/v2/projects` met bearer token. **Respons bevat API-keys**:
      niet tonen tenzij expliciet gevraagd, nooit loggen.
- [ ] `zad project create <naam>` → `POST /api/v2/projects` met bearer token. De key komt één keer
      terug: direct opslaan in de credential store en dat melden.
- [ ] `zad project use <naam>` — zet het actieve project. `ZAD_PROJECT_ID` wordt een override
      in plaats van de enige bron.
- [ ] `--export` (voor `eval "$(…)"`) en `--write-env .env`.

### Fase 8 — Restant en opruiming

- [ ] `zad db schema list|add|remove` → de drie `postgresql-database/schemas`-endpoints.
- [ ] `zad admin cleanup|reconcile` → de drie ongedekte admin-endpoints.
- [ ] `zad version` toont ook de server-versie via `GET /version`.
- [ ] `zad registry add` → `registries/by-credentials` / `by-secret` (nu v1-deprecated; gebruik
      het v2-equivalent zodra dat er is, anders v1 met een notitie).
- [ ] **Opruiming 1.0**: `service add` in zijn oude vorm eruit, `--components` JSON-string eruit
      ten gunste van `-f`, flagnamen consistent. Nieuwe baseline voor
      `tests/test_backwards_compat.py`. `CLAUDE.md` bijwerken: policy wordt "additief binnen een
      major", en de nieuwe conventies (registry als bron, `--from-file`, `--rollout`, `--target`).
- [ ] `api/upstream-openapi.json` vervangen door de sandbox-spec en `scripts/check_coverage.py`
      erop laten draaien; het doel is dat het rapport leeg is op de bewust overgeslagen paden na.
- [ ] `README.md` bijwerken: nieuwe commandolijst, `zad login`, rollout-model.

---

## 3. Randvoorwaarden

- **Elke muterende commando** houdt zich aan het bestaande sjabloon: `--dry-run` vóór
  bevestiging, `--yes/-y`, `@handle_api_errors`, `formatter.render_success`, project via
  `require_project(ctx)`.
- **Output**: alles respecteert `--output table|json|yaml`; data naar stdout, status naar stderr.
  Voor agents is `--output json` het pad — controleer dat elk nieuw commando daar bruikbare JSON
  geeft, niet alleen een tabel-dump.
- **Geen echte API-calls in tests.** `respx` voor de client, `subprocess` voor CLI-integratie,
  `capsys` voor output. Neem de catalogus-respons als fixture op.
- **Geheimen**: de project-lijst en project-create geven API-keys terug. Nooit in logs, nooit in
  `--verbose`, en in tabel-output gemaskeerd tenzij expliciet opgevraagd.
- **Conflicterende naamgeving**: `--path` betekent al *ingress path*; gebruik `--mount-path`.
  `task list` gebruikt `--filter-project` om niet met de globale `-p` te botsen.

## 4. Buiten scope

- De geparkeerde CI-bootstrap (`zad ci`) — zie de bijlage hieronder. Niet bouwen.
- Een build-generator voor applicaties (Dockerfiles, testrunners).
- `zad apply -f zad.yaml` voor een heel project met een `diff`/plan-stap. Verdient een eigen
  ontwerp nadat fase 3 en 4 staan.

## 5. Klaar als

- `scripts/check_coverage.py` tegen de sandbox-spec rapporteert geen ongedekte endpoints meer,
  op de bewust overgeslagen infrastructuurpaden na.
- `uv run pytest` en `uv run ruff check .` zijn groen.
- `zad service list` en `zad service describe <naam>` werken tegen de live sandbox.
- `zad-actions` blijft werken op `deployment create` / `deployment delete`, of de benodigde
  pin-bump staat expliciet in de PR-beschrijving.
- `CLAUDE.md` beschrijft het nieuwe model; er staat geen dienstnaam meer hardcoded in de repo.

---

# Bijlage: `zad ci` — CI-bootstrap op GitHub en Forgejo — GEPARKEERD

> **Geparkeerd 2026-08-06. Niet onderdeel van 1.0.** Haalbaarheid is uitgezocht en het antwoord
> is ja; het staat alleen niet op de rol. Bewaard als vooronderzoek.

Kan de CLI in een GitHub- of Forgejo-repo de CI-actie ophangen én de projectsecret zetten, met
de credentials van de gebruiker zelf? Ja, en volledig client-side.

**Secrets zetten.** Forgejo/Gitea: `PUT /api/v1/repos/{o}/{r}/actions/secrets/{naam}` met body
`{"data": "<plaintext>"}`, geen client-side crypto. GitHub: public-key ophalen, libsodium sealed
box, dan `PUT` met `encrypted_value` + `key_id` — kost één dependency (PyNaCl) en ~15 regels.

**Workflow-bestand.** Er is geen workflow-API; je commit `.github/workflows/x.yml` via de
Contents API, en dat vereist op GitHub de aparte `workflow` scope die een standaard `gh`-token
niet heeft. Besluit: **het workflow-bestand lokaal in de working tree schrijven, niet pushen.**
Alleen de secrets gaan over de API.

**Auth.** Niets te bouwen: `gh auth token` / `tea`-config → env var → PAT in de credential store.
OAuth device flow is voor Forgejo geen optie (bestaat niet, en Forgejo heeft *geen* OAuth2-scopes
— een OAuth-token geeft daar volledige controle over het account).

**Forgejo-valkuil.** Forgejo Actions haalt `uses:` standaard van de eigen instance, niet van
GitHub. Genereer daar een workflow die zad-cli direct installeert.
