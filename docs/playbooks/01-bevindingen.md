# Bevindingen: playbook 01 tegen de sandbox

Twee doorlopen, beide vastgelegd:

| Run | Wanneer | Build | Uitkomst |
|---|---|---|---|
| 1 | 10 augustus 2026, 21:06–21:20 UTC | `2d04342f` (10 aug 20:25 UTC) | gestrand op stap 11 |
| 2 | **11 augustus 2026, 08:45–10:05 UTC** | **`2e8e25fc`** (11 aug 08:34 UTC) | **stap 13 gehaald** |

Run 2 draaide met zad-cli op deze branch (basis `v1`). Projecten `p0-ui9` (verkennend) en
`p0-50b` (het draaiboek als geheel, geautomatiseerd afgespeeld). Beide zijn opgeruimd.

> Over de build: het plan noemde `56b78f9e` als vorige build, en de orchestrator corrigeerde
> dat naar `2d04342f`. Dat laatste klopt. `2e8e25fc` bevat de zes RC-66-reparaties
> (`b07489ea` is een voorouder); de RC-69-sessie heeft dat aan hun kant nagerekend met
> `git merge-base --is-ancestor` en een lege `git diff` over `opi/`.

> **Na deze run is `93ed2a07` uitgerold** (11 aug 10:27 UTC). Volgens de RC-69-sessie is
> `opi/` daarin byte-identiek aan `2e8e25fc` — alleen Taskfile, docs en tests verschillen —
> dus deze resultaten beschrijven ook wat er nu draait. Dat byte-verschil is hun meting, niet
> de onze; `/version` en `/health` zijn hier wel zelf nagekeken.

---

## De hoofdzaak: de keten is nu bewezen

**Stap 13 is gehaald.** Voor het eerst is niet alleen "de API bevestigt dat het is
opgeslagen" aangetoond, maar het hele pad: de CLI schrijft, het platform rolt uit, en de
workload bereikt zijn diensten met de credentials die het platform injecteerde.

```
$ curl -sS "$URL/status" | jq -c '.services|to_entries[]|{(.key):{bound:.value.bound,ok:.value.ok}}'
{"minio":{"bound":true,"ok":true}}
{"platform":{"bound":true,"ok":true}}
{"postgres":{"bound":true,"ok":true}}
{"redis":{"bound":true,"ok":true}}
{"web":{"bound":true,"ok":true}}
{"metrics":{"bound":false,"ok":null}}     # niet aan dit component gebonden
{"oidc":{"bound":false,"ok":null}}
{"storage-data":{"bound":false,"ok":null}}
{"storage-temp":{"bound":false,"ok":null}}

$ curl -sSf "$URL/status?strict=1" > /dev/null    # 200
```

Het `api`-component heeft andere bindingen en geeft dus een tweede antwoord:
`storage-data` (persistent-storage) verifieert daar met `ok: true`.

Het geautomatiseerde afspelen van het hele playbook eindigt op **0 falers**.

## De stand van de bevindingen uit run 1

| # | Bevinding | Stand na run 2 |
|---|---|---|
| 1 | `service config set` weigert een lege configuratie | **weg** (was al van ons, opgelost op 11 aug) |
| 2 | *geen bevinding*: het verzoek van `deployment create` klopt | n.v.t. |
| 3 | `:upsert-deployment` klapt op `'deployments'` | **weg** |
| 4 | `:refresh` faalt op "Diensten en manifesten bijwerken" | **weg** |
| 5 | Geen leesweg voor env-vars en aliassen | **weg** |
| 6 | Aliaswaarden komen gemaskeerd terug als `***` | **weg** |
| 7 | Een alias naar een niet-bestaande variabele wordt geaccepteerd | **weg** |
| 8 | `DELETE` van een niet-bestaande deployment meldt succes | **van vorm veranderd**: de API zegt het nu eerlijk, de CLI las het niet — bij ons gerepareerd |
| 9, 10, 11 | Fouten in het playbook zelf | gecorrigeerd in run 1 |

Per stuk, met wat er gemeten is:

**3 — `deployment create` werkt.** `zad deployment create productie --component web --image …`
slaagt, gevolgd door `component assign` voor `api` en `worker`; `deployment describe` toont
drie componenten. Dit was in run 1 de zwaarste bevinding en maakte stap 11 tot 13
onbereikbaar.

**4 — `project refresh` werkt.** `success`, "All project resources processed successfully",
in ongeveer 62 seconden; `project pending` gaat van 21 naar 0.

**5 — er is een leesweg.** De live spec geeft nu `get` op elk waarden-endpoint:

