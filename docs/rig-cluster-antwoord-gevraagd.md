# Wat een antwoord nodig heeft

Uit `vragen-aan-rig-cluster.md`, maar dan alleen wat een antwoord van jullie nodig heeft.
Dat document is de volledige lijst met metingen erbij; dit is de korte versie, zodat er
niets ondersneeuwt. Begon als vier vragen en één gesprek; twee zijn beantwoord.

Alles gemeten tegen `zad.sandbox.rijksapp.dev` op 15 augustus 2026. De vier vragen van gisteren zijn beantwoord en staan onderaan. Hieronder wat er sindsdien
bij kwam: één storing en drie dingen waar wij niet omheen kunnen.

---

## 1. `PUT` op de storage-config geeft 500

```
PUT  .../services/persistent-storage/config/component/api
     [{"name": "data", "size": "1Gi", "mount-path": "/data"}]      → 500, drie keer
PATCH .../services/persistent-storage/config/component/api
     {"add": [{"name": "data", "size": "1Gi", "mount-path": "/data"}]}  → 200
```

Zelfde entry, zelfde moment; `temp-storage` doet hetzelfde. De body volgt `StorageEntry`
exact. Ons eigen draaiboek 01 strandt hierop, voor het eerst sinds 12 augustus. *(Punt 14.)*

## 2. Waar hoort `project_name` bij `check-subdomain`?

`GET /api/subdomains/check/{sub}?base_domain=…` antwoordt 401 "Missing project_name
parameter". Die parameter staat niet in de spec, en als queryparameter meesturen helpt niet.
Wij kunnen niet raden waar hij heen moet. *(Punt 15.)*

## 3. Wat moet een client met `__custom__`?

De keuzelijst voor `base-domain` biedt `__custom__` aan; de rollout weigert die waarde. Een
eigen domein als tekst invullen werkt wel, maar staat nergens. Uit de lijst halen of een
titel geven die zegt wat je moet doen. *(Punt 16.)*

## 4. Waar draait een deployment terwijl zijn domein wacht op goedkeuring?

`urls` toont alleen het aangevraagde adres, dat nog niet resolvet. Het clusteradres waar hij
wél op staat, kunnen wij niet afleiden. *(Punt 17.)*

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
