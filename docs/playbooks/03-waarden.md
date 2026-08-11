# Playbook 03: waarden

Env-vars, aliassen en bijlagen, en dan de hele matrix: toevoegen, wijzigen, overschrijven,
één weghalen, alles wissen. Op **beide lagen**, dus ook `deployment-component`.

Waar playbook 01 langs de waarden loopt om iets op te bouwen, is dit het playbook dat de
waardenlaag zelf uitoefent. Drie dingen maken het verschil met 01:

1. **Twee deployments.** Een waarde die alleen in één deployment geldt en de componentbrede
   waarde overschrijft, is niet te zien met één deployment: dan is er niets om tegen af te
   zetten.
2. **`add` en `set` zijn niet hetzelfde.** `add` is een POST die op een bestaande sleutel
   hoort te weigeren, `set` een PATCH die op een onbekende hoort te weigeren. Twee
   endpoints, twee betekenissen; dit playbook toetst beide kanten, ook de kant die faalt.
3. **Lezen en maskeren zijn twee vragen.** Een env-var is versleuteld opgeslagen en komt als
   `***` terug; een alias is een *verwijzing* en komt terug zoals hij is opgeslagen. De
   controles hieronder gaan daarom bij env-vars over namen en bij aliassen over de
   verwijzing zelf.

Bijlagen zitten erbij omdat dezelfde bijlage bij het ene component een bestand is en bij het
andere een omgevingsvariabele — het pad hoort bij de koppeling, niet bij het bestand.

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

**Controle:** de CLI praat met de sandbox en niet met productie.

```sh
zad config list -o json | jq -e '.effective[] | select(.setting=="api_url") | .value | test("sandbox")'
```

## 1. Inloggen en een project

```sh
zad login          # of: uv run --with playwright python docs/playbooks/login-headless.py --zad "$ZAD"
zad project create "Waarden $SUFFIX" --description "E2E playbook 03" --use
zad config set rollout false
```

**Controle:** er is een actief project, en er wordt niet uitgerold.

```sh
zad config list -o json | jq -e '
  ((.effective[] | select(.setting=="project") | .value) | length > 0)
  and ((.effective[] | select(.setting=="rollout") | .value) == "false")'
```

## 2. Twee componenten

```sh
zad component add web    --port 8080 --path /
zad component add worker
```

**Controle:**

```sh
zad project describe --part components -o json | jq -e '[.components[].name] | sort == ["web","worker"]'
```

## 3. Toevoegen: `add` maakt aan

```sh
zad env add -c web APP_MODE=production LOG_LEVEL=info EXTRA=weg
```

**Controle:** alle drie staan er. De waarden zijn geheim en komen als `(set, not shown)`
terug, dus de controle gaat over de namen — dat is precies wat er te weten valt.

```sh
zad env list -c web -o json | jq -e 'keys == ["APP_MODE","EXTRA","LOG_LEVEL"]'
```

Dezelfde namen horen ook in de componentdefinitie te staan. Twee leeswegen die hetzelfde
zeggen is meer waard dan één die zichzelf bevestigt:

```sh
zad project describe --part components -o json | jq -e '
  [.components[] | select(.name=="web") | .env_var_names[]?] | sort == ["APP_MODE","EXTRA","LOG_LEVEL"]'
```

## 4. `add` op een bestaande sleutel is een conflict

Geen stille overschrijving: dat is het verschil met `set`.

```sh
! zad env add -c web APP_MODE=iets-anders 2>/dev/null
```

**Controle:** de oude waarde staat er nog, en er is geen sleutel bij gekomen.

```sh
zad env list -c web -o json | jq -e 'keys == ["APP_MODE","EXTRA","LOG_LEVEL"]'
```

## 5. Wijzigen: `set` wijzigt wat bestaat

```sh
zad env set -c web LOG_LEVEL=debug
```

En een sleutel die er niet is, is een fout en geen stille aanmaak:

```sh
! zad env set -c web BESTAAT_NIET=x 2>/dev/null
```

**Controle:** er is niets bijgekomen.

```sh
zad env list -c web -o json | jq -e 'has("BESTAAT_NIET") | not'
```

## 6. De tweede laag: een waarde die alleen in één deployment geldt

Hiervoor zijn twee deployments nodig. Dit is het deel dat playbook 01 uitdrukkelijk
overliet aan dit playbook.

```sh
zad deployment create acceptatie --component web --image $IMG
zad deployment create productie  --component web --image $IMG
```

**Controle:** twee deployments.

```sh
zad deployment list -o json | jq -e '[.[].deployment] | sort == ["acceptatie","productie"]'
```

De componentbrede waarde geldt overal. Nu één die alleen in `productie` geldt:

```sh
zad env add -c web --deployment productie APP_MODE=live
```

**Controle:** de deploymentlaag heeft zijn eigen antwoord, en de componentlaag is niet
veranderd. Dit is de controle waar het playbook om bestaat: één laag mag de andere niet
overschrijven.

```sh
zad env list -c web --deployment productie -o json | jq -e 'has("APP_MODE")'
zad env list -c web --deployment acceptatie -o json | jq -e 'has("APP_MODE") | not'
zad env list -c web -o json                          | jq -e 'keys | index("APP_MODE") != null'
```