```
['delete','get','patch','post'] /api/v2/projects/{p}/services/user-env-vars/values/component/{c}
['delete','get','patch','post'] /api/v2/projects/{p}/services/user-env-vars/values/deployment/{d}/component/{c}
['delete','get','patch','post'] /api/v2/projects/{p}/services/aliases/values/component/{c}
```

**6 — een alias komt leesbaar terug.** De spec zegt het nu ook met zoveel woorden: "An alias
value is NOT a secret — it is a reference to a platform variable, and the reference is
exactly what a reader is checking — so it comes back as stored." Gemeten:
`{"POSTGRES_HOST": "$DATABASE_SERVER_HOST"}`. Een env-var blijft `***`, en dat hoort: die is
versleuteld opgeslagen.

**7 — een onbekende verwijzing wordt geweigerd**, met HTTP 422, exitcode 1 en de lijst
beschikbare variabelen erbij.

---

## Wat er nog wél aan de overkant ligt

Twee bevindingen, allebei reproduceerbaar zonder de CLI. Doorgegeven aan RIG-Cluster.

### 12. Een component met een ingress-pad anders dan `/` is onbereikbaar

> **Opgelost op 12 augustus, en onze conclusie hieronder was maar half juist.** De
> ingressregel *werd* gegenereerd; wat ontbrak was een herschrijving, dus `/api` kwam
> ongewijzigd bij de container aan. Van de vier 404's waren er dus twee van nginx (buiten
> het voorvoegsel) en twee van de applicatie zelf (die op `/` luistert). Met alleen
> statuscodes is dat niet te onderscheiden, en "er zit geen backend achter" hieronder is
> daarom te stellig. RIG-Cluster heeft `rewrite` aan de component-API toegevoegd; de CLI
> heeft nu `--rewrite`, en het playbook maakt `api` aan met `--path /api --rewrite /` en
> controleert in stap 13 zowel dat `/api/status` aankomt als dat `/status` 404 geeft.

Component `api`, aangemaakt met `--path /api`, krijgt een URL en de deployment wordt
`Healthy`. De pod is gezond en verifieert zijn diensten (zichtbaar in `zad logs`). Maar er
is geen ingressregel die matcht: **elke** URL op die host geeft de 404-pagina van nginx.

```sh
# host van het component met --path /api
for p in / /api /status /api/status; do
  curl -sS -o /dev/null -w "$p -> %{http_code}\n" "https://api-productie-<project>.sandbox.rijksapp.dev$p"
done
# / -> 404 ; /api -> 404 ; /status -> 404 ; /api/status -> 404   (nginx-404, dus geen backend)
```

Het pad staat ook niet op de host van het andere component: `https://web-…/api/status` geeft
`404 page not found` in platte tekst — dat is de applicatie van `web`, dus die host stuurt
`/api` niet door.

Isolerend experiment, en daarmee de oorzaak:

```sh
zad component update api --path /
zad project refresh
curl -s -o /dev/null -w "%{http_code}\n" https://api-productie-<project>.sandbox.rijksapp.dev/status   # 200
```

Binnen een minuut 200. Het ligt dus op het niet-root-pad, niet op het component, de image of
de dienst. Playbook 01 geeft `api` daarom nu zijn eigen host op `/`.

### 13. `POST /v2/projects` geeft een API-sleutel terug die nog niet werkt, en er is niet op te wachten

Het aanmaken van een project is asynchroon. De 202 draagt de API-sleutel, maar het project
bestaat op dat moment nog niet, dus het eerstvolgende projectgebonden commando geeft 401.
Even later werkt dezelfde sleutel wel.

```sh
curl -sS -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  https://zad.sandbox.rijksapp.dev/api/v2/projects -d '{"displayName":"Race"}'
# 202 {"project_name":"r0-abc","api_key":"…","task_id":"…","poll_url":"/api/tasks/…"}

curl -sS -H "X-API-Key: <die sleutel>" \
  https://zad.sandbox.rijksapp.dev/api/v2/projects/r0-abc/components
# 401 Authentication required
```

Erger dan het wachten zelf is dat er **geen signaal** is om op te wachten:

- `/api/tasks/{id}` met het bearer-token → `401 {"detail":"Authentication required - provide X-API-Key header"}`
- `/api/tasks/{id}` met de zojuist ontvangen sleutel → ook 401, want die sleutel wordt pas
  geaccepteerd als het project bestaat

Een client kan dus niet zien wanneer het project klaar is. Daarom is dit **niet** in de CLI
opgelost: elke wachtlus daar zou een gok zijn, en een stille retry op 401 zou een echte
authenticatiefout maskeren. De playbooks hebben in plaats daarvan een expliciete lus:

```sh
for i in $(seq 1 30); do zad project status >/dev/null 2>&1 && break; sleep 2; done
```

---

## Wat er in de CLI is gerepareerd

