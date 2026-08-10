# Proefrit: van niets naar een draaiende deployment

Een copy/paste-lijst om de CLI tegen de sandbox uit te proberen, met de
testimage `ghcr.io/minbzk/base-images/e2e-allservices:latest`. Die image doet bij het
opstarten een echte schrijf-lees-ronde tegen elke dienst waaraan hij gebonden is
(PostgreSQL, Redis, MinIO/S3, Keycloak, gemonteerde volumes) en rapporteert het resultaat op
poort 8080. Boot hij groen, dan werkt de hele koppeling echt.

De endpoints en payloads hieronder zijn geverifieerd met `--dry-run` tegen de CLI op branch
`v1`. Alles wat nog niet werkt staat als zodanig gemarkeerd.

---

## 0. Instellen

Zet dit in `.env` in de repo-root. Dan hoef je verder nooit een vlag mee te geven.

```sh
ZAD_API_URL=https://zad.sandbox.rijksapp.dev/api
ZAD_KEYCLOAK_URL=https://keycloak.sandbox.rijksapp.dev
ZAD_KEYCLOAK_REALM=operations-manager
ZAD_KEYCLOAK_CLIENT_ID=zad-cli
```

Controleren waar elke instelling vandaan komt:

```sh
uv run zad config list
```

De kolom **Source** zegt per instelling wie hem bepaalde: vlag, `.env`, config-bestand of
ingebouwde standaard. Staat er iets op `built-in default` dat je niet verwacht, dan pakt hij
productie in plaats van de sandbox.

## 1. Inloggen

Twee soorten credentials, en dat onderscheid verklaart de hele volgorde hieronder:

| | Wat | Waarvoor |
|---|---|---|
| **SSO-token** | jouw identiteit, kort geldig | alléén `project list` en `project create` |
| **Project-API-key** | per project, langlevend | al het andere |

Je hebt de projectnaam nodig vóór je zijn key kunt hebben — vandaar dat die twee commando's
met een token werken en de rest met `X-API-Key`.

```sh
uv run zad login
```

Opent de browser (`--no-open` als je alleen de URL wilt). Inloggen op de sandbox kan met het
testaccount `admin` / `admin1234`.

```sh
uv run zad project list          # welke projecten mag ik zien
uv run zad project use           # kiezen uit een lijst; zet het actieve project
```

`project use` bewaart project én API-key in `~/.config/zad/credentials.toml` (0600, keyring als
die er is). Daarna is er geen omgevingsvariabele meer nodig — een CLI kan de omgeving van je
shell toch niet muteren. Wil je het tóch in je shell: `eval "$(uv run zad project use x --export)"`.

## 2. Een project

```sh
uv run zad project create "Proefrit" --description "Proefrit met de e2e-testimage"
```

Je geeft een **weergavenaam**; de technische naam wordt daaruit afgeleid en komt terug als
`project_name`. Die afgeleide naam is wat elk later pad en elke header gebruikt, dus die
wordt opgeslagen en getoond — niet wat je typte.

De API-key komt hier **één keer** terug en wordt meteen opgeslagen onder die afgeleide naam.
Wat er ontstaat is de romp van een project: geen componenten, geen deployments, nog niets op
het cluster.

## 3. Deployment en componenten

`deployment create` is een upsert: hij maakt de deployment én de componenten in één
atomaire call. Dat is de enige plek waar meerdere componenten in één keer kunnen.

```sh
IMG=ghcr.io/minbzk/base-images/e2e-allservices:latest

uv run zad deployment create proef --component web --image $IMG
# POST /v2/projects/{p}/:upsert-deployment
# {'deploymentName': 'proef', 'components': [{'reference': 'web', 'image': '...'}]}
```

Meerdere componenten gaan via een manifest — op de commandoregel is er geen manier om te
zien wat bij wat hoort:

```sh
uv run zad deployment create proef --generate-skeleton > proef.yaml
uv run zad deployment create proef -f proef.yaml
uv run zad deployment create proef -f proef.yaml --set components[0].image=$IMG
```

`-f -` leest van stdin, wat handig is voor scripts en agents omdat er dan geen
shell-quoting aan te pas komt.

Een component los definiëren kan ook. Dan geef je met `--deployment` aan in welke
deployments hij meedraait:

