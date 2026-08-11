# Bevindingen: playbook 01 tegen de sandbox

Afgespeeld op **10 augustus 2026, 21:06–21:20 UTC** tegen
`https://zad.sandbox.rijksapp.dev/api`, met zad-cli op commit `a331e99` (basis `v1`).
Eigen project `p2-2u6` (weergavenaam "Playbook 205412"), plus een tweede project `pi-dps`
om één bevinding te isoleren. Beide zijn na afloop verwijderd.

De sandbox was bij aanvang van de sessie niet beschikbaar: `orch sandbox` stond op
`rebuild` ("cluster herbouw op branch naar-het-nieuwe-componentensysteem") en zowel de API
als Keycloak gaven 502. Om 21:05 kwam de API terug, om 21:06 kwam het slot vrij en is het
geclaimd. **Deze run meet dus een net herbouwd cluster**, wat bij de uitrolbevinding hieronder
uitmaakt.

---

## Per stap

| Stap | Uitkomst | Kort |
|---|---|---|
| 0. Opzet | **gelukt** | controle op sandbox-URL slaagt |
| 1. Inloggen | **gelukt** | headless inlog werkt, token doorstaat de audience-controle |
| 2. Het project | **gelukt** | `p2-2u6`, sleutel in `./.env` |
| 3. Uitrollen uitzetten | **gelukt** | |
| 4. De drie componenten | **gelukt** | |
| 5. Diensten op projectniveau | **deels** | `minio-storage` faalt op de CLI-vorm (bev. 1) |
| 5b. Databaseschema | **gelukt** | vorm van `db schema list` hieronder vastgelegd |
| 6. Diensten per component | **deels** | 6 van 6 falen op de playbookvorm; 2 oorzaken (bev. 1, 9, 10) |
| 7. Omgevingsvariabelen | **gelukt** | alle controles slagen; `env list` toont niets (bev. 5) |
| 8. Aliassen | **deels** | 3 van 5 controles falen (bev. 6, 7, 11) |
| 9. Bijlagen | **gelukt** | alle controles slagen |
| 10. Wat staat er te wachten | **gelukt** | 22 wijzigingen in de wachtrij |
| 11. De deployment, en uitrollen | **gefaald** | `deployment create` breekt de API (bev. 3); `project refresh` faalt (bev. 4) |
| 12. Wachten tot het draait | **overgeslagen** | er is geen deployment om op te wachten |
| 13. Het echte bewijs | **overgeslagen** | er draait niets; zie "Wat niet te testen viel" |
| 14. Opruimen | **gelukt** | beide projecten weg, controle slaagt |

---

## De bevindingen

### De CLI doet iets fout

#### 1. `service config set` weigert een lege configuratie die de API wél accepteert

> **Opgelost op 11 augustus** in `v1`. Een ontbrekende body is nu `{}` in plaats van een
> weigering; een dienst die wél velden vereist wordt nog steeds door de schemacontrole
> gevangen. De playbookvorm uit stap 5 en 6 werkt sindsdien zoals hij er stond.

De playbookvorm voor een dienst die je alleen aanzet:

```
$ zad service config set minio-storage --target project
Invalid value: Nothing to send: pass -f/--file, --set, or both.
[exit 2]
```

Dezelfde selectie via een leeg manifest wordt door de API zonder morren aangenomen:

```
$ echo {} | zad service config set minio-storage --target project -f -
Service 'minio-storage' configured at layer 'project'.
```

Het is dus een lokale weigering van de CLI, niet van de API. "Dienst gekozen, geen
configuratie" is een echte toestand — de API documenteert hem zelf in `ServiceUsage.config`
("Null means the service is selected"). Raakt in dit playbook `minio-storage`,
`health-check` en `metrics-scraper`.

#### 2. Geen bevinding: het verzoek van `deployment create` klopt

Wel nagegaan, want het scheelt in de schuldvraag bij bevinding 6. `--verbose` toont:

