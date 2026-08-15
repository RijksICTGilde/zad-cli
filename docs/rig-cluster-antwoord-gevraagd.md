# Vier vragen en één gesprek

Uit `vragen-aan-rig-cluster.md`, maar dan alleen wat een antwoord van jullie nodig heeft.
Dat document is de volledige lijst met metingen erbij; dit is de korte versie, zodat er
niets ondersneeuwt.

Alles gemeten tegen `zad.sandbox.rijksapp.dev` op 15 augustus 2026. **Twee zijn inmiddels
beantwoord** en staan onderaan; wat hierboven staat wacht nog.

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

*Er staat inmiddels `examples: ["requested"]` op. Dank, maar dat is net niet wat we nodig
hebben: een voorbeeld zegt welke waarde het veld kán hebben, niet welke het kán hebben en
verder geen. Wij moeten weten dat de verzameling gesloten is voordat we erop durven
vertakken.*

De beschrijving noemt `requested`, `denied` en `none`; het schema zegt `string`. Wij tonen
de melding nu ongeïnterpreteerd, want op drie woorden vertakken die de spec niet belooft is
stil kapotgaan zodra er een vierde bijkomt.

**Wat het oplevert:** dan kan `--strict` in een pijplijn falen op een *afgewezen* aanvraag en
zwijgen over een *lopende*. Dat is nu precies het onderscheid dat we niet mogen maken.
*(Punt 12.)*

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

## Beantwoord, en verwerkt

**Er is een `ETag` op `/openapi.json`** (was vraag 3). `info.version` staat nog op `0.1.0`,
maar dat hoeft niet meer: de CLI stuurt nu `If-None-Match` zodra zijn kopie ouder is dan een
minuut, en krijgt meestal `304` terug. Een revalidatie kost 0,03s tegen 0,16s voor een
download, dus de vertraging van een uur is weg zonder dat iemand er iets van merkt.

**`sleep-mode status` en `wake` accepteren de projectsleutel** (was vraag 4), en de spec
documenteert nu allebei de headers: *"The project's API key. Accepted here as well, so a
project owner can wake his own deployment."* Getest, het werkt. De `--wake-token`-vlag
blijft staan voor wie een waker-token heeft, maar is niet meer nodig — en de helptekst zegt
dat nu ook, in plaats van dat het platform je sleutel weigert.

De rest van `vragen-aan-rig-cluster.md` (punten 5, 7, 8, 9, 10) heeft geen antwoord nodig:
die staan er compleet in, met meting en voorstel, om op te pakken wanneer het uitkomt.

En met dank: `x-choices`, `x-choices-source`, de PATCH op de lijsten, de `anyOf` op
`restrict-access`, `x-platform-managed` en `approvals` zijn deze week geland en allemaal
verwerkt. Het onderste stuk van het lange document houdt dat bij.