```sh
uv run zad component add web --image $IMG --deployment proef --port 8080
# POST /v2/projects/{p}/components
# {'name': 'web', 'type': 'single', 'image': '...', 'deployment_names': ['proef'], 'path': '/'}
```

## 4. Diensten koppelen

Er is geen `service add` meer. Een dienst gebruiken **is** hem configureren, op de laag waar
hij hoort. Welke lagen een dienst accepteert vertelt de catalogus:

```sh
uv run zad service list                          # de 21 diensten van dit platform
uv run zad service describe postgresql-database  # uitleg, variabelen, aliassen
uv run zad service config schema redis           # de velden die deze laag accepteert
```

De testimage probeert alles waaraan hij gebonden is, dus bind er een paar:

```sh
uv run zad service config set postgresql-database --set scope=shared
# PUT /v2/projects/{p}/services/postgresql-database/config/project   {'scope': 'shared'}

uv run zad service config set redis --set acl-key-prefix=true
uv run zad service config set publish-on-web --component web --set tls=standard
# PUT .../services/publish-on-web/config/component/web              {'tls': 'standard'}
```

Heeft een dienst meer dan één laag, dan is `--target` verplicht — er wordt niet gegokt:

```sh
uv run zad service config set minio-storage --target project --set ...
```

## 5. Een nieuwe image

```sh
uv run zad deployment update-image proef --component web --image $IMG
# PUT /v2/projects/{p}/deployments/proef/image
# {'componentName': 'web', 'newImageUrl': '...'}
```

## 6. Uitrollen

Elke muterende opdracht rolt standaard meteen uit. Wil je eerst alles opslaan en in één keer
uitrollen, zet dan de automatische uitrol uit:

```sh
uv run zad config set rollout false      # of ZAD_ROLLOUT=false, of --no-rollout per opdracht
```

Daarna:

```sh
uv run zad project pending               # wat staat er open
uv run zad project refresh               # rol het hele project in één keer uit
uv run zad deployment refresh proef      # of alleen deze deployment
```

De precedentie is **vlag > `ZAD_ROLLOUT` > config > uitrollen**. `zad config list` laat in de
Source-kolom zien welke laag won.

## 7. Kijken of het werkt

```sh
uv run zad project status
uv run zad deployment describe proef
uv run zad logs proef -c web
uv run zad task list                     # muterende calls zijn asynchrone taken
```

De testimage zelf: `GET /` geeft een tabel met per dienst OK/FAIL, `GET /status` dezelfde
gegevens als JSON, en `GET /status?strict=1` antwoordt 503 zolang niet alles verifieert.

## 8. Opruimen

```sh
uv run zad deployment delete proef
uv run zad project delete proefrit
```

---

## Voor agents

- Alles ondersteunt `--output json` (of `--json`). Zet `ZAD_OUTPUT_FORMAT=json` of
  `zad config set output json` om het overal te laten gelden.
- Elke muterende opdracht heeft `--dry-run`: die toont methode, endpoint en payload zonder
  iets te versturen. Dat is de goedkoopste manier om te controleren of een opdracht klopt.
- `zad service list` en `zad service describe` hebben geen credentials nodig. Dat is de weg
  om te ontdekken wat dit platform kan zonder eerst in te loggen.
- `zad service config schema <dienst> --target <laag>` geeft de JSON Schema van een
  configuratie: gebruik die om een geldige payload te bouwen in plaats van te raden.
- Structuur op de commandoregel gaat via `-f -` (stdin) of `--set pad[0].veld=waarde`. Er is
  geen notatie waarbij volgorde bepaalt wat bij elkaar hoort.

## Wat nog niet werkt

- **`zad login` op productie.** De client `zad-cli` bestaat nog niet op realm `rig-platform`
  van `keycloak.rijksapp.nl` — het auth-endpoint antwoordt "Client not found". Op de sandbox
  bestaat hij wel.
- **De device-flow.** Uitgezet op de client (`The flow is disabled for the client`), dus de
  CLI valt terug op de browser-flow met een loopback-listener. Dat werkt, maar over SSH of in
  een container heb je de device-flow nodig — of `ZAD_SSO_TOKEN` met een elders gehaald token.
- **De standaard `api_url` wijst naar productie**, en die draait de oude API: `/api/v2/services`
  geeft daar 404, waarna de CLI terugvalt op de meegeleverde dienstencatalogus en dat luid
  meldt. Voor de sandbox moet `ZAD_API_URL` dus gezet zijn.
