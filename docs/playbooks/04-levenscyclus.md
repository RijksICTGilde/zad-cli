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
uv run --with playwright python "$PLAYBOOKS/login-headless.py" --zad "$(command -v zad)"
zad project create "Cyclus $SUFFIX" --description "E2E playbook 04" --use
```

## 2. Een draaiend vertrekpunt

Twee componenten, met de projectdiensten eraan gebonden — zonder die binding krijgt de
workload geen credentials en bewijst `/status` niets (zie playbook 01). De projectdiensten
gaan eerst: `--service` mag alleen noemen wat het project al heeft.

```sh
zad service config set postgresql-database --set scope=shared
zad service config set redis --set acl-key-prefix=true
zad service config set minio-storage --target project

zad component add web     --port 8080 --path / \
  --service postgresql-database --service redis --service minio-storage
zad component add bijzaak --port 8080

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

**Klonen gaat niet van deployment naar deployment.** `zad clone database` en `zad clone
bucket` halen data uit een **externe** bron — een host, een databasenaam en inloggegevens —
en zetten die in één deployment. Er is dus geen `--from`/`--to`; het doel is het positionele
argument en de bron staat in de opties. Dat is een andere operatie dan "kopieer acceptatie
naar productie", en het playbook zei dat eerst verkeerd.

```sh
zad deployment create acceptatie --component web --image $IMG
zad project refresh
for i in $(seq 1 40); do
  [ "$(zad deployment describe acceptatie -o json | jq -r .status)" = "Healthy" ] && break
  sleep 10
done
```

**Eerst controleren zonder iets te doen.** `clone check` is read-only en neemt de
deployment als positioneel argument.

`acceptatie` heeft geen kloonconfiguratie, dus hier hoort hij te **weigeren** met een 422
die zegt waarom — en niet met een interne fout, wat hij tot 12 augustus deed. De controle
eist allebei: dat hij faalt, en dat de reden erin staat.

```sh
UIT=$(zad clone check acceptatie 2>&1) && exit 1
echo "$UIT" | grep -q "no clone-from configuration"
```

Dan de kloon zelf. Zonder een echte bronhost is dit alleen als `--dry-run` te draaien; het
verzoek dat eruit komt is wél te controleren, en dat is meer dan niets:

```sh
zad clone database acceptatie \
  --host db.example.org --dbname bron --username u --password p --dry-run -o json \
  | jq -e '.endpoint | test(":clone-database")'
```

**Controle:** de doeldeployment draait nog steeds.

```sh
ACC=$(zad deployment describe acceptatie -o json | jq -r '.urls.web')
curl -sSf "$ACC/status?strict=1" > /dev/null
```

## 5. Backup

```sh
zad backup create productie
zad backup list productie -o json | jq -e '.runs | length > 0'
```

`backup list` neemt de deployment als argument en antwoordt met de cluster, de namespace en
de runs. Daaruit komen ook de namen die je verderop nodig hebt:

```sh
zad backup list productie -o json | jq -c '[.runs[].items[] | {resource_type, reference_name}] | unique'
# [{"resource_type":"database","reference_name":"backup"},
#  {"resource_type":"bucket","reference_name":"bucket-backup"}]

CLUSTER=$(zad backup list productie -o json | jq -r .cluster)      # sandboxed-local
NS=$(zad backup list productie -o json | jq -r .namespace)         # rig-<project>
```

**Controle:** er staat minstens één run met items in.

```sh
zad backup list productie -o json | jq -e '[.runs[].items[]] | length > 0'
```

## 6. Restore

Terugzetten in de acceptatie-deployment, zodat productie niet het proefkonijn is.

`restore list` neemt een cluster en een **namespace** — niet de projectnaam, maar de
namespace met `rig-` ervoor, precies zoals `backup list` hem teruggeeft:

```sh
zad restore list "$CLUSTER" "$NS" -o json | jq -e 'type == "array"'
```

`restore database` en `restore bucket` nemen de deployment, een referentienaam **en het
doel waar de momentopname naartoe geschreven wordt**. De API vereist die vier doelvelden;
er wordt niets afgeleid uit de deployment, en dat is maar goed ook: een restore die zelf
zijn bestemming kiest is een restore waar je achteraf achter komt.

```sh skip: de doelcredentials beheert het platform en geeft het nergens terug (vraag 7)
zad restore database productie backup \
  --target-host "$DB_HOST" --target-dbname "$DB_NAME" \
  --target-username "$DB_USER" --target-password "$DB_PASSWORD"

zad restore bucket productie bucket-backup \
  --target-endpoint "$MINIO_ENDPOINT" --target-bucket "$BUCKET" \
  --target-access-key "$MINIO_KEY" --target-secret-key "$MINIO_SECRET"
```

De wachtwoorden mogen ook uit de omgeving komen (`TARGET_DB_PASSWORD`,
`TARGET_S3_ACCESS_KEY`, `TARGET_S3_SECRET_KEY`), dan staan ze niet in je shellgeschiedenis.