Drie dingen, alle drie met tests.

**`zad env list` en `zad alias list` lezen de waarden nu op bij de API.** Ze bevroegen het
configdocument van de dienst, en dat komt leeg terug; het resultaat was een lege lijst die
leest als "er staat niets" terwijl de variabelen aantoonbaar bestonden (bevinding 5). Nu
wordt de `GET` van het waarden-endpoint gebruikt — die van **de laag waarop het commando
acteert**, dus ook `--deployment`, wat de componentdefinitie principieel niet kan
beantwoorden. Een `***` wordt getoond als `(set, not shown)` en niet als een waarde van drie
sterretjes. Tegen een API zonder die `GET` (405) valt de CLI terug op de componentdefinitie
zodat de namen zichtbaar blijven; is er helemaal geen leesweg, dan is dat een fout en geen
lege lijst — een diagnose met bron `platform` en exitcode 2, die zegt *welke* van de drie
dingen er misging: de `GET` antwoordde zonder `values`, of hij bestaat niet en de
componentdefinitie kan de deploymentlaag niet beantwoorden, of hij noemt de namen niet.

**`zad deployment delete` meldt geen verwijdering die niet plaatsvond** (bevinding 8). De API
antwoordde vroeger 404 en rondt de taak nu af met `deleted: false` en `already_absent: true`
plus een duidelijke boodschap. De CLI keek daar niet naar en zei onvoorwaardelijk
`Deployment 'X' deleted.`, waarmee een fout stilzwijgend een succes werd — en
`--ignore-not-found` betekenisloos, want zonder die vlag was de uitkomst al 0. Nu is "niets
verwijderd" een diagnose met exitcode 1, en met `--ignore-not-found` blijft het een succes,
zoals de vlag belooft.

**`login-headless.py` liep vast op de inlogpagina.** Het script wachtte op `load`, en op de
inlogpagina van Keycloak komt dat nooit af: `Page.goto: Timeout 30000ms exceeded`.
`domcontentloaded` is genoeg. De flow zelf is niet veranderd — het script bedient `zad login`
nog steeds in plaats van eromheen te werken.

## Wat er in het playbook is gerepareerd

**De projectdiensten werden nergens aan een component gebonden.** Dit is de belangrijkste
correctie, en het is precies het soort fout waar stap 13 voor bestaat. `zad service config set
postgresql-database` zegt dat het *project* een database heeft; het component krijgt de
credentials pas als de dienst in zijn eigen lijst staat. Zonder die binding meldde `/status`
netjes `all_ok: true` en gaf `strict=1` een 200 — met alleen `platform` en `web` gebonden en
alle echte diensten op `bound: false, ok: null`. Een niet-gebonden dienst telt namelijk niet
mee in `all_ok`. **De laatste stap was dus groen zonder iets te bewijzen.** De componenten
krijgen nu `--service`, en stap 13 controleert expliciet dat `postgres`, `redis` en `minio`
*gebonden én ok* zijn.

**De volgorde van stap 4 en 5 is omgedraaid.** `zad component add --service` mag alleen
diensten noemen die het project al heeft, anders faalt hij met
`Services not defined on project: [...]`. De projectdiensten staan daarom nu vóór de
componenten. Andersom geldt: diensten die op de componentlaag wonen (`publish-on-web`,
`health-check`, `metrics-scraper`, de opslagdiensten) worden juist *toegevoegd* door
`zad service config set … --component`, en horen niet in `--service`.

**`zad project delete` neemt geen projectnaam.** Het playbook riep
`zad project delete "$(zad config get project)"` aan, en dat is `Got unexpected extra
argument(s)`. Het commando werkt op het actieve project; een ander project kies je met `-p`.

**Stap 8 toetst weer de verwijzing zelf.** In run 1 was die controle afgezwakt tot
"bestaat de sleutel", omdat de API de waarde maskeerde (bevinding 6). Dat is niet meer nodig.

## Wat niet te testen viel, en waarom

- **Een ingress-pad anders dan `/`** was niet werkend te krijgen (bevinding 12). Dat kan nu
  wel, met `--rewrite`, en het playbook beproeft het sindsdien in stap 5 en 13. Ten tijde
  van deze doorloop week het uit naar een eigen host per component.
- **`oidc` en `metrics`** komen in `/status` niet aan bod: `keycloak` en `metrics-scraper`
  zijn in dit playbook niet aan `web` gebonden. `metrics-scraper` staat wel op `worker`, maar
  dat component heeft geen ingress, dus zijn `/status` is niet op te halen.
- **Of een waarde ook echt in de container aankomt** onder de naam die je gaf: `/status`
  bewijst dat de *dienst* bereikbaar is, niet dat `APP_MODE` de waarde `production` heeft.