Wijzigen op die laag raakt alleen die laag:

```sh
zad env set -c web --deployment productie APP_MODE=live-2
zad env list -c web --deployment productie -o json | jq -e 'keys == ["APP_MODE"]'
```

## 7. Eén weghalen, en alles wissen

Eén sleutel weg:

```sh
zad env unset -c web EXTRA
zad env list -c web -o json | jq -e 'keys == ["APP_MODE","LOG_LEVEL"]'
```

Meerdere in één keer — dat is een ander endpoint dan één:

```sh
zad env add -c worker A=1 B=2 C=3
zad env unset -c worker A B
zad env list -c worker -o json | jq -e 'keys == ["C"]'
```

Alles wissen op één laag. De andere laag hoort daar niet in mee te gaan:

```sh
zad env clear -c web --deployment productie
zad env list -c web --deployment productie -o json | jq -e 'length == 0'
zad env list -c web -o json | jq -e 'keys == ["APP_MODE","LOG_LEVEL"]'
```

En de componentlaag zelf:

```sh
zad env clear -c worker
zad env list -c worker -o json | jq -e 'length == 0'
```

## 8. Aliassen: de verwijzing is het punt

Een alias koppelt een platformvariabele aan de naam die de applicatie verwacht. Anders dan
een env-var is hij géén geheim, dus hij hoort leesbaar terug te komen: waar hij heen wijst is
precies wat een lezer controleert.

```sh
zad service config set postgresql-database --set scope=shared
zad alias add -c web POSTGRES_HOST='$DATABASE_SERVER_HOST' POSTGRES_DB='$DATABASE_DB'
```

**Controle:** de verwijzing komt terug zoals hij is opgeslagen, niet gemaskeerd.

```sh
zad alias list -c web -o json | jq -e '.POSTGRES_HOST == "$DATABASE_SERVER_HOST"'
zad alias list -c web -o json | jq -e 'keys == ["POSTGRES_DB","POSTGRES_HOST"]'
```

Overschrijven met een andere bron:

```sh
zad alias set -c web POSTGRES_HOST='$DATABASE_SERVER_PORT'
zad alias list -c web -o json | jq -e '.POSTGRES_HOST == "$DATABASE_SERVER_PORT"'
```

Een verwijzing naar iets dat niet bestaat, hoort te falen — dat is het verschil met een
eigen variabele, waar een dollarteken in een wachtwoord geen typefout is:

```sh
! zad alias add -c web KAPOT='$BESTAAT_ECHT_NIET' 2>/dev/null
zad alias list -c web -o json | jq -e 'has("KAPOT") | not'
```

Aliassen kennen maar één laag. `--deployment` hoort daarom te weigeren en niet stilletjes
op de componentlaag te schrijven:

```sh
! zad alias add -c web X='$DATABASE_DB' --deployment productie 2>/dev/null
```

Eén weg, en de rest wissen:

```sh
zad alias unset -c web POSTGRES_DB
zad alias list -c web -o json | jq -e 'keys == ["POSTGRES_HOST"]'
zad alias clear -c web
zad alias list -c web -o json | jq -e 'length == 0'
```

## 9. Bijlagen: één bestand, twee vormen

De catalogus en de koppeling zijn twee dingen. Hetzelfde bestand landt bij `web` als bestand
en bij `worker` als omgevingsvariabele; daarom hoort het pad bij de koppeling.

```sh
echo "eerste inhoud" > ./config.yaml
zad attachment add app-config --from-file ./config.yaml
zad attachment list -o json | jq -e '[.configurations[].config.data[]?.id] | any(. == "app-config")'
```

```sh
zad attachment assign app-config web    --provide-as file    --mount-path /etc/app/config.yaml
zad attachment assign app-config worker --provide-as env-var --env-name APP_CONFIG
```

**Controle:** één catalogusitem, twee koppelingen, elk met hun eigen vorm.

```sh
zad project describe --part components -o json | jq -e '
  [.components[] | .attachments[]? | .reference] | sort == ["app-config","app-config"]'
```

De inhoud vervangen; de koppelingen blijven staan:

```sh
echo "tweede inhoud" > ./config.yaml
zad attachment update app-config --from-file ./config.yaml
zad project describe --part components -o json | jq -e '[.components[].attachments[]?] | length == 2'
```

Een bijlage die nog in gebruik is, hoort niet zomaar te verdwijnen:

```sh
! zad attachment delete app-config 2>/dev/null
zad attachment delete app-config --confirm-in-use
zad attachment list -o json | jq -e '[.configurations[].config.data[]?.id] | any(. == "app-config") | not'
```

## 10. Opruimen

Draai dit ook als er hierboven iets faalde.

```sh
zad deployment delete productie
zad deployment delete acceptatie
zad project delete            # zonder naam: het actieve project, uit -p / ZAD_PROJECT_ID
```

**Controle:** het project is weg.

```sh
! zad project status 2>/dev/null
```

---

## Wat dit playbook niet dekt

- **Of de waarden ook in de container aankomen.** Alles hier is "de API bevestigt dat het is
  opgeslagen". Dat een variabele de workload bereikt, bewijst playbook 01 met `/status`.
- **De diensten per laag**: playbook 02.
- **Image bijwerken, klonen, backuppen, terugzetten**: playbook 04.
