# zad-cli: alles wat de UI kan, vanaf de opdrachtregel

Dit bestand is het contract voor deze taak. Het is bewust volledig: alles wat nodig is om
te bouwen staat erin, zodat er niets opnieuw uitgezocht of uitgelegd hoeft te worden.
Werk het van boven naar beneden af en vink af.

Vastgesteld 2026-08-09, op basis van onderzoek tegen de draaiende sandbox.

## Waar het plan inmiddels staat

Fase 1 tot en met 8 zijn gebouwd en staan op deze branch. Vier dingen zijn onderweg anders
besloten dan hierboven, en die gelden voor de rest van dit bestand:

- **Het commando heet `zadctl`.** `zad` blijft bestaan als tweede naam voor hetzelfde entry
  point, want daar wijzen bestaande scripts en playbooks naar. Waar hieronder `zad` staat,
  lees `zadctl`.
- **Het blijft voorlopig 0.x, geen 1.0.** De API eronder beweegt nog, en drie brekende
  wijzigingen in de vier dagen rond 12 augustus waren elk dezelfde ontdekking: een commando
  dat nooit gewerkt had. Onder 0.x mag dat; onder 1.x kost elk van die drie een major en een
  belofte die we dan zouden breken. `CLAUDE.md` beschrijft het beleid dat er nu geldt.
- **Er is geen opslag onder `~`.** Fase 7 ging uit van `~/.config/zad/credentials.toml`. Het
  is een env-file in de werkmap geworden, samen met de instellingen, 0600, zodat twee
  checkouts aan twee projecten kunnen werken zonder voor elkaar te beslissen welk project
  actief is. `zadctl config path` zegt om welk bestand het gaat.
- **`zad project describe` is er.** Hij stond hieronder geparkeerd in afwachting van
  upstream; dat is gebeurd.

Wat hierna nog openstaat, staat in de twee bijlagen onderaan.

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
| Versiebeleid | **Opruimen mag, maar het blijft 0.x** (herzien, zie de status hierboven). Breken mag; `tests/test_backwards_compat.py` krijgt dan een nieuwe baseline en de CHANGELOG zegt erbij of het "dit werkte nooit" of "we zijn van gedachten veranderd" was. |
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

Wat hieronder stond is gebouwd en zit in de suite; het is verwijderd in plaats van afgevinkt,
want een lijst waar alles op doorgestreept is leest niemand meer. Fase 1 tot en met 8 zijn
weg: de catalogus als bron, opslaan-versus-uitrollen, `service config` met validatie,
manifesten en `--set`, bijlagen, env-vars en aliassen, projecten aanmaken en terugvinden, en
de opruiming. Wat daarvan afweek van het plan staat in §1, niet hier.

Er ligt niets meer. `check_coverage.py` meldt 129 endpoints, 124 gedekt en 5 bewust niet, elk
met de reden ernaast; er staat geen regel meer onder "uncovered".

Wat er als laatste af ging: `--components` is weg uit `deployment create` (`-f` doet
hetzelfde en `zad-actions` was er al van af), en `GET .../clusters` staat in `DEFERRED` met
de reden dat geen enkel commando een cluster als invoer neemt — het platform plaatst een
deployment, jij kiest niet.

En het lopende gesprek met RIG-Cluster, dat geen code van ons vraagt tot er antwoord is:
kortlevende projecttokens voor agents. Zie `docs/rig-cluster-antwoord-gevraagd.md`; de
volledige lijst met wat we hun vroegen en wat er geleverd is staat in
`docs/vragen-aan-rig-cluster.md`.

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

---

## Afgehandeld: `zad project describe`

Vastgelegd 2026-08-10 als "wacht op upstream". **Upstream heeft geleverd**: er is een
`GET /api/v2/projects/{project_name}`, en `zadctl project describe` draait erop, met
`--part services|components|deployments` om er een stuk uit te vragen. Geheimen zitten er
niet in: env-vars komen terug als namen, en een opgeslagen geheim in een dienstconfig leest
als ingehouden. Hieronder staat waar de vraag vandaan kwam, voor wie het verhaal zoekt.

Er was geen manier om een project als geheel op te vragen. Het leesoppervlak van de v2-API
is `deployments`, `deployments/{d}`, `services/{service}/config`, `pending-rollout` en de
postgres-schema's. Vier gaten:

1. Geen `GET /api/v2/projects/{project_name}`.
2. Niet te zien wélke diensten een project gebruikt: `services/{service}/config` werkt
   alleen als je de naam al weet, dus 21 aanroepen om het te ontdekken.
3. Componentdefinities (poorten, pad, limieten, root, type) zijn schrijfbaar via
   `POST/PATCH .../components` maar nergens leesbaar.
4. `user-env-vars`, `aliases` en `attachments` hebben POST/PATCH/DELETE en **geen GET**.
   Je kunt een env-var zetten en daarna nergens nakijken welke er staan.

Gevraagd: één `GET /api/v2/projects/{project_name}` die het projectbestand als JSON
teruggeeft, met componenten, deployments, de gebruikte diensten per laag en
`pending_rollout`. Zonder geheimen: env-vars als namen, niet als waarden.

Het alternatief, benaderen met 1 + 21 aanroepen, was traag en incompleet genoeg om het niet
als permanente oplossing neer te zetten. Dat is nu ook niet meer nodig.

---

## Upstream: `env_var_names` is `null` waar `[]` hoort

Vastgesteld 2026-08-10, live tegen de sandbox na het mergen van RIG-Cluster PR #60.

Elke component zonder eigen omgevingsvariabelen komt terug met `env_var_names: null`.
Volgens het veld zelf betekent dat "de opgeslagen variabelen konden niet gelezen worden,
wat niet hetzelfde is als er geen hebben". De CLI volgt dat contract en toont
`(unreadable)`, dus in de praktijk leest élke component alsof er iets mis is.

De oorzaak staat in de docstring van `read_user_env_vars`
(`opi/services/project_env_vars.py`): *"or None when nothing is stored or the value could
not be read"*, met `if not raw: return None`. Twee gevallen, één antwoord, terwijl de API
ze juist uit elkaar wil houden.

Voorstel voor upstream: een ontbrekende `user-env-vars`-sleutel levert `{}` op (er zijn er
geen), en alleen een aanwezige waarde die niet ontcijferd kan worden levert `None`. Dan
klopt het onderscheid dat het veld belooft.

Aan CLI-kant niets te doen: het contract volgen is juist, en zelf gaan raden zou het
probleem verbergen. Zodra upstream het onderscheid maakt, klopt de tabel vanzelf.
