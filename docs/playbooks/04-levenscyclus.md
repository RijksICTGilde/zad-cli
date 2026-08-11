# Playbook 04: de levenscyclus

Wat er met een project gebeurt nádat het draait: de image bijwerken, data klonen naar een
tweede deployment, een backup maken en terugzetten, componenten wijzigen en verwijderen, en
uiteindelijk het project opruimen.

Dit playbook hangt het sterkst van een werkende uitrol af. Het begint daarom met een
verkorte versie van playbook 01 — twee componenten, een deployment, uitgerold en gezond —
en alles daarna bouwt daarop voort. Strandt stap 2, dan is de rest niet te draaien; markeer
dat dan als zodanig in plaats van de stappen over te slaan alsof ze niet bestonden.

De testimage schrijft bij het opstarten in elke gebonden dienst en leest terug, dus na een
kloon of een restore is `/status` het bewijs dat de data er daadwerkelijk is.

---

## 0. Opzet

```sh
cd $(mktemp -d)
SUFFIX=$(date +%H%M%S)
IMG=ghcr.io/minbzk/base-images/e2e-allservices:latest

cat > .env <<EOF
ZAD_API_URL=https://zad.sandbox.rijksapp.dev/api
ZAD_KEYCLOAK_URL=https://keycloak.sandbox.rijksapp.dev
ZAD_KEYCLOAK_REALM=operations-manager
ZAD_KEYCLOAK_CLIENT_ID=zad-cli
ZAD_YES=true
EOF
```

```sh
zad config list -o json | jq -e '.effective[] | select(.setting=="api_url") | .value | test("sandbox")'
```

## 1. Inloggen en een project

```sh
zad login          # of: uv run --with playwright python docs/playbooks/login-headless.py --zad "$ZAD"
zad project create "Cyclus $SUFFIX" --description "E2E playbook 04" --use
for i in $(seq 1 30); do zad project status >/dev/null 2>&1 && break; sleep 2; done
```

## 2. Een draaiend vertrekpunt

Twee componenten, met de projectdiensten eraan gebonden — zonder die binding krijgt de
workload geen credentials en bewijst `/status` niets (zie playbook 01).

```sh
zad component add web    --port 8080 --path / \
  --service publish-on-web --service postgresql-database --service redis --service minio-storage
zad component add bijzaak --port 8080 --service publish-on-web

zad service config set postgresql-database --set scope=shared
zad service config set redis --set acl-key-prefix=true
zad service config set minio-storage --target project
zad service config set publish-on-web --target component --component web     --set tls=standard
zad service config set publish-on-web --target component --component bijzaak --set tls=standard

zad deployment create productie --component web --image $IMG
zad component assign bijzaak productie --image $IMG
zad project refresh
```

**Controle:** het draait, en de workload bereikt zijn diensten. Alles hierna is zinloos als
deze stap niet slaagt.

```sh
for i in $(seq 1 40); do
  [ "$(zad deployment describe productie -o json | jq -r .status)" = "Healthy" ] && break
  sleep 10
done
zad deployment describe productie -o json | jq -e '.status == "Healthy"'

URL=$(zad deployment describe productie -o json | jq -r '.urls.web')
for i in $(seq 1 30); do curl -sSf "$URL/status?strict=1" >/dev/null 2>&1 && break; sleep 10; done
curl -sS "$URL/status" | jq -e '
  [.services | to_entries[] | select(.value.bound) | select(.value.ok == true) | .key]
  | index("postgres") != null and index("minio") != null'
```

## 3. `deployment update-image`

Eén veld wijzigen, zonder de rest van de deployment aan te raken.

```sh
zad deployment update-image productie --component web --image "$IMG"
```

**Controle:** de image staat erop en de deployment komt terug op gezond.

```sh
zad deployment describe productie -o json | jq -e '
  [.components[] | select(.name=="web") | .image] | .[0] | test("e2e-allservices")'
```

Een component dat niet in de deployment zit, hoort een fout te zijn en geen stille toevoeging:

```sh
! zad deployment update-image productie --component bestaat-niet --image "$IMG" 2>/dev/null
```

