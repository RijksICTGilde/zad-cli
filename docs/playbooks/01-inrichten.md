# Playbook 01: een heel project inrichten

Bouwt een project op van niets tot een draaiende applicatie, en bewijst aan het eind dat het
werkt door de applicatie het zelf te laten zeggen.

De testimage `ghcr.io/minbzk/base-images/e2e-allservices:latest` doet bij het opstarten een
echte schrijf-lees-ronde tegen elke dienst waaraan hij gebonden is: PostgreSQL (inclusief
extra schema's en de meelezende rol), Redis, MinIO, Keycloak en gemonteerde volumes. Hij
rapporteert per dienst OK of FAIL op `GET /status`, en `?strict=1` antwoordt 503 zolang niet
alles verifieert. Daarmee is de laatste stap geen "de CLI zei dat het goed ging" maar "de
workload heeft die diensten echt bereikt, met de credentials die het platform injecteerde".

**Drie componenten met verschillende bindingen**, want daar wordt een fout in de laagkeuze
zichtbaar:

| Component | Diensten | Ingress |
|---|---|---|
| `web` | postgresql-database (project), publish-on-web, health-check | ja, op `/` |
| `api` | redis + minio-storage (project), publish-on-web, persistent-storage | ja, op `/api` |
| `worker` | temp-storage, metrics-scraper | nee |

---

## 0. Opzet

```sh
cd $(mktemp -d)
SUFFIX=$(date +%H%M%S)                    # zodat parallelle runs elkaar niet raken
IMG=ghcr.io/minbzk/base-images/e2e-allservices:latest

cat > .env <<EOF
ZAD_API_URL=https://zad.sandbox.rijksapp.dev/api
ZAD_KEYCLOAK_URL=https://keycloak.sandbox.rijksapp.dev
ZAD_KEYCLOAK_REALM=operations-manager
ZAD_KEYCLOAK_CLIENT_ID=zad-cli
ZAD_YES=true
EOF
```

`ZAD_YES=true` staat erin omdat een playbook geen mens is die kan bevestigen. De uitrol
zetten we pas later uit, zodat je stap voor stap kunt zien wat er gebeurt.

**Controle:** de CLI praat met de sandbox en niet met productie.

```sh
zad config list -o json | jq -e '.effective[] | select(.setting=="api_url") | .value | test("sandbox")'
```

## 1. Inloggen

Met een mens erbij:

```sh
zad login
```

Zonder mens erbij, bijvoorbeeld op het servercluster:

```sh
uv run --with playwright python docs/playbooks/login-headless.py --zad "$ZAD"
```

Dat script omzeilt de inlog niet, het bedient hem: `zad login --no-open --browser` luistert
op 127.0.0.1 en print de URL, en een headless Chromium logt daar in met `admin` /
`admin1234`. Het opgeslagen token is er dus één dat door de echte flow is gekomen,
inclusief de audience-controle. Vereist `playwright install chromium`.

**Controle:** er is een token, en het draagt de audience die de API eist.

```sh
zad project list -o json | jq -e 'type == "array"'
```

## 2. Het project

```sh
zad project create "Playbook $SUFFIX" --description "E2E playbook 01" --use
```

De weergavenaam gaat erin, de technische naam komt eruit. Die afgeleide naam wordt samen met
de API-sleutel in `./.env` gezet, dus daarna is er niets meer te zetten.

**Controle:** het project is actief en de sleutel staat erbij.

```sh
zad config list -o json | jq -e '
  (.effective[] | select(.setting=="project") | .value) as $p
  | (.effective[] | select(.setting=="api_key") | .value) as $k
  | ($p | length > 0) and ($k != "(none)")'
```

## 3. Uitrollen uitzetten

Alles wat nu volgt wordt opgeslagen zonder het cluster aan te raken. Aan het eind rollen we
in één keer uit. Dat is niet alleen sneller: het test ook of de API de wijzigingen
opstapelt en of één refresh ze allemaal verwerkt.

```sh
zad config set rollout false
```

**Controle:**

```sh
zad config list -o json | jq -e '.effective[] | select(.setting=="rollout") | .value == "false"'
```

## 4. De drie componenten

Los gedefinieerd, zonder image: een component zonder deployment is een geldige toestand, en
de image hoort bij de koppeling.

```sh
zad component add web    --port 8080 --path /
zad component add api    --port 8080 --path /api
zad component add worker
```

**Controle:** er zijn er drie, en ze dragen nog geen image.

```sh
zad project describe --part components -o json \
  | jq -e '[.components[].name] | sort == ["api","web","worker"]'
```

## 5. Diensten op projectniveau

PostgreSQL, Redis en MinIO gelden voor het hele project. Let op de laagkeuze: `minio-storage`
accepteert er twee, dus `--target` is daar verplicht.

```sh
zad service config set postgresql-database --set scope=shared
zad service config set redis --set acl-key-prefix=true
zad service config set minio-storage --target project
```

**Controle:** alle drie staan er, op de projectlaag.

```sh
zad project describe --part services -o json | jq -e '
  [.services[] | select(.name | IN("postgresql-database","redis","minio-storage")) | .name]
  | sort == ["minio-storage","postgresql-database","redis"]'
```

### Een extra databaseschema

```sh
zad db schema add rapportage
zad db schema list      # de vorm hiervan is nog niet geverifieerd; noteer wat je ziet
```

De testimage controleert elk extra schema apart, dus dit komt straks terug in `/status`.

## 6. Diensten per component

Hier lopen de drie uit elkaar. Dit is het deel dat een generieke setter niet kan testen.

`publish-on-web` accepteert twee lagen (`component` en `deployment`), dus `--target` is daar
verplicht — `--component` alleen zegt wél welk component, niet welke laag.

```sh
zad service config set publish-on-web --target component --component web --set tls=standard
zad service config set publish-on-web --target component --component api --set tls=standard
zad service config set health-check        --component web
zad service config set metrics-scraper     --component worker
```

`persistent-storage` en `temp-storage` zijn geen dienst die je alleen aanzet: hun
configuratie is een lijst volumes. `--generate-skeleton` laat de vorm zien.

```sh
printf -- "- name: data\n  size: 1Gi\n  mount-path: /data\n"     > /tmp/vol-api.yaml
printf -- "- name: tmp\n  size: 1Gi\n  mount-path: /scratch\n"   > /tmp/vol-worker.yaml

zad service config set persistent-storage --target component --component api    -f /tmp/vol-api.yaml
zad service config set temp-storage       --target component --component worker -f /tmp/vol-worker.yaml
```

**Controle:** publish-on-web staat op twee componenten en niet op de derde.

```sh
zad project describe --part services -o json | jq -e '
  [.services[] | select(.name=="publish-on-web") | .usages[] | select(.target=="component") | .component]
  | sort == ["api","web"]'
```

## 7. Omgevingsvariabelen

Toevoegen, wijzigen, overschrijven op deploymentniveau, en weghalen. `add` maakt aan en
faalt op een bestaande sleutel; `set` wijzigt en faalt op een onbekende. Dat onderscheid is
het punt van deze stap.

```sh
zad env add -c web APP_MODE=production LOG_LEVEL=info EXTRA=weg
zad project describe --part components -o json | jq -e '
  [.components[] | select(.name=="web") | .env_var_names[]?] | sort == ["APP_MODE","EXTRA","LOG_LEVEL"]'
```

Wijzigen van een bestaande:

```sh
zad env set -c web LOG_LEVEL=debug
zad env list -c web        # de waarden zijn versleuteld opgeslagen; alleen namen komen terug
```

Een sleutel die er niet is, is een fout en geen stille aanmaak:

```sh
! zad env set -c web BESTAAT_NIET=x 2>/dev/null
```

Er weer een weghalen:

```sh
zad env unset -c web EXTRA
zad project describe --part components -o json | jq -e '
  [.components[] | select(.name=="web") | .env_var_names[]?] | index("EXTRA") == null'
```

## 8. Aliassen

Een alias koppelt een platformvariabele aan de naam die de applicatie verwacht. Een
onbekende verwijzing is hier een **harde fout**, anders dan bij een eigen variabele: dat is
het verschil dat deze stap uitoefent.

```sh
zad alias add -c web POSTGRES_HOST='$DATABASE_SERVER_HOST' POSTGRES_DB='$DATABASE_DB'
zad project describe --part components -o json | jq -e '
  [.components[] | select(.name=="web") | .aliases | keys[]] | sort == ["POSTGRES_DB","POSTGRES_HOST"]'
```

Overschrijven met een andere bron. De API maskeert aliaswaarden als `***`, dus waar hij heen
wijst is van buitenaf niet te zien; de controle kan alleen op aanwezigheid toetsen.

```sh
zad alias set -c web POSTGRES_HOST='$DATABASE_SERVER_HOST'
zad project describe --part components -o json | jq -e '
  [.components[] | select(.name=="web") | .aliases | has("POSTGRES_HOST")] | .[0]'
```

En een verwijzing naar iets dat niet bestaat, hoort te falen:

```sh
! zad alias add -c web KAPOT='$BESTAAT_ECHT_NIET' 2>/dev/null
```

Opruimen van één alias:

```sh
zad alias unset -c web POSTGRES_DB
zad project describe --part components -o json | jq -e '
  [.components[] | select(.name=="web") | .aliases | keys] | .[0] == ["POSTGRES_HOST"]'
```

## 9. Bijlagen

De catalogus en de koppeling zijn twee dingen: een bestand kan in het project staan zonder
dat iets het gebruikt, en hetzelfde bestand kan bij twee componenten op een ander pad landen.

```sh
echo "eerste inhoud" > /tmp/playbook-config.yaml
zad attachment add app-config --from-file /tmp/playbook-config.yaml
zad attachment list -o json | jq -e '
  [.configurations[].config.data[]?.id] | any(. == "app-config")'
```

Koppelen aan een component, als bestand:

```sh
zad attachment assign app-config web --provide-as file --mount-path /etc/app/config.yaml
```

Hetzelfde bestand bij een ander component, als omgevingsvariabele. Dat is de reden dat het
pad bij de koppeling hoort en niet bij het bestand:

```sh
zad attachment assign app-config api --provide-as env-var --env-name APP_CONFIG
```

**Controle:** één catalogusitem, twee koppelingen, elk met hun eigen vorm.

```sh
zad project describe --part components -o json | jq -e '
  [.components[] | select(.name | IN("web","api")) | .attachments[] | .reference]
  | sort == ["app-config","app-config"]'
```

De inhoud vervangen; de koppelingen blijven staan:

```sh
echo "tweede inhoud" > /tmp/playbook-config.yaml
zad attachment update app-config --from-file /tmp/playbook-config.yaml
zad project describe --part components -o json | jq -e '
  [.components[].attachments[]?] | length == 2'
```

## 10. Wat staat er te wachten

Alles hierboven is opgeslagen zonder uitrol. Dat hoort zichtbaar te zijn.

```sh
zad project pending -o json | jq -e '.count > 0'
```

## 11. De deployment, en uitrollen

Nu pas krijgen de componenten een image, en nu pas raakt het het cluster.

```sh
zad deployment create productie \
  --component web --image $IMG

zad component assign api    productie --image $IMG
zad component assign worker productie --image $IMG
```

**Controle:** drie componenten in de deployment.

```sh
zad deployment describe productie -o json | jq -e '[.components[].name] | length == 3'
```

Uitrollen in één keer:

```sh
zad project refresh
zad project pending -o json | jq -e '.count == 0'
```

## 12. Wachten tot het draait

De uitrol is asynchroon; de status komt van ArgoCD.

```sh
for i in $(seq 1 60); do
  STATUS=$(zad deployment describe productie -o json | jq -r .status)
  echo "  $i: $STATUS"
  [ "$STATUS" = "Healthy" ] && break
  sleep 10
done
zad project status
```

**Controle:** gezond, en er staat een revisie bij.

```sh
zad deployment describe productie -o json | jq -e '.status == "Healthy" and (.sync_revision | length > 0)'
```

## 13. Het echte bewijs

Tot hier heeft alleen de CLI iets beweerd. Nu vragen we het aan de applicatie zelf.

```sh
URL=$(zad deployment describe productie -o json | jq -r '.urls.web')
echo "$URL"
curl -sS "$URL/status" | jq
```

**Controle:** elke gebonden dienst verifieert. `?strict=1` geeft 503 zolang dat niet zo is,
dus dit faalt vanzelf als bijvoorbeeld de databasebinding niet klopt.

```sh
curl -sSf "$URL/status?strict=1" > /dev/null
```

Per dienst nakijken wat hij gedaan heeft:

```sh
curl -sS "$URL/status" | jq -e '.all_ok == true'
curl -sS "$URL/status" | jq '.services | to_entries[] | {(.key): .value.ok}'
```

Het `api`-component heeft andere bindingen, dus dat is een tweede antwoord en geen herhaling:

```sh
API_URL=$(zad deployment describe productie -o json | jq -r '.urls.api')
curl -sSf "$API_URL/status?strict=1" > /dev/null
```

## 14. Opruimen

Draai dit ook als er hierboven iets faalde. Wat blijft staan, staat de volgende run in de weg.

```sh
zad deployment delete productie
zad project delete "$(zad config get project)"
rm -f /tmp/playbook-config.yaml
```

**Controle:** het project is weg.

```sh
! zad project status 2>/dev/null
```

---

## Wat dit playbook niet dekt

Bewust, zodat het niet doet alsof:

- **De diensten die geen configuratie dragen** (`aliases`, `platform`, `deployment-health`,
  `resource-tuning`, `user-env-vars` als dienst): die draait het platform zelf.
- **`invite`, `keycloak`, `authorization-wall`, `cross-domain-access`, `sleep-mode`,
  `namespace-*`**: die horen in playbook 02, per laag.
- **Backup, restore en clone**: playbook 04.
- **De waardenlaag `deployment-component`**: env-vars die alleen in één deployment gelden.
  Playbook 03, want dat vraagt twee deployments om het verschil te kunnen zien.
