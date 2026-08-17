# Playbooks

Draaiboeken die de CLI van begin tot eind uitoefenen tegen een echte omgeving. Elk playbook
is één markdownbestand met genummerde stappen; elke stap is een commando plus een controle.

## Hoe een draaiboek in elkaar zit

Twee soorten inhoud, en alleen de eerste wordt uitgevoerd:

- **De ```sh-blokken zijn de stappen.** Die voert `run.py` uit, in volgorde, in één shell.
- **Het proza eromheen is het waarom**: welke laag, waarom de volgorde uitmaakt (diensten
  vóór componenten, anders faalt `--service`), en wat een fout op die plek betekent. Dat is
  het deel dat je niet uit een commandolijst haalt, en het is precies waar de vorige
  doorlopen op stukliepen.

Wil je alleen de commando's zien, dan is dat één vlag: `run.py <playbook> --commands`.

**De controle is een commando, geen beschrijving.** Er is geen eigen taal om te leren: elke
bewering is een aanroep die niet-nul afsluit als hij niet klopt, meestal `jq -e`. Daardoor
kan een mens dit plakken, een agent het afspelen en een script het draaien, en betekent
"stap 7 faalde" bij alle drie hetzelfde.

## Hoe je er een draait

Automatisch, en dat is de snelste weg:

```sh
uv run python docs/playbooks/run.py 01 --zad ./zad          # één regel per stap
uv run python docs/playbooks/run.py 01 --zad ./zad --keep   # laat het project staan
uv run python docs/playbooks/run.py 01 --list               # alleen de stappen tonen
uv run python docs/playbooks/run.py 01 --commands           # alleen de commando's, zonder proza
uv run python docs/playbooks/run.py 01 --zad ./zad --show   # commando en antwoord, live
uv run python docs/playbooks/run.py 01 --zad ./zad --step   # idem, één stap per Enter