```
--> POST /api/v2/projects/p2-2u6/:upsert-deployment
    Body: {'deploymentName': 'productie', 'components': [{'reference': 'web', 'image': '...'}]}
```

Dat is precies `UpsertDeploymentRequest` uit de **live** spec (`required: ['deploymentName']`,
`components[].reference/.image`). De CLI stuurt het goede verzoek; de fout valt aan de
overkant.

### De API doet iets fout of onhandig

#### 3. `upsert-deployment` breekt op `'deployments'` — geen enkele deployment is aan te maken

De zwaarste bevinding van deze run.

```
$ zad deployment create productie --component web --image ghcr.io/minbzk/base-images/e2e-allservices:latest
✗ The operation only got part of the way: some steps succeeded, a later one failed.
  Error upserting deployment 'productie': 'deployments'
  error_type: internal_error
  failed: Deployment upsert: Error upserting deployment 'productie': 'deployments'
  completed: Deployment validatie
[exit 3]
```

De aangehaalde `'deployments'` leest als een Python `KeyError` op de projectstructuur.
Wat ik heb uitgesloten:

- **Niet de componenten.** `zad deployment create leeg` — zonder `--component` — faalt
  identiek. De spec staat een lege lijst expliciet toe.
- **Niet `rollout`.** Op een tweede, vers project faalt zowel `--no-rollout` als `--rollout`
  met dezelfde melding.
- **Niet de opgestapelde wijzigingen.** Ook op het verse project `pi-dps`, met één component
  en verder niets, faalt hij.
- **Niet de validatie ervoor.** Zolang de component níet bestaat komt er een keurige fout
  (`Invalid component references ... Available components: ['none']`). Pas als de validatie
  slaagt, klapt de upsert. De crash zit dus achter de validatie.

Op dit cluster is daarmee geen enkele deployment aan te maken, en stap 11 tot en met 13 van
het playbook zijn onbereikbaar.

#### 4. `project refresh` faalt op "Diensten en manifesten bijwerken" — ook op een vers project

Dit bevestigt wat vooraf bekend was van `hwt-nqi`, nu op een project dat een kwartier oud is:

```
$ zad project refresh
  Project processing failed - check logs for details
  failed: Alle deployments opnieuw verwerken: Project processing failed - check logs for details
  failed: Diensten en manifesten bijwerken: Bijwerken van diensten en manifesten is mislukt
  completed: Project opzoeken en wijzigingen uit git ophalen, Projectbestand ophalen en controleren
[exit 3]
```

`zad task status <id> -o json` geeft niets meer dan dit: geen `component_failures`, geen
`error_type` op de subtaken, alleen "check logs for details". **Het ligt dus niet aan het
project.** Of het aan de omgeving ligt is van buitenaf niet vast te stellen; de oorzaak staat
in serverlogs waar de CLI niet bij kan. Dat de CLI hier "Source: not attributable from the
response" zegt is het eerlijke antwoord, geen tekortkoming.

#### 5. Er is geen leesweg voor omgevingsvariabelen en aliassen

`zad env list -c web` geeft een lege verzameling terwijl de variabelen aantoonbaar bestaan:

```
$ zad env list -c web -o json
{ "service": "user-env-vars", "configurations": [] }

$ zad project describe --part components -o json | jq -c '[.components[] | {name, env_var_names}]'
[{"name":"web","env_var_names":["APP_MODE","LOG_LEVEL"]}, ...]
```

De oorzaak zit in de API, niet in de CLI. `zad env list` bevraagt
`/services/user-env-vars/config`, en dat endpoint antwoordt met een lege `configurations`.
Het endpoint dat de registry zelf in zijn `explanation` noemt —
`/services/user-env-vars/values/component/{component}` — heeft **geen GET**:

```
$ curl -H 'X-API-Key: ...' .../services/user-env-vars/values/component/web
{"detail":"Method Not Allowed"}
```