## 4. Een tweede deployment, en klonen

Klonen kopieert data van de ene deployment naar de andere. Daarvoor moeten er twee zijn.

```sh
zad deployment create acceptatie --component web --image $IMG
zad project refresh
for i in $(seq 1 40); do
  [ "$(zad deployment describe acceptatie -o json | jq -r .status)" = "Healthy" ] && break
  sleep 10
done
```

**Eerst controleren zonder iets te doen.** `clone check` is read-only en zegt of de
configuratie klopt; dat is de goedkoopste manier om een verkeerde kloon te voorkomen.

```sh
zad clone check --from productie --to acceptatie
```

Dan de database en de bucket:

```sh
zad clone database --from productie --to acceptatie
zad clone bucket   --from productie --to acceptatie
```

**Controle:** de doeldeployment draait nog steeds en bereikt zijn diensten na de kloon.

```sh
ACC=$(zad deployment describe acceptatie -o json | jq -r '.urls.web')
for i in $(seq 1 30); do curl -sSf "$ACC/status?strict=1" >/dev/null 2>&1 && break; sleep 10; done
curl -sSf "$ACC/status?strict=1" > /dev/null
```

## 5. Backup

```sh
zad backup create productie
zad backup list -o json | jq -e 'length > 0'
```

**Controle:** de backup is er en heeft een status.

```sh
zad backup list -o json | jq -e '.[0] | has("status") or has("id") or has("name")'
```

Per onderdeel is er ook een backup: de namespace, de database en de bucket.

```sh
zad backup namespace productie
zad backup database  productie
zad backup bucket    productie
```

## 6. Restore

Terugzetten in de acceptatie-deployment, zodat productie niet het proefkonijn is.

```sh
zad restore list -o json | jq -e 'type == "array" or type == "object"'
zad restore database --from productie --to acceptatie
zad restore bucket   --from productie --to acceptatie
```

**Controle:** acceptatie draait en verifieert zijn diensten na de restore.

```sh
for i in $(seq 1 30); do curl -sSf "$ACC/status?strict=1" >/dev/null 2>&1 && break; sleep 10; done
curl -sSf "$ACC/status?strict=1" > /dev/null
```

## 7. `component update` en `component delete`

Wijzigen is een gedeeltelijke update: alleen wat je noemt verandert.

```sh
zad component update bijzaak --memory-limit 512Mi
zad project describe --part components -o json | jq -e '
  [.components[] | select(.name=="bijzaak")] | length == 1'
```

Let op: `--service` **vervangt** de lijst en voegt niet toe. Dat is een van de manieren
waarop een component stilletjes zijn bindingen kwijtraakt:

```sh
zad component update bijzaak --service publish-on-web
zad project describe --part components -o json | jq -e '
  [.components[] | select(.name=="bijzaak") | .services] | .[0] == ["publish-on-web"]'
```

Verwijderen:

```sh
zad component delete bijzaak
zad project describe --part components -o json | jq -e '
  [.components[].name] | index("bijzaak") == null'
```

**Controle:** de deployment draait door met wat er over is.

```sh
zad project refresh
zad deployment describe productie -o json | jq -e '[.components[].name] == ["web"]'
```

## 8. `deployment delete`

Een deployment weghalen laat het project staan.

```sh
zad deployment delete acceptatie
zad deployment list -o json | jq -e '[.[].name] == ["productie"]'
```

En een deployment die niet bestaat is geen succes:

```sh
! zad deployment delete bestaat-echt-niet 2>/dev/null
zad deployment delete bestaat-echt-niet --ignore-not-found
```

## 9. `project delete`

```sh
zad project delete "$(zad config get project)"
```

**Controle:**

```sh
! zad project status 2>/dev/null
```

---

## Wat dit playbook niet dekt

- **Of een restore de juiste inhoud terugzet.** `/status` bewijst dat de dienst bereikbaar
  is en beschrijfbaar, niet dat er precies de rijen in staan die er voor de backup stonden.
  Daarvoor zou de testimage een gemarkeerde rij moeten schrijven en terugzoeken.
- **Diensten per laag**: playbook 02. **Waarden**: playbook 03.
