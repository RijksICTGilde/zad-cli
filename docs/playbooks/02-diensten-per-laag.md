# Playbook 02: elke instelbare dienst, op elke laag die hij accepteert

Playbook 01 zet zes diensten aan omdat het er een project mee bouwt. Dit playbook gaat de
andere kant op: het loopt de **registry** af en oefent elke instelbare dienst uit op elke
laag die hij zegt te accepteren, plus `config get` en `config clear` — niet alleen `set`.

**De lagen komen uit `zadctl service list -o json`, niet uit dit bestand.** Dat is geen
netheid maar noodzaak: toen `publish-on-web` er een laag bij kreeg, was het playbook dat de
lagen had opgeschreven meteen fout, en de fout zag eruit als een CLI-bug. Wat hier hard
staat, is alleen wat níet af te leiden is: welke waarde geldig is voor een veld.

De diensten die playbook 01 oversloeg horen hier thuis: `invite`, `keycloak`,
`authorization-wall`, `cross-domain-access`, `sleep-mode`, `namespace-*`, `health-check` en
`metrics-scraper`.

---

## 0. Opzet

```sh
SUFFIX=$(date +%H%M%S)

cat > .env.zadctl <<EOF
ZAD_API_URL=https://zad.sandbox.rijksapp.dev/api
ZAD_KEYCLOAK_URL=https://keycloak.sandbox.rijksapp.dev
ZAD_KEYCLOAK_REALM=operations-manager
ZAD_KEYCLOAK_CLIENT_ID=zad-cli
ZAD_YES=true
EOF
```

**Controle:**

```sh
zadctl config list -o json | jq -e '.effective[] | select(.setting=="api_url") | .value | test("sandbox")'
```

## 1. Inloggen, project, componenten

```sh
uv run --with playwright python "$PLAYBOOKS/login-headless.py" --zad "$(command -v zad)"
zadctl project create "Diensten $SUFFIX" --description "E2E playbook 02" --use
zadctl config set rollout false

zadctl component add web --port 8080 --path /
zadctl component add api --port 8080
```

**Controle:**

```sh
zadctl project describe --part components -o json | jq -e '[.components[].name] | sort == ["api","web"]'
```

## 2. De registry is de lijst

Wat er te configureren valt, en op welke laag, staat in de catalogus. Dit is de bron voor
alles hieronder.

```sh
zadctl service list -o json | jq -r '.[] | select(.configurable) | "\(.name)\t\(.targets|join(","))"'
```

**Controle:** de catalogus noemt zichzelf, en elke instelbare dienst heeft minstens één laag.

```sh
zadctl service list -o json | jq -e '
  [.[] | select(.configurable)] | length > 0
  and ([.[] | select(.configurable) | select((.targets|length) == 0)] | length == 0)'
```

## 3. Elke dienst op elke laag die hij accepteert

Deze lus is de kern van het playbook. Voor elke instelbare dienst en elke laag die de
registry noemt, moet de CLI die combinatie **accepteren**. Dat wordt gevraagd met
`--generate-skeleton`: die neemt een laag en geen lichaam, en drukt de vorm van díe laag af.
Daarmee is het een zuivere laagproef — een `--set veld=waarde` zou stranden op de
schemacontrole van het veld, en dan meet je het veld in plaats van de laag.

```sh
zadctl service list -o json \
  | jq -r '.[] | select(.configurable) | . as $s | $s.targets[] | "\($s.name) \(.)"' \
  | while read -r SVC LAYER; do
      case "$LAYER" in
        project)    ARGS="" ;;
        component)  ARGS="--component web" ;;
        deployment) ARGS="--deployment productie" ;;
      esac
      zadctl service config set "$SVC" --target "$LAYER" $ARGS --generate-skeleton >/dev/null 2>&1 \
        || echo "FAIL $SVC/$LAYER"
    done
```

**Controle:** de lus hierboven print niets. Elke regel is een dienst-laagcombinatie die de
registry belooft en de CLI niet waarmaakt.

En de andere kant op: een laag die de registry *niet* noemt, hoort geweigerd te worden. Een
CLI die alles accepteert, test niets.

```sh
! zadctl service config set health-check --target project --generate-skeleton 2>/dev/null
! zadctl service config set postgresql-database --target component --component web --generate-skeleton 2>/dev/null
```

## 4. De diensten die playbook 01 oversloeg

Nu echt schrijven. Per dienst: `set`, dan `get` om te zien dat het er staat, later `clear`.
De vorm van elk lichaam komt uit `--generate-skeleton`, niet uit giswerk:

