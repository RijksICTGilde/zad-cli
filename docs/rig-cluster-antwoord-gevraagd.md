# Vier vragen en één gesprek

Uit `vragen-aan-rig-cluster.md`, maar dan alleen wat een antwoord van jullie nodig heeft.
Dat document is de volledige lijst met metingen erbij; dit is de korte versie, zodat er
niets ondersneeuwt.

Alles gemeten tegen `zad.sandbox.rijksapp.dev` op 15 augustus 2026.

---

## 1. Mogen we de invitecode teruglezen?

Nu komt hij terug als lege string, dus wie een invite aanmaakt kan hem niet versturen —
alleen vervangen, waarmee de vorige ongeldig wordt terwijl er misschien iemand mee onderweg
is. De code *is* de uitnodiging.

Hij is ook niet geheim in de gebruikelijke zin: wie de link heeft kan hem inwisselen, dus
hij is zo geheim als het kanaal waarover je hem stuurt. En voor de projecteigenaar verbergen
beschermt niemand — die heeft de projectsleutel al, waarmee hij de invite kan overschrijven
en de dienst kan uitzetten.

**Waar we uit kunnen:** in de gewone read, achter een eigen aanroep, of eenmalig bij het
aanmaken. Jullie weten beter wat bij het auditverhaal past. *(Punt 3.)*

## 2. Kan `approvals.status` een `enum` krijgen?

De beschrijving noemt `requested`, `denied` en `none`; het schema zegt `string`. Wij tonen
de melding nu ongeïnterpreteerd, want op drie woorden vertakken die de spec niet belooft is
stil kapotgaan zodra er een vierde bijkomt.

**Wat het oplevert:** dan kan `--strict` in een pijplijn falen op een *afgewezen* aanvraag en
zwijgen over een *lopende*. Dat is nu precies het onderscheid dat we niet mogen maken.
*(Punt 12.)*

## 3. Kan `/openapi.json` een `ETag` krijgen, of `info.version` meebewegen?

`info.version` staat op `0.1.0` en is dat door alle wijzigingen van deze week heen gebleven,
en er komt geen `ETag` of `Last-Modified` mee. De CLI leest de spec live — daar staat in wat
een veld accepteert — maar kan zonder signaal alleen op tijd cachen: nu een uur.

**Wat het kost zonder:** in dat uur vertelt `--help` de oude waarheid. Dat gebeurde vandaag
toen de default van `sleep-mode.wake-mode` van `auto` naar `manual` ging. Eén van de drie is
genoeg. *(Punt 1.)*

## 4. Waar haalt een operator een `X-Wake-Token`?

`GET /api/sleep-mode/{project}/{deployment}/status` en de bijbehorende `/wake` weigeren een
geldige projectsleutel met *"X-Wake-Token header required"*. Die header staat nergens in de
spec, en er is geen gedocumenteerde manier om er een te krijgen.

**"Die endpoints zijn alleen voor de waker-pagina" is ook een antwoord.** Dan halen wij
`zadctl service sleep-mode status` en `wake` er weer uit en zeggen we waarom. Nu staan er
twee commando's die niemand kan gebruiken. *(Punt 4.)*

---

## Het gesprek: kortlevende projecttokens voor agents

Geen vraag met een antwoord van één regel. Een projectsleutel verloopt niet en is niet in te
trekken, en zadctl wordt in toenemende mate door agents gedraaid — die lezen bestanden,
plakken uitvoer in transcripten en loggen dingen die later door iemand anders gelezen worden.

We hebben aan onze kant gekeken naar het versleutelen van die sleutel in het env-bestand en
dat laten liggen: de code die ontsleutelt is open source en draait als dezelfde gebruiker als
de agent. Het probleem is niet waar de sleutel ligt maar hoe lang hij geldig is, en dat kan
alleen bij jullie.

Wat we ons voorstellen: een token dat je op een SSO-sessie krijgt bij het kiezen van een
project, met een vervalmoment in het antwoord, intrekbaar, en bij voorkeur met een
alleen-lezen variant. CI verandert niet — daar blijft een vaste sleutel, want daar is geen
mens om in te loggen. Het volledige voorstel staat als punt 11 in het lange document.

---

De rest van `vragen-aan-rig-cluster.md` (punten 5, 7, 8, 9, 10) heeft geen antwoord nodig:
die staan er compleet in, met meting en voorstel, om op te pakken wanneer het uitkomt.

En met dank: `x-choices`, `x-choices-source`, de PATCH op de lijsten, de `anyOf` op
`restrict-access`, `x-platform-managed` en `approvals` zijn deze week geland en allemaal
verwerkt. Het onderste stuk van het lange document houdt dat bij.
