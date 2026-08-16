# Wat een antwoord nodig heeft

Uit `vragen-aan-rig-cluster.md`, maar dan alleen wat een antwoord van jullie nodig heeft.
Dat document is de volledige lijst met metingen erbij; dit is de korte versie, zodat er
niets ondersneeuwt.

Alles gemeten tegen `zad.sandbox.rijksapp.dev`, laatst nagelopen op 16 augustus 2026 aan het
eind van de dag. Een praktijkronde heeft die dag het platform zonder voorkennis ingericht en
kwam met twaalf bevindingen terug; wat hieronder staat is wat daarvan bij jullie ligt.

**En de twee zwaarste zijn dezelfde avond nog opgelost** — de stille no-op op `POST /services`
en `check-subdomain`. Allebei nagemeten en verwerkt; ze staan onderaan. Wat overblijft is
kleiner, en niets ervan houdt iemand tegen.

---

## 1. Wat moet een client met `__custom__`?

De keuzelijst voor `base-domain` biedt `__custom__` aan; de rollout weigert die waarde. Een
eigen domein als tekst invullen werkt wel, maar staat nergens. *(Punt 16.)*

## 2. Waar draait een deployment terwijl zijn domein wacht op goedkeuring?

`urls` toont alleen het aangevraagde adres, dat nog niet resolvet. Het clusteradres waar hij
wél op staat, kunnen wij niet afleiden. *(Punt 17.)*

## 3. Welk domein uit de clusterlijst mag direct?

`base-domains` geeft `value` en `label`; een domein eruit kiezen levert alsnog een approval
op. Een veld dat de twee gevallen scheidt zetten wij in de keuzelijst. *(Punt 21.)*

---

## Kleiner, maar wel een antwoord waard

- **`base_domain` en `domain-format` staan half in twee schema's.** De `x-choices-source`
  zit op de publish-on-web-config, de `enum` op het deployment-verzoek, en `deployment create`
  heeft ze allebei nodig. *(Punt 23.)*
- **Vijf attachment-endpoints kennen geen `rollout`.** Met `rollout=false` gaat de wijziging
  er meteen op en `pending-rollout` beweegt niet. Dezelfde parameter, of één zin die zegt dat
  ze altijd meteen uitrollen — beide is goed. *(Punt 22.)*
- **`sleep-mode status` zegt `starting`** voor een `Healthy` deployment met sleep-mode uit.
  *(Punt 25.)*
- **Twee gelijktijdige writes melden een verschillend aantal wachtende wijzigingen.** Race in
  de teller, niet in de data. *(Punt 24.)*

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

**`POST /services` bindt de componenten nu ook als de dienst er al stond**, en de beschrijving
zegt het erbij: *"configure-then-bind works in either order."* Dat was de zwaarste bevinding
van de ronde — een `success` op een binding die niet gebeurde, met een publieke URL die 200
antwoordde terwijl er een authorization-wall voor had moeten staan. Nagemeten voordat we het
geloofden: een kale `POST` met `components: ["worker"]` op een dienst die al op het project
stond, en `worker` had hem daarna. Onze omweg — binden via `add_services` per component — is
weer weg; het is één aanroep zoals het hoort. Wat we bewaren is de controle: draaiboek 01
bindt nu een dienst die een stap eerder is geconfigureerd en leest daarna `component list`
na, in plaats van het antwoord te geloven.

**`check-subdomain` is verhuisd naar onder het project** en werkt. Punt 15 en 20 in één keer,
en op een manier die wij niet hadden kunnen raden: de projectnaam moest in het *pad*, omdat de
API-sleutel wordt gelegitimeerd tegen het project dat in de route staat. Nagemeten: `keycloak`
is bezet, een vrije naam is vrij. De CLI vraagt nu om een project, en de noodmelding die we
's middags nog inbouwden is weer weg.

**De 500 op de storage-`PUT` is over.** Gemeld op 15 augustus, en op de 16e loopt draaiboek 01
weer helemaal door: 44 van de 44, met de `PUT` als stap 16. Het bewijs zit niet in de
schrijfactie maar in stap 42, die `/api/status` ophaalt bij de draaiende workload en eist dat
`storage-data` er `ok` is — dus gemount, niet alleen opgeslagen. Aan onze kant is er tussen
de twee rondes niets veranderd. Als iemand weet wat het was horen we het graag: dat is het
verschil tussen "gerepareerd" en "vanzelf overgegaan", en het tweede kan terugkomen.

**De invitecode komt terug bij een read** (was vraag 1), en er is een generator bij gekomen
die we niet gevraagd hadden: laat je de sleutel leeg, dan vult het platform er een in en
meldt die onder `generated`. Nagemeten met een echte invite, en de CLI toont die regel nu na
elke schrijfactie -- het is de enige plek waar je een code te zien krijgt die je niet zelf
koos.

**`approvals.status` is een enum** (was vraag 2): `none | requested | denied`. `--strict`
faalt daardoor sinds vandaag op een afgewezen aanvraag en zwijgt over een lopende. Een test
pint die drie waarden vast, zodat een vierde bij ons als rode build binnenkomt in plaats van
als stilte.

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
