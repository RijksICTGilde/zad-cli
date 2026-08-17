# Wat een antwoord nodig heeft

Uit `vragen-aan-rig-cluster.md`, maar dan alleen wat een antwoord van jullie nodig heeft.
Dat document is de volledige lijst met metingen erbij; dit is de korte versie, zodat er
niets ondersneeuwt.

Alles gemeten tegen `zad.sandbox.rijksapp.dev`, laatst nagelopen op **17 augustus 2026**. Er
liepen twee praktijkrondes: op de 16e één die twaalf bevindingen opleverde, en op de 17e één
die er tien vond. Wat hieronder staat is wat daarvan bij jullie ligt; de rest is aan onze kant
gerepareerd.

**En jullie hebben vijf van onze punten in die twee dagen geleverd** — de stille no-op op
`POST /services`, `check-subdomain` onder het project, `rollout` op de attachment-endpoints,
`sleep_state` naast `state`, en de 500 op de storage-`PUT`. Allemaal nagemeten voordat we ze
geloofden; ze staan onderaan met wat de meting opleverde. Dank daarvoor — het scheelde ons
twee omwegen die we alweer hebben weggehaald.

Eén vraag is nieuw en kost ons iets concreets: **nummer 4 hieronder is waarom een invoerfout
uit onze CLI komt met exit 3 in plaats van exit 1.**

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

## 4. Van wie is de fout als een taak faalt?

Een gefaalde taak stuurt `error_type` (vrije string, geen enum) en geen `error_category`. Onze
afspraak is dat we zonder categorie niet gokken: de fout wordt `Unknown` en de exit code 3,
"niet toe te schrijven". Het gevolg is dat `component add x --service attachments` op een
project waar die dienst nog niet gekozen is — een duidelijke invoerfout, `error_type:
invalid_services` — eruit komt als exit 3 in plaats van 1. Een praktijkronde noemde dat, en had
gelijk.

Twee wegen, en de eerste is het minste werk: zet `error_category` op een gefaalde taak met
dezelfde `ErrorCategory` die `component_failures` al gebruikt, óf maak `error_type` een enum.
In het tweede geval pinnen wij hem vast met een test, zoals bij `ErrorCategory` en
`ApprovalNoticeStatus`, zodat een nieuwe waarde bij ons als rode build binnenkomt in plaats
van als stilte. *(Punt 26.)*

---

## Kleiner, maar wel een antwoord waard

- **`base_domain` en `domain-format` staan half in twee schema's.** De `x-choices-source`
  zit op de publish-on-web-config, de `enum` op het deployment-verzoek, en `deployment create`
  heeft ze allebei nodig. *(Punt 23.)*
- **De storage-beschrijving noemt een default die niet de default is.** De `explanation` zegt
  "standaard 1Gi op /data" en "500Mi op /tmp"; wat er wordt aangemaakt is 100Mi. Wij geven die
  tekst letterlijk door, dus onze `describe` vertelt nu iets onwaars. *(Punt 27.)*
- **`minio-storage` markeert `revisions[0].*` als verplicht** terwijl een write zonder
  `revisions` gewoon wordt geaccepteerd; `service describe` zet daar dus een sterretje bij
  velden die niemand nodig heeft. *(Punt 28.)*
- **Wat garandeert `check-subdomain`?** Hij zei `available: true` voor een domein dat van
  niemand is. Eén zin over wat de check wél betekent is genoeg; kan hij er ook bij zeggen of
  het base-domain van dit cluster is, dan vallen "vrije naam" en "bruikbaar adres" samen.
  *(Punt 29.)*
- **De platte `error` van een taak is midden in een woord afgeknipt** terwijl de subtaak
  dezelfde zin voluit draagt. Wij tonen sinds vandaag de langste van de twee. *(Punt 26.)*
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

**De vijf attachment-endpoints nemen `rollout`** (was punt 22). Daarmee kon de waarschuwing die
we er 's avonds voor bouwden weer weg — en dat moest ook: de endpoints die de parameter nog
missen zijn er waar uitstellen geen betekenis heeft (admin-triggers, `task cancel`, `wake`,
`project create`), dus zij gaf alleen nog vals alarm. We zagen hem afgaan op een `project
delete`, waar "Rolled out anyway" nergens op sloeg.

**`sleep_state` staat naast `state`** (was punt 25), met `awake | sleeping | waking |
disabled`, en beide velden dragen hun uitleg in de spec. Dat antwoord was leerzamer dan onze
vraag: `state` is het pollcontract van de wekker en staat op `starting` zolang de app geen
ready pod heeft *en* wanneer er helemaal geen wekker is. Onze bevinding was dus geen verkeerde
stand maar een verkeerd gelezen veld. Nagemeten `{"state": "starting", "sleep_state":
"disabled"}`; `sleep-mode status` zet `sleep_state` nu bovenaan, want jullie sturen het
misleidende veld eerst.

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
