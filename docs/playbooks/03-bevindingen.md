# Bevindingen: playbook 03 (waarden) tegen de sandbox

Afgespeeld op **11 augustus 2026, 09:35–09:45 UTC** tegen
`https://zad.sandbox.rijksapp.dev/api`, build `2e8e25fc`. Project `w0-9xs`, na afloop
verwijderd. Eerste doorloop van dit playbook.

**Uitkomst: alle 24 controles slagen.** De enige faler in de eerste doorloop zat in het
playbook zelf en is gecorrigeerd (hieronder).

---

## Per stap

| Stap | Uitkomst | Kort |
|---|---|---|
| 1. Project | **gelukt** | met wachtlus na `project create`, zie 01-bevindingen nr. 13 |
| 2. Twee componenten | **gelukt** | |
| 3. `add` maakt aan | **gelukt** | twee leeswegen zeggen hetzelfde: `env list` en `project describe` |
| 4. `add` op een bestaande sleutel | **gelukt** | wordt geweigerd, en er verandert niets |
| 5. `set` wijzigt wat bestaat | **gelukt** | onbekende sleutel wordt geweigerd |
| 6. De laag `deployment-component` | **gelukt** | de kern van dit playbook, zie hieronder |
| 7. Weghalen en wissen | **gelukt** | één, meerdere, en per laag |
| 8. Aliassen | **gelukt** | verwijzing leesbaar, onbekende verwijzing geweigerd |
| 9. Bijlagen | **gelukt** | inclusief "in gebruik, dus niet zomaar weg" |
| 10. Opruimen | **gelukt** | |

## Wat dit playbook als eerste heeft aangetoond

**De twee waardenlagen staan echt los van elkaar.** Dat was de reden om dit playbook te
schrijven, en het is nu gemeten in beide richtingen:

```sh
zad env add -c web --deployment productie APP_MODE=live

zad env list -c web --deployment productie  -o json | jq -e 'has("APP_MODE")'        # ja
zad env list -c web --deployment acceptatie -o json | jq -e 'has("APP_MODE") | not'  # niet daar
zad env list -c web                          -o json | jq -e 'keys|index("APP_MODE")!=null'  # componentbreed ongemoeid
```

En wissen respecteert de laaggrens: `zad env clear -c web --deployment productie` laat de
componentbrede waarden staan.

**`add` en `set` zijn twee endpoints met twee betekenissen**, en allebei weigeren de kant die
ze horen te weigeren: `add` op een bestaande sleutel is een conflict, `set` op een onbekende
sleutel een fout. Geen van beide doet stil het andere.

**Een alias komt leesbaar terug en een onbekende verwijzing wordt geweigerd** — de twee
bevindingen (6 en 7) uit playbook 01 die aan de overkant zijn opgelost, hier nog eens
onafhankelijk bevestigd:

```sh
zad alias list -c web -o json | jq -e '.POSTGRES_HOST == "$DATABASE_SERVER_HOST"'
! zad alias add -c web KAPOT='$BESTAAT_ECHT_NIET'
zad alias list -c web -o json | jq -e 'has("KAPOT") | not'
```

**Aliassen kennen maar één laag, en de CLI houdt zich daaraan.**
`zad alias add -c web X=… --deployment productie` wordt geweigerd in plaats van stilletjes op
de componentlaag te schrijven. De catalogus zegt `value_targets: ["component"]` voor
`aliases` en `["component","deployment-component"]` voor `user-env-vars`; de CLI volgt dat.

**Een bijlage die nog in gebruik is, verdwijnt niet zomaar.** `zad attachment delete
app-config` wordt geweigerd zolang een component ernaar verwijst; `--confirm-in-use` is nodig
om het toch te doen.

## Wat er in het playbook is gerepareerd

**`zad deployment list` geeft `deployment`, niet `name`.** De controle op twee deployments
toetste `[.[].name]` en dat is overal `null`; de deployments waren er wel. Dit is een fout in
het playbook, geen bevinding over de CLI — precies het soort controle dat op de verkeerde
vorm test en dan een probleem suggereert dat er niet is. Gecorrigeerd naar
`[.[].deployment]`.

```json
{ "deployment": "acceptatie", "project": "w0-9xs", "namespace": "w0-9xs",
  "components": ["web"], "status": "Pending", "urls": {},
  "sync_revision": null, "last_synced_at": null, "errors": [] }
```

**`zad project delete` neemt geen projectnaam** — zelfde correctie als in playbook 01.

## De vorm van `zad env list` en `zad alias list`

Sinds de leesweg bestaat, geeft `-o json` de kale afbeelding van naam naar waarde:

```json
{ "APP_MODE": "(set, not shown)", "LOG_LEVEL": "(set, not shown)" }
{ "POSTGRES_HOST": "$DATABASE_SERVER_HOST" }
```

`(set, not shown)` staat waar de API `***` teruggaf. Dat is een bewuste keuze van de CLI: de
waarde letterlijk als `***` tonen zou beweren dat de variabele op drie sterretjes staat.

## Wat niet te testen viel, en waarom

- **Of een waarde in de container aankomt onder de naam die je gaf.** Dit playbook toetst de
  waardenlaag; playbook 01 bewijst met `/status` dat een *dienst* de workload bereikt, maar
  niet dat `APP_MODE` daar de waarde `production` heeft. De testimage rapporteert geen eigen
  env-vars.
- **Bijlagen als bestand op het gemonteerde pad.** Dat de koppeling is opgeslagen is
  gecontroleerd; dat er op `/etc/app/config.yaml` daadwerkelijk "tweede inhoud" staat, is
  niet uit te lezen zonder een deployment die dat pad terugrapporteert.
- **Een derde waardendienst.** `zad env` en `zad alias` zijn dezelfde code met een andere
  dienst eraan; een derde zou dat pas echt aantonen, en die is er niet.
