# Bevindingen: playbook 02 (diensten per laag) tegen de sandbox

Afgespeeld op **11 augustus 2026, 09:50–10:00 UTC** tegen
`https://zad.sandbox.rijksapp.dev/api`, build `2e8e25fc`. Projecten `w0-vk3` en `d0-zh4`
(tweede doorloop na een correctie), na afloop verwijderd. Eerste doorloop van dit playbook.

**Uitkomst: alle controles slagen**, inclusief de volledige matrix van **17
dienst-laagcombinaties**.

Na deze run is `93ed2a07` uitgerold; volgens de RC-69-sessie is `opi/` daarin
byte-identiek aan `2e8e25fc`, dus deze resultaten beschrijven ook wat er nu draait.

---

## Per stap

| Stap | Uitkomst | Kort |
|---|---|---|
| 1. Project en componenten | **gelukt** | |
| 2. De registry is de lijst | **gelukt** | elke instelbare dienst noemt minstens één laag |
| 3. Elke dienst op elke laag | **gelukt** | 17 van 17, zie hieronder |
| 3b. Een laag die niet bestaat | **gelukt** | wordt geweigerd |
| 4. De diensten die 01 oversloeg | **gelukt** | `invite`, `authorization-wall`, `sleep-mode`, `health-check`, `metrics-scraper` |
| 5. `config get` | **gelukt** | alle lagen in één antwoord |
| 6. `config clear` per laag | **gelukt** | één laag weg, de andere blijft |
| 7. Verborgen diensten | **gelukt** | `--all` toont ze, zonder `--all` niet |
| 8. Opruimen | **gelukt** | |

## De matrix

De lagen komen uit `zad service list -o json`, niet uit het playbook. Dat leverde deze 17
combinaties op, en de CLI accepteert ze alle 17:

| Dienst | Lagen |
|---|---|
| `attachments` | component |
| `authorization-wall` | project |
| `cross-domain-access` | project, deployment |
| `health-check` | component |
| `invite` | project |
| `metrics-scraper` | component |
| `minio-storage` | project, deployment |
| `persistent-storage` | component |
| `postgresql-database` | project |
| `publish-on-web` | component, deployment |
| `redis` | project |
| `sleep-mode` | project |
| `temp-storage` | component |

En de andere kant op, want een CLI die alles accepteert toetst niets:

```sh
! zad service config set health-check --target project --generate-skeleton
! zad service config set postgresql-database --target component --component web --generate-skeleton
```

Beide worden geweigerd, met een melding die de lagen noemt die er wél zijn:
`Service 'health-check' has no 'project' layer. Available: component`.

## Wat er in het playbook is gerepareerd

**De laagproef gebruikte `--set x=y --dry-run`, en dat meet het verkeerde.** De eerste
doorloop meldde 15 falers op de matrix, wat eruitzag als een CLI die zijn eigen registry niet
volgt. Het tegendeel bleek waar: de lokale schemacontrole van de CLI keurde het *veld* af
voordat er ook maar iets met de laag gebeurde.

```
$ zad service config set redis --target project --set x=y --dry-run -o json
{"error": "This body is not valid for redis (project) config:\n
   - (root): unknown field 'x'. Known fields: acl-key-prefix.", "status_code": 2}
```

Dat is de schemacontrole die precies doet wat hij moet doen. De proef is gecorrigeerd naar
`--generate-skeleton`: die neemt een laag en geen lichaam, en drukt de vorm van díe laag af.
Daarmee meet hij de laag en niets anders. Sindsdien: 17 van 17.

Dit is het tweede voorbeeld in deze reeks van een controle die op de verkeerde vorm test en
dan een probleem suggereert dat er niet is — vergelijk `[.[].name]` op `deployment list` in
playbook 03.

## De vorm van `zad service config get`

Eén antwoord over alle lagen heen, wat de vraag "waar staat dit eigenlijk aan" beantwoordt:

```json
{
  "service": "publish-on-web",
  "configurations": [
    { "target": "component", "component": "web", "config": { "tls": "standard" } },
    { "target": "component", "component": "api", "config": { "tls": "standard" } }
  ]
}
```

Na `zad service config clear publish-on-web --target component --component api` blijft
alleen de regel van `web` staan. Een dienst die helemaal uit staat geeft
`"configurations": []`.

## De skeletten van de diensten die playbook 01 oversloeg

Vastgelegd omdat ze nergens anders staan, en omdat ze laten zien welke van deze diensten je
"alleen aanzet" en welke echt configuratie dragen:

```yaml
# invite (project)
default-language: nl
active: [{key: ''}]

# authorization-wall (project) — vereist services/publish-on-web volgens de catalogus
banner: ''

# cross-domain-access (project, deployment)
inbound: [{name: ''}]
outbound: [{name: ''}]

# sleep-mode (project)
enabled: false
match: ['']
sleep-after-deploy: 48h
sleep-after-wake: 1h
waker: true
waker-component: ''
wake-mode: auto
title: ''
description: ''

# keycloak (project)
template: sso-only
realms: [{host: '', realm: '', username: '', password: ''}]
variables: {}
additional_redirect_uris: ['']
restrict-access: {enabled: false, role: ''}
```

`health-check` en `metrics-scraper` dragen geen velden: die zet je alleen aan, en dat werkt
sinds de reparatie van bevinding 1 met `zad service config set health-check --component web`.

## Wat niet te testen viel, en waarom

- **`keycloak` met echte realms.** De configuratie vraagt host, realm, gebruikersnaam en
  wachtwoord van een Keycloak die niet van dit project is. Alleen het skelet is vastgelegd.
- **`cross-domain-access` met echte waarden.** `inbound[].name` en `outbound[].name`
  verwijzen naar andere projecten of deployments; wat daar geldig is, is van buitenaf niet
  af te leiden. De laag is wel geproefd, de inhoud niet.
- **Of een dienst iets dóet als hij aanstaat.** Dit playbook toetst de configuratielaag.
  Playbook 01 bewijst met `/status` dat een gebonden dienst de workload bereikt; voor
  `invite`, `sleep-mode` en `authorization-wall` is er geen zo'n bewijs, want de testimage
  rapporteert ze niet.
- **De verborgen diensten (`namespace-*`) aanzetten.** Ze zijn geteld en de CLI verzint ze
  niet, maar ze zijn interne varianten die de portal niet aanbiedt; ze aanzetten hoort niet
  in een playbook thuis.
