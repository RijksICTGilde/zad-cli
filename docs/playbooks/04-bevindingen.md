# Bevindingen: playbook 04 (levenscyclus) tegen de sandbox

Afgespeeld op **11 augustus 2026, 10:00–10:30 UTC** tegen
`https://zad.sandbox.rijksapp.dev/api`, build `2e8e25fc`. Projecten `c0-n72` (hele doorloop)
en `c1-i83` (de commando's een voor een nagelopen), beide opgeruimd. Eerste doorloop van dit
playbook, en de eerste keer dat backup, restore en clone überhaupt zijn aangeraakt.

**Uitkomst: de basis loopt door, de backup/restore/clone-hoek niet.** Van de elf falers in de
eerste doorloop waren er zeven fouten in het playbook (verzonnen vlaggen) en vier echte
bevindingen.

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
