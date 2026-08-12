# Bevindingen: playbook 04 (levenscyclus) tegen de sandbox

## Run 2: 12 augustus 2026, 15:00–17:00 UTC, build `edbda374`

Project `c1-ij8`, opgeruimd. **Alle stappen gelopen.** De hele backup/restore/clone-hoek,
die in run 1 volledig strandde, doet nu iets.

Wat er aan de overkant is opgelost, hier nagemeten:

| Was | Nu |
|---|---|
| Bev. 14: `clone check` valt om op `'ProjectManager' object has no attribute '_clone_manager'` | Geeft een 422 die zegt *waarom*: "Deployment 'acceptatie' has no clone-from configuration" |
| Bev. 17: `component delete` roept een endpoint aan dat niet bestaat | Werkt, en weigert terecht met 409 als het component nog in gebruik is |
| Playbook 01, bev. 8: `deployment delete` van iets onbestaands meldt succes | Faalt nu, en `--ignore-not-found` doet wat het zegt |

**Vier reparaties aan onze kant**, alle vier gevonden doordat het draaiboek verder kwam dan
ooit:

1. **`restore database|bucket` stuurden een verkeerd cluster en een verkeerde namespace.**
   Het cluster werd geraden uit het eerste streepje van de namespace (`c1-ij8` → `c1`, een
   400), en de namespace kwam van de v2-deployment, die `c1-ij8` zegt waar de echte
   `rig-c1-ij8` is (een 403 "Namespace does not belong to the authenticated project").
   Beide komen nu van `/v1/backup/runs`, het enige endpoint dat ze publiceert in de vorm
   die restore accepteert. Met die reparatie *en* het verzoeklichaam van vanmorgen komt
   restore tot `Testing target database connectivity...` en faalt pas op onze opzettelijk
   onbestaande doelhost. Het pad werkt dus.
2. **`component delete` kende `confirm_in_use` niet.** Dat is nu `--force`, en het weigeren
   zonder die vlag is een aparte stap in het draaiboek geworden.
3. **De 409 van dat weigeren werd volledig weggegooid.** De API nest de reden een niveau
   dieper (`detail.detail`) en stuurt `used_by` mee; wij toonden alleen "the resource is in
   a state that blocks this action". Hetzelfde gold voor de `validation.checks` van
   `clone check`. Allebei worden nu getoond, en een 409 met `used_by` zegt niet langer
   "wacht tot het settelt" — dat gaat namelijk nooit gebeuren.
4. **`project delete` liet de sleutel van het verwijderde project in de `.env` staan**,
   waardoor elk volgend commando een authenticatiefout gaf over een project dat gewoon weg
   was. Hij wordt nu opgeruimd; je blijft ingelogd.

En één die alleen zichtbaar werd door ernaar te kijken: `component delete` drukte zijn
succesregel **twee keer** af.

### Twee refreshes over elkaar heen

Nieuw in het draaiboek, en het gedrag was niet wat wij verwachtten. Een tweede
`project refresh` terwijl de eerste nog loopt start **geen tweede taak en stopt de eerste
niet**: hij geeft hetzelfde `task_id` terug. De wijziging die wij tussen die twee in
opsloegen is wél meegenomen — het component kwam er, kreeg een adres en antwoordde 200 — en
`project pending` stond daarna op 0.

Of dat gegarandeerd is of dat wij geluk hadden met de timing, is van buitenaf niet te zien.
Dat staat als vraag 8 in `plans/vragen-uit-zad-cli.md` van RIG-Cluster.

### Wat nog openstaat

- **Restore naar de eigen projectdatabase** blijft onuitvoerbaar: de vier doelvelden zijn
  credentials die het platform beheert en nergens teruggeeft (vraag 7). Wat wij aantoonden
  is dat het verzoek klopt, niet dat de handeling te doen is.
- **Een echte kloon** vraagt een bronhost die wij niet hebben; `clone check` en de dry-run
  zijn wel gelopen.
- **Fouttoekenning bij restore**: de API antwoordt met `HTTP 500` en zonder categorie als de
  doelhost niet resolvet. Onze laag maakt daar exit code 2 van, "platform, probeer opnieuw",
  terwijl het de invoer van de gebruiker is. Dat is vraag 9.

---

## Run 1: 11 augustus 2026, 10:00–10:30 UTC

