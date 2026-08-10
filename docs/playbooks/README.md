# Playbooks

Draaiboeken die de CLI van begin tot eind uitoefenen tegen een echte omgeving. Elk playbook
is één markdownbestand met genummerde stappen; elke stap is een commando plus een controle.

**De controle is een commando, geen beschrijving.** Er is geen eigen taal om te leren: elke
bewering is een aanroep die niet-nul afsluit als hij niet klopt, meestal `jq -e`. Daardoor
kan een mens dit plakken, een agent het afspelen en een script het draaien, en betekent
"stap 7 faalde" bij alle drie hetzelfde.

## Hoe je er een draait

```sh
cd $(mktemp -d)                       # een eigen map: de instellingen staan in ./.env
export ZAD=/pad/naar/zad-cli          # of gewoon `zad` als hij geïnstalleerd is
```

Werk de stappen van boven naar beneden af. De opruimstap onderaan hoort altijd te draaien,
ook als er iets faalde; wat er blijft staan, staat de volgende run in de weg.

## Niet parallel

Twee redenen, en ze zijn niet dezelfde:

1. **Instellingen staan in de `.env` van de werkmap.** Twee playbooks in dezelfde map
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
| 02-diensten-per-laag.md | *(nog te schrijven)* Elke instelbare dienst, op elke laag die hij accepteert |
| 03-waarden.md | *(nog te schrijven)* Env-vars, aliassen en bijlagen: toevoegen, wijzigen, overschrijven, weghalen, op beide lagen |
| 04-levenscyclus.md | *(nog te schrijven)* Image bijwerken, klonen, backuppen, verwijderen, terugzetten |

## Wat een playbook moet doen

- **Eindigen met bewijs van buiten de CLI.** Dat de CLI zegt dat het goed ging is de
  zwakste vorm van slagen die er is. Playbook 01 haalt daarom de applicatie zelf op.
- **Opruimen wat het aanmaakt**, ook bij een fout.
- **Elke stap controleerbaar maken.** Een stap zonder controle is een stap waarvan niemand
  merkt dat hij stilletjes niets deed.