uv run python docs/playbooks/run.py 01 02 03 04 --zad ./zad      # alle vier, na elkaar
uv run python docs/playbooks/run.py 01 02 03 04 --zad ./zad -j   # alle vier, tegelijk
```

`-j` speelt de genoemde draaiboeken tegelijk, elk in een eigen proces met een eigen werkmap
en een eigen project — ze delen niets aan onze kant, dus dat kan. **Twee keer gemeten: 6:02
en 5:57 voor de vier, tegen ongeveer acht minuten na elkaar.** Dat is een kwart winst en niet
de tweederde die "de langste in plaats van de som" belooft: ze delen wél één cluster, dus vier
gelijktijdige rollouts staan deels op elkaar te wachten. De uitvoer
wordt per draaiboek verzameld en pas geprint als dat klaar is, want vier voortgangsstromen
door elkaar leest niemand — en dan staat de fout die je zoekt vier regels boven een regel uit
een ander draaiboek.

Het opruimen verandert er niet van: elk kind draait zijn eigen teardown, en daarna de veeg
die een gemist project alsnog weghaalt, precies zoals bij één draaiboek. Onderbreek je met
Ctrl-C, dan wacht de ouder tot de kinderen hun teardown af hebben — een kind doodslaan
halverwege het opruimen is hoe een project op het cluster achterblijft.

**Waar de tijd zit**, gemeten aan draaiboek 01: 163 seconden aan stappen, waarvan 101 in twee
platformoperaties — 77s voor `deployment create` met rollout, 24s voor `project delete`. De
overige 42 stappen kosten samen een minuut, zo'n 1,5s per stap, waarvan 0,35s het starten van
de binary is. Het draaiboek wacht dus op het cluster en niet op de CLI, en dat is ook waarom
parallel draaien helpt en sleutelen aan de CLI niet.

`run.py` voert de `sh`-blokken van het draaiboek zelf uit, in één shell, zodat een
variabele uit stap 0 in stap 6 nog bestaat. Er is dus geen tweede kopie van de stappen die
kan gaan afwijken. Een blok dat een voorbeeld is en geen stap draagt `sh skip: reden` in
zijn fence en komt als overgeslagen in het verslag — niet als niets.

De opruimsectie draait ook als er iets faalde. Lukt dat opruimen zelf niet, dan zegt de
samenvatting dat er iets op het cluster kan staan; stil achterlaten op een gedeelde sandbox
is hoe je aan vier vergeten projecten komt.

Stand van de laatste doorloop, tegen build `f512417` (17 augustus, alle vier parallel in
5:57):

| Playbook | Uitkomst |
|---|---|
| 01 inrichten | 46/46 (1 overgeslagen: de interactieve inlog) |
| 02 diensten per laag | 21/21 |
| 03 waarden | 36/36 |
| 04 levenscyclus | 30/30 (1 overgeslagen: een database buiten ZAD, die dit draaiboek niet heeft) |

## Met de hand

```sh
cd $(mktemp -d)                       # een eigen map: de instellingen staan in ./.env.zadctl
export ZAD=/pad/naar/zad-cli          # of gewoon `zad` als hij geïnstalleerd is
```

Werk de stappen van boven naar beneden af. De opruimstap onderaan hoort altijd te draaien,
ook als er iets faalde; wat er blijft staan, staat de volgende run in de weg.

## Draait de build die je denkt?

Een doorloop tegen de verkeerde build meet het probleem van gisteren opnieuw. Dat is hier
twee keer gebeurd, en beide keren was de conclusie "de build is misgegaan" fout: er liep
een uitrol, en twee pods achter hetzelfde adres antwoordden om beurten.

```sh
zadctl version                        # commit, pod en image
```

Kijk **eerst naar `pod`, dan pas naar `commit`**. Twee calls met verschillende podnamen
betekent dat er een uitrol loopt: dan is wachten het antwoord. Blijft de podnaam gelijk en
klopt het commit niet, dan draait de nieuwe code er echt nog niet.

`image` is wat het cluster daadwerkelijk gestart heeft, en `dirty: true` betekent dat er
ongecommitte wijzigingen in de build zaten. Dan zegt `commit` niets en is `image` het enige
waarop je kunt afgaan.

## Niet parallel

Twee redenen, en ze zijn niet dezelfde:

1. **Instellingen staan in de `.env.zadctl` van de werkmap.** Twee playbooks in dezelfde map
   vechten om het actieve project en de sleutel. In *verschillende* mappen kan het wel:
   dat is precies waarom die instellingen daar zijn gaan staan.
2. **De omgeving is gedeeld.** Ook vanuit twee mappen praten ze tegen dezelfde sandbox, dus
   projectnamen moeten uit elkaar lopen. Elk playbook gebruikt daarom een naam met een
   achtervoegsel dat je zelf zet.

Op het servercluster is er `orch sandbox claim|release` voor turn-taking. Lokaal niet: daar
is de sandbox niet afgeschermd, dus twee mensen tegelijk merken elkaar.

## De reeks

| Playbook | Waar het over gaat |
|---|---|
| [01-inrichten.md](01-inrichten.md) | Een heel project opbouwen: drie componenten met verschillende diensten, waarden, bijlagen, uitgesteld uitrollen, en de werkende applicatie als bewijs |
| [02-diensten-per-laag.md](02-diensten-per-laag.md) | Elke instelbare dienst, op elke laag die hij accepteert, plus `config get` en `config clear` |
| [03-waarden.md](03-waarden.md) | Env-vars, aliassen en bijlagen: toevoegen, wijzigen, overschrijven, weghalen, op beide lagen |
| [04-levenscyclus.md](04-levenscyclus.md) | Image bijwerken, klonen, backuppen, terugzetten, verwijderen |

Bij elk playbook hoort een bevindingenbestand met wat de laatste doorloop opleverde:
[01-bevindingen.md](01-bevindingen.md), [02-bevindingen.md](02-bevindingen.md),
[03-bevindingen.md](03-bevindingen.md), [04-bevindingen.md](04-bevindingen.md).

## Wat een playbook moet doen

- **Eindigen met bewijs van buiten de CLI.** Dat de CLI zegt dat het goed ging is de
  zwakste vorm van slagen die er is. Playbook 01 haalt daarom de applicatie zelf op.
- **Opruimen wat het aanmaakt**, ook bij een fout.
- **Elke stap controleerbaar maken.** Een stap zonder controle is een stap waarvan niemand
  merkt dat hij stilletjes niets deed.