Afgespeeld op **11 augustus 2026, 10:00–10:30 UTC** tegen
`https://zad.sandbox.rijksapp.dev/api`, build `2e8e25fc`. Projecten `c0-n72` (hele doorloop)
en `c1-i83` (de commando's een voor een nagelopen), beide opgeruimd. Eerste doorloop van dit
playbook, en de eerste keer dat backup, restore en clone überhaupt zijn aangeraakt.

**Uitkomst: de basis loopt door, de backup/restore/clone-hoek niet.** Van de elf falers in de
eerste doorloop waren er zeven fouten in het playbook (verzonnen vlaggen) en vier echte
bevindingen.

Na deze run is `93ed2a07` uitgerold; volgens de RC-69-sessie is `opi/` daarin
byte-identiek aan `2e8e25fc`, dus deze resultaten beschrijven ook wat er nu draait.

---

## Per stap

| Stap | Uitkomst | Kort |
|---|---|---|
| 1. Project | **gelukt** | |
| 2. Een draaiend vertrekpunt | **gelukt** | `Healthy`, postgres en minio gebonden en geverifieerd |
| 3. `deployment update-image` | **gelukt** | inclusief: onbekend component wordt geweigerd |
| 4. Tweede deployment | **gelukt** | |
| 4b. `clone check` / `clone database` / `clone bucket` | **gefaald** | bev. 14; playbook had bovendien verzonnen vlaggen |
| 5. `backup create` / `backup list` | **gelukt** | na correctie van het playbook |
| 5b. `backup database` / `backup bucket` / `backup namespace` | **gefaald** | bev. 15 |
| 6. `restore list` | **gelukt** | na correctie: cluster + namespace |
| 6b. `restore database` / `restore bucket` | **gefaald** | bev. 16 |
| 7. `component update` | **gelukt** | inclusief: `--service` vervangt de lijst |
| 7b. `component delete` | **gefaald** | bev. 17 — het endpoint bestaat niet |
| 8. `deployment delete` | **gelukt** | inclusief `--ignore-not-found`, na onze reparatie |
| 9. `project delete` | **gelukt** | |

---

## De bevindingen

### 14. `clone check` valt om op een ontbrekend attribuut

```sh
$ zad clone check productie
Error validating clone configuration: 'ProjectManager' object has no attribute '_clone_manager'
```

Dat leest als een interne fout aan de serverkant, geen configuratiefout van de gebruiker. De
CLI labelt hem als "transient, probeer opnieuw"; dat is bij deze melding te vriendelijk, maar
de CLI kan het van buitenaf niet beter weten.

Reproductie zonder de CLI:

```sh
curl -sS -H "X-API-Key: $KEY" \
  "https://zad.sandbox.rijksapp.dev/api/v2/projects/$PROJECT/deployments/productie/:validate-clone"
```

Het schrijvende pad is hierdoor niet te beproeven: zonder een geldige `clone check` is een
echte kloon niet verantwoord te draaien. Wat wél klopt is het verzoek dat de CLI bouwt:

```sh
$ zad clone database productie --host db.example.org --dbname bron --username u --password p --dry-run -o json
{ "dry_run": true, "method": "POST",
  "endpoint": "/v2/projects/c1-i83/deployments/productie/:clone-database",
  "payload": { "sourceHost": "db.example.org", "sourcePort": 5432, ... } }
```

### 15. `backup database`, `backup bucket` en `backup namespace` geven 404

`backup create` werkt en levert een run op. De losse varianten niet, ook niet met de namen
die `backup list` zelf teruggeeft:

```sh
$ zad backup list productie -o json | jq -c '[.runs[].items[] | {resource_type, reference_name}] | unique'
[{"resource_type":"database","reference_name":"backup"},
 {"resource_type":"bucket","reference_name":"bucket-backup"}]

$ zad backup database productie backup
✗ Not found (HTTP 404): the resource you referenced doesn't exist.

$ zad backup bucket productie bucket-backup
✗ Not found (HTTP 404)

$ zad backup namespace rig-c1-i83
✗ Not found (HTTP 404)
```

De referentienaam komt hier dus uit het antwoord van de API zelf, en wordt door de API niet
herkend. Of de CLI de verkeerde `reference_name` doorgeeft of het endpoint iets anders
verwacht, is van buitenaf niet vast te stellen — vandaar dat dit als bevinding blijft staan
en niet als reparatie.

### 16. `restore database` en `restore bucket` geven 422

> **Opgelost op 12 augustus, en het lag aan ons.** Niet de referentienaam maar het
> ontbrekende verzoeklichaam: beide endpoints vereisen er een, en onze client stuurde er
> geen. Het stond in de spec die we zelf vendoren, `DatabaseRestoreRequest` met vier
> verplichte velden. Het spoor hieronder over `pvc_name` versus `reference_name` was fout;
> die drie namen zijn dezelfde waarde. De commando's hebben nu `--target-*`-opties, en
> `scripts/check_coverage.py` stelt sinds vandaag ook de derde vraag: stuurt elke aanroep
> de body die zijn endpoint verplicht stelt. Die controle draait mee in `pytest`.
>
> **Wat er wél blijft staan**, als nieuwe bevinding voor de API-kant: die vier doelvelden
> zijn de credentials van de doeldatabase, en voor een door ZAD beheerde database kun je
> die nergens opvragen. Er is geen commando en geen endpoint dat ze teruggeeft. Terugzetten
> in je eigen projectdatabase vraagt dus om een wachtwoord dat de gebruiker niet heeft.
> Daarmee is deze stap nog steeds niet te draaien, nu om een andere reden.

Met dezelfde referentienamen uit `backup list`:

```sh
$ zad restore database productie backup
✗ Invalid request (HTTP 422): the values you sent didn't pass validation.

$ zad restore bucket productie bucket-backup
✗ Invalid request (HTTP 422)
```

`restore list` werkt wel, en laat zien dat de snapshots er zijn:

```sh
$ zad restore list sandboxed-local rig-c1-i83 -o json
[ { "snapshot_id": "41bbdb572907e918b96665c1e8b3369f", "pvc_name": "bucket-backup",
    "timestamp": "2026-08-11T10:14:50Z", "size_bytes": 0 } ]
```

Merk op dat `restore list` een **pvc_name** teruggeeft en de restore-endpoints in de spec op
`{cluster}/{namespace}/{reference_name}` staan. Dat zijn drie namen voor mogelijk hetzelfde
ding (`reference_name`, `pvc_name`, en wat `backup list` een `reference_name` noemt), en dat
is de meest waarschijnlijke plek waar dit uiteenloopt.

### 17. `zad component delete` roept een endpoint aan dat niet bestaat

> **Opgelost op 11 augustus.** `DELETE /api/v2/projects/{p}/components/{c}` staat nu in de
> spec en het commando doet weer wat het zegt. De tussenoplossing (lokaal weigeren met
> uitleg) is teruggedraaid.

```sh
$ zad --verbose component delete wegwerp
--> DELETE https://zad.sandbox.rijksapp.dev/api/v2/projects/c1-i83/components/wegwerp
✗ Request rejected (HTTP 405). Method Not Allowed
```

En dat klopt met de live spec: op het componentpad staat **alleen** `patch`.

```
['get', 'post']  /api/v2/projects/{project_name}/components
['patch']        /api/v2/projects/{project_name}/components/{component_name}
```

Er is dus in de hele API geen enkele manier om een component te verwijderen. Dit is
**niet** in de CLI te repareren: het commando bestaat sinds 1.0 en mag volgens het
compatibiliteitsbeleid niet verdwijnen, maar er is niets om het naartoe te sturen. Het hoort
aan de overkant terug te komen, of hier een expliciete "dit kan niet op deze API" te worden.

---

## Wat er in het playbook is gerepareerd

Zeven van de elf falers waren verzonnen vlaggen — het playbook was geschreven vóór het voor
het eerst gedraaid werd, en dat is precies waarom een playbook dat nooit gedraaid heeft een
verzameling aannames is.

**`clone` gaat niet van deployment naar deployment.** `--from`/`--to` bestaan niet.
`zad clone database <deployment>` haalt data uit een **externe** bron (`--host`, `--dbname`,
`--username`, `--password`) en zet die in één deployment. Dat is een andere operatie dan
"kopieer acceptatie naar productie", en het playbook beweerde het verkeerde.

**`backup list` neemt een deployment** en geeft `{cluster, namespace, runs[]}` terug, geen
kale lijst. De namespace is `rig-<project>`, niet de projectnaam — dat is precies wat
`restore list` nodig heeft.

**`restore list` neemt een cluster en een namespace**, allebei positioneel. Met de
projectnaam in plaats van de namespace komt er een nette maar misleidende melding:
`Namespace does not belong to the authenticated project`.

**`backup database` en `restore database` nemen `<deployment> <reference>`**, geen
`--from`/`--to`.

## Over de doorlooptijd, gemeten

Omdat de indruk bestond dat een uitrol minuten duurt: dat klopt niet, en het is de moeite
waard om vast te leggen waar de tijd wél zit.

```
deployment create (met rollout aan)  3m05s
project refresh                      47s   (eerder gemeten: 62s, 68s)
status na refresh                    Healthy, direct
applicatie antwoordt 200             0s
```

`Healthy` is er dus meteen, en de applicatie antwoordt meteen. De tijd zit in het
**afwachten van de asynchrone taak**, en vooral in een `deployment create` die zelf uitrolt.
Dat is ook waarom playbook 01 met `--no-rollout` werkt: alle schrijfacties zijn dan snel en
er is één refresh van ongeveer een minuut aan het eind. De wachtlussen in de playbooks
breken op de eerste ronde af; ze staan er voor het geval het een keer níet zo is.

## Wat niet te testen viel, en waarom

- **Een echte kloon** (`clone database` / `clone bucket` schrijvend). Twee redenen, en beide
  tellen: `clone check` werkt niet (bevinding 14), en er is geen externe bronhost met data
  om uit te klonen. Alleen het opgebouwde verzoek is gecontroleerd, via `--dry-run`.
- **Een echte restore-terugleescontrole.** `restore database` komt niet voorbij de validatie
  (bevinding 16), dus of de data terugkomt is niet vast te stellen. Ook als het wél werkte,
  zou `/status` alleen zeggen dat de dienst beschrijfbaar is, niet dat de rij van vóór de
  backup er weer in staat; daarvoor zou de testimage een gemarkeerde rij moeten schrijven en
  terugzoeken.
- **`component delete`** kan niet (bevinding 17), dus wat er met een deployment gebeurt die
  een verwijderd component bevatte, is onbeproefd.
- **`backup` per onderdeel** (bevinding 15), dus alleen de volledige `backup create` is
  aangetoond.