> **Hier stokt het draaiboek, en niet door de CLI.** Die doelgegevens zijn precies de
> credentials die het platform zelf in de component injecteert, en er is geen commando dat
> ze teruggeeft. Terugzetten in je eigen projectdatabase vraagt dus om een wachtwoord dat
> je nergens kunt opvragen. Wie een eigen database buiten ZAD heeft, kan deze stap wel
> draaien. Dit staat als bevinding in `04-bevindingen.md`.

**Controle** (zodra de stap te draaien is): de deployment draait en verifieert zijn
diensten na de restore.

```sh
curl -sSf "$URL/status?strict=1" > /dev/null
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

Verwijderen, en dit is een paar in plaats van één stap. Een component dat nog in een
deployment zit hoort **geweigerd** te worden, met de lijst erbij van wat het gebruikt:

```sh
! zad component delete bijzaak 2>/dev/null      # 409, en noemt deployment 'productie'
```

Pas met `--force` gaat hij weg, inclusief de verwijzingen ernaartoe. Beide kanten testen is
het punt: een weigering die niet komt is net zo fout als een verwijdering die niet lukt.

```sh
zad component delete bijzaak --force
zad project describe --part components -o json | jq -e '
  [.components[].name] | index("bijzaak") == null'
zad deployment describe productie -o json | jq -e '[.components[].name] == ["web"]'
```

Een component waar het webadres van een deployment omheen gebouwd is (het root-component)
wordt ook met `--force` geweigerd; verander dat adres dan eerst.

**Controle:** wat er over is rolt door, en de verwijdering is niet alleen in het
projectbestand blijven staan.

```sh
zad project refresh
curl -sSf "$(zad deployment describe productie -o json | jq -r '.urls.web')/status" > /dev/null
```

## 7b. Twee refreshes over elkaar heen

Wat er gebeurt als je iets wijzigt terwijl een uitrol nog loopt. Dit is de stap die de
volgorde van het platform test in plaats van één commando.

```sh
zad component add laatkomer --port 8080 --path / --no-rollout
zad service config set publish-on-web --target component --component laatkomer \
  --set tls=standard --no-rollout

TA=$(zad --no-wait project refresh -o json | jq -r '.task_id')   # start, wacht niet
zad component assign laatkomer productie --image $IMG --no-rollout   # tijdens die taak
TB=$(zad --no-wait project refresh -o json | jq -r '.task_id')
```

**Controle:** de tweede refresh start geen tweede taak, hij levert dezelfde op.

```sh
test "$TA" = "$TB"
```

**En de controle die er echt toe doet:** de wijziging van ná de start is toch meegenomen.
Zonder deze regel bewijst het bovenstaande alleen dat er niets dubbel draaide, niet dat er
niets is zoekgeraakt.

```sh
for i in $(seq 1 40); do
  [ "$(zad task status "$TA" -o json | jq -r .status)" = "completed" ] && break; sleep 10
done
zad project pending -o json | jq -e '.count == 0'
zad deployment describe productie -o json | jq -e '[.components[].name] | index("laatkomer") != null'

LAAT=$(zad deployment describe productie -o json | jq -r '.urls.laatkomer')
for i in $(seq 1 30); do
  [ "$(curl -sS -o /dev/null -m 10 -w '%{http_code}' "$LAAT/status")" = "200" ] && break
  sleep 10
done
curl -sSf "$LAAT/status" > /dev/null
```

## 8. `deployment delete`

Een deployment weghalen laat het project staan.

```sh
zad deployment delete acceptatie
zad deployment list -o json | jq -e '[.[].deployment] == ["productie"]'
```

En een deployment die niet bestaat is geen succes:

```sh
! zad deployment delete bestaat-echt-niet 2>/dev/null
zad deployment delete bestaat-echt-niet --ignore-not-found
```

## 9. `project delete`

```sh
zad project delete            # zonder naam: het actieve project, uit -p / ZAD_PROJECT_ID
```

**Controle:** het project is weg, en de `.env` wijst er niet meer naar. Dat tweede is geen
netheid: een achtergebleven sleutel van een verwijderd project maakt van elk volgend
commando een authenticatiefout, terwijl er niets mis is met je inloggegevens.

```sh
! zad project status 2>/dev/null
! grep -q '^ZAD_PROJECT_ID=' .env
zad project list -o json | jq -e 'type == "array"'    # nog steeds ingelogd
```

---

## Wat dit playbook niet dekt

- **Of een restore de juiste inhoud terugzet.** `/status` bewijst dat de dienst bereikbaar
  is en beschrijfbaar, niet dat er precies de rijen in staan die er voor de backup stonden.
  Daarvoor zou de testimage een gemarkeerde rij moeten schrijven en terugzoeken.
- **Diensten per laag**: playbook 02. **Waarden**: playbook 03.