De live spec bevestigt het: op alle `…/values/…`-paden staan alleen `post`, `patch` en
`delete`. Er is dus geen enkel endpoint dat de waarden of namen teruggeeft; `env_var_names`
uit `project describe` is de enige leesweg. Zolang dat zo is kan `zad env list` niet werken.
Hetzelfde geldt voor `zad alias list`.

#### 6. Aliaswaarden komen gemaskeerd terug als `***`

```
$ zad project describe --part components -o json | jq -c '[.components[] | {name, aliases}]'
[{"name":"web","aliases":{"POSTGRES_HOST":"***"}}, ...]
```

Een alias is een verwijzing naar een platformvariabele (`$DATABASE_SERVER_HOST`), geen
geheim. Maskeren maakt de koppeling onleesbaar: je kunt zien *dat* er een alias is, niet
*waar hij heen wijst*. De controle van stap 8 kon daardoor nooit slagen.

#### 7. Een alias naar een niet-bestaande variabele wordt geaccepteerd

Het playbook noemt dit een harde fout, en dat is het niet:

```
$ zad alias add -c web KAPOT='$BESTAAT_ECHT_NIET'
│ success │ component │ True │ aliases │ web │ add │ ...
[exit 0]
```

De verwijzing wordt zonder controle opgeslagen. Merk op dat de registry dit gedrag voor
*eigen* variabelen uitdrukkelijk beschrijft ("een verwijzing die niet bestaat blijft hier
gewoon staan, want een dollarteken in een wachtwoord is geen typefout") — maar bij aliassen,
waar de verwijzing het hele punt is, betekent het dat een typefout pas in de container
opvalt. Ik heb `KAPOT` daarna weer verwijderd zodat hij stap 13 niet kon vertroebelen.

#### 8. `deployment delete` meldt succes voor een deployment die nooit bestond

```
$ zad deployment delete productie
Deployment 'productie' deleted.
[exit 0]
```

`productie` is nooit aangemaakt (bevinding 3), en drie eerdere commando's zeiden in
dezelfde run nog `Deployment 'productie' not found in project 'p2-2u6'`. Idempotent
verwijderen is verdedigbaar, maar dan mag de melding niet "deleted" zijn.

### Het playbook klopt niet

#### 9. `publish-on-web` heeft er een laag bij gekregen, dus `--target` is verplicht

```
$ zad service config set publish-on-web --component web --set tls=standard
Invalid value: Service 'publish-on-web' accepts more than one layer; pass --target
[exit 2]
```

De live registry geeft `publish-on-web` de targets `['component', 'deployment']`. De
gebundelde momentopname in `src/zad_cli/data/services-snapshot.json` zegt nog `['component']`
— vandaar dat het playbook `--target` wegliet. Gecorrigeerd naar
`--target component --component web`; daarmee slaagt de controle van stap 6.

Dit is meteen een signaal op zichzelf: **de snapshot waartegen de testsuite draait loopt
achter op de sandbox.** Verversen is werk voor een aparte PR, want het verschuift de basis
onder de tests.

#### 10. `persistent-storage` en `temp-storage` dragen wél configuratie

Het playbook zet ze aan zonder inhoud. Dat kan niet: hun configuratie is een *lijst volumes*.

```
$ echo {} | zad service config set persistent-storage --component api -f -
Invalid value: This body is not valid for persistent-storage (component) config:
  - (root): expected array, got dict.
  Run the same command with --generate-skeleton for an example body.
[exit 2]

$ zad service config set persistent-storage --target component --component api --generate-skeleton
- name: ''
  size: ''
  mount-path: ''
```

Gecorrigeerd naar een echt volume per component. De lokale schemacontrole van de CLI wees
hier precies de goede kant op — dat werkt zoals bedoeld.

#### 11. De controle op de aliaswaarde kan niet slagen

Stap 8 toetste `.aliases.POSTGRES_HOST | test("DATABASE_SERVER_HOST")` op een veld dat de API
maskeert (bevinding 6). Gecorrigeerd naar een controle op aanwezigheid, met de reden erbij,
zodat de stap niet net doet alsof hij de verwijzing verifieert.

De verwachting in dezelfde stap dat een onbekende verwijzing hoort te falen heb ik **laten
staan**: die is niet fout, de API gedraagt zich fout (bevinding 7). Het playbook aanpassen
zou die bevinding wegpoetsen.

---

## Wat niet te testen viel, en waarom

- **Stap 12 (wachten tot het draait)** en **stap 13 (het echte bewijs)** zijn niet gedraaid.
  Beide beginnen bij `zad deployment describe productie`, en er is geen deployment: bevinding
  3 maakt aanmaken onmogelijk. Doorgaan had alleen dezelfde fout herhaald.
- **Stap 13 is de enige stap die iets zegt zonder de CLI op zijn woord te geloven.** Dat die
  niet gedraaid heeft, betekent dat *geen enkele* dienstbinding in dit rapport is bewezen
  tegen een draaiende workload. Alles onder stap 4 tot en met 10 is "de API bevestigt dat het
  is opgeslagen", niet "het werkt". Per dienst OK of FAIL kan ik dus niet geven.
- **De uitrol zelf** (stap 11, `project refresh`) is wel geprobeerd en faalt, zie bevinding 4.
  Of hij ná een geslaagde deployment anders zou lopen is niet vast te stellen.
- **`zad env list` / `zad alias list` als leescontrole** zijn niet bruikbaar te maken zolang
  bevinding 5 staat.

## Wat vooraf bekend was, getoetst

| Bewering | Uitkomst |
|---|---|
| De uitrol faalt op `Diensten en manifesten bijwerken` | **Bevestigd**, ook op een vers project (bevinding 4). |
| `env_var_names` komt als `null` terug voor componenten zonder variabelen | **Weerlegd op deze build.** `api` en `worker` gaven `[]`, niet `null`. De controle van stap 7 slaagde gewoon. |
| De vorm van `zad db schema list` is niet geverifieerd | **Vastgelegd**, zie hieronder. Zowel tabel als json kloppen. |
| `zad env list` / `zad attachment list` geven `{service, configurations: [...]}` | **Bevestigd.** Bij `attachment list` werkt dat: de controle van stap 9 slaagt op `.configurations[].config.data[]?.id`. Bij `env list` is de vorm niet het probleem — de lijst is leeg (bevinding 5). |

### De vorm van `zad db schema list`

Een platte lijst, met het standaardschema als regel met een lege `postfix`:

```json
[
  { "postfix": "", "is_default": true,
    "description": "Het standaardschema van dit project. ...",
    "marked_for_deletion": false, "variable_name": "DATABASE_SCHEMA",
    "aliases": ["APP_DATABASE_SCHEMA"], "deployments": [] },
  { "postfix": "rapportage", "is_default": false, "description": "",
    "marked_for_deletion": false, "variable_name": "DATABASE_SCHEMA_RAPPORTAGE",
    "aliases": ["APP_DATABASE_SCHEMA_RAPPORTAGE"], "deployments": [] }
]
```

De tabelweergave toont beide regels, met een lege eerste kolom voor het standaardschema.

## Opgeruimd

`p2-2u6` en `pi-dps` zijn verwijderd; de controle van stap 14 (`! zad project status`)
slaagt. Daarna geeft `zad project list` "No results": er staat niets meer op de sandbox.

Over `hwt-nqi` uit de opdracht: dat project was er tijdens deze run niet, en ik heb het niet
verwijderd — mijn twee `project delete`-aanroepen noemen `p2-2u6` en `pi-dps`. Waarschijnlijk
is het meegegaan in de clusterherbouw die vlak voor deze run liep. Bewijzen kan ik dat niet:
de controle van stap 1 (`type == "array"`) gooit de lijst weg, dus in het transcript staat
niet wélke projecten er bij aanvang waren.