```sh
zadctl service config set keycloak --target project --generate-skeleton
```

### Diensten op projectniveau

```sh
zadctl service config set invite             --target project --set default-language=nl
zadctl service config set authorization-wall --target project --set banner='Alleen voor medewerkers'
zadctl service config set sleep-mode         --target project --set enabled=false
```

**Controle:** alle drie staan er, op de projectlaag.

```sh
for SVC in invite authorization-wall sleep-mode; do
  zadctl service config get $SVC -o json | jq -e --arg s "$SVC" '
    .service == $s and ([.configurations[] | select(.target=="project")] | length == 1)'
done
```

`authorization-wall` zegt in de registry dat hij `publish-on-web` nodig heeft. Dat is een
eigenschap van de dienst, dus die lees je uit de catalogus in plaats van hem te onthouden:

```sh
zadctl service list -o json | jq -e '
  [.[] | select(.name=="authorization-wall") | .requires[]?] | any(test("publish-on-web"))'
```

### Diensten op componentniveau

```sh
zadctl service config set health-check    --component web
zadctl service config set metrics-scraper --component api
```

**Controle:** ze staan op het component dat genoemd is, en niet op het andere.

```sh
zadctl service config get health-check -o json | jq -e '
  [.configurations[] | select(.target=="component") | .component] == ["web"]'
```

### Een dienst met twee lagen

`cross-domain-access` accepteert `project` en `deployment`. De laag is daar dus verplicht —
dat is precies waar playbook 01 op struikelde toen `publish-on-web` er een laag bij kreeg.

**Controle:** hij weigert, én de melding noemt de lagen die er wél zijn. Allebei, want een
weigering zonder uitleg stuurt je naar `--help` en een uitleg zonder weigering betekent dat
er zojuist naar een gegokte laag is geschreven.

```sh
UIT=$(zadctl service config set cross-domain-access --set x=y --dry-run 2>&1) && exit 1
echo "$UIT" | grep -q -- "--target"
echo "$UIT" | grep -q "project" && echo "$UIT" | grep -q "deployment"
```

## 5. `config get`: alle lagen in één antwoord

`get` is niet per laag: het toont een dienst zoals hij over alle lagen heen is ingesteld.
Dat is wat je wilt weten als je je afvraagt "waar staat dit eigenlijk aan".

```sh
zadctl service config get publish-on-web -o json
```

**Controle:** de vorm is `{service, configurations: [{target, component?, config}]}`.

```sh
zadctl service config get health-check -o json | jq -e '
  has("service") and (.configurations | type == "array")'
```

## 6. `config clear`: één laag weg, de rest blijft

Wissen is per laag, net als schrijven. Dat is te toetsen door twee lagen te vullen en er één
weg te halen.

```sh
zadctl service config set publish-on-web --target component --component web --set tls=standard
zadctl service config set publish-on-web --target component --component api  --set tls=standard
zadctl service config get publish-on-web -o json | jq -e '[.configurations[]] | length == 2'

zadctl service config clear publish-on-web --target component --component api
zadctl service config get publish-on-web -o json | jq -e '
  [.configurations[] | .component] == ["web"]'
```

En een dienst helemaal uitzetten:

```sh
zadctl service config clear health-check --component web
zadctl service config get health-check -o json | jq -e '[.configurations[]] | length == 0'
```

## 7. Verborgen diensten

`zadctl service list` laat de interne varianten weg; `--all` toont ze. Ze horen niet in een
playbook thuis om aan te zetten, maar wel om te controleren dat de CLI ze niet verzint.

```sh
zadctl service list --all -o json | jq -e '[.[] | select(.hidden)] | length > 0'
zadctl service list -o json      | jq -e '[.[] | select(.hidden)] | length == 0'
```

## 8. Opruimen

```sh
zadctl project delete            # zonder naam: het actieve project, uit -p / ZAD_PROJECT_ID
! zadctl project status 2>/dev/null
```

---

## Wat dit playbook niet dekt

- **Of een dienst ook werkt** als hij aanstaat. Dit playbook toetst de configuratielaag;
  playbook 01 bewijst met `/status` dat een gebonden dienst de workload bereikt.
- **`keycloak` met echte realms**: die configuratie vraagt een host, een realm en
  inloggegevens van een Keycloak die niet van dit project is.
- **Waarden** (env-vars, aliassen, bijlagen): playbook 03.
