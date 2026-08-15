# Vragen aan RIG-Cluster

Wat de CLI en de praktijkrondes tegenkomen en niet aan hun eigen kant kunnen oplossen. Eén
document, omdat de punten verspreid raakten over commit messages, `TODO.md` en de
bevindingen van losse rondes.

Alles hieronder is gemeten tegen `zad.sandbox.rijksapp.dev` op **14 augustus 2026**, met het
commando erbij zodat je het kunt nadoen. Waar we een voorstel doen is dat een voorstel, geen
ontwerp: jullie weten beter waar het hoort.

Volgorde is naar wat het ons kost, niet naar hoeveel werk het is.

| # | Punt | Kost ons |
|---|---|---|
| 11 | [Kortlevende projecttokens voor agents](#11) — *een voorstel, geen bug* | Een gelekte sleutel blijft geldig |
| 12 | [`approvals`: geen `enum` op `status`, en geen overzicht per project](#12) | Wij kunnen er niet op sturen |
| 1 | [Spec verandert zonder dat een client het kan zien](#1) | Verouderde hulp, tot een uur |
| ~~2~~ | ~~Geen PATCH op lijstvormige config~~ — *geleverd, zie onderaan* | — |
| 3 | [Invite-sleutel is niet terug te lezen](#3) | Tweede invite kost de eerste |
| 4 | [`X-Wake-Token` is ongedocumenteerd](#4) | Twee commando's die niemand kan gebruiken |
| 5 | [`user-env-vars` maskeert ook niet-geheime waarden](#5) | Je eigen waarde niet te controleren |
| ~~6~~ | ~~`restrict-access` legt zijn eis niet vast~~ — *geleverd, zie onderaan* | — |
| 7 | [Keycloak-realmblokkade heeft geen uitweg met projectrechten](#7) | Project onbruikbaar |
| 8 | [Attachment-inhoud is nergens te verifiëren](#8) | Mount niet aantoonbaar |
| 9 | [Twee `x-choices-source` zonder endpoint](#9) | Klein |
| 10 | [`authorization-wall` antwoordt 403, dat staat nergens](#10) | Klein |

---

## <a id="1"></a>1. De spec verandert zonder dat een client het kan zien

**Wat we zien.** `info.version` staat op `0.1.0` en is dat gebleven door alle wijzigingen van
deze week heen — ook toen vandaag de default van `sleep-mode.wake-mode` van `auto` naar
`manual` ging. De spec komt bovendien binnen zonder `ETag` en zonder `Last-Modified`:

```
$ curl -sSI https://zad.sandbox.rijksapp.dev/openapi.json | grep -i "etag\|last-modified"
(niets)
```

**Wat het kost.** De CLI leest de spec sinds vandaag live in plaats van uit de meegeleverde
kopie, want daar staat in wat een veld accepteert. Zonder enig signaal van verandering kan
hij alleen op tijd cachen: nu een uur. In dat uur vertelt hij `--help`-lezers de oude
waarheid — precies wat vandaag gebeurde met `wake-mode`.

**Wat we vragen.** Eén van deze drie is genoeg:

- `info.version` ophogen bij elke wijziging aan de spec (of een `x-spec-revision` met de
  commit-sha), of
- een `ETag` op `/openapi.json`, zodat een conditionele GET "onveranderd" kan antwoorden, of
- een `Last-Modified`.

Met een van de drie kan de cache op verandering in plaats van op tijd, en is de vertraging
nul.

## <a id="2"></a>2. Geen PATCH op lijstvormige config

**Wat we zien.** Drie config-blokken hebben een PATCH die één entry toevoegt of weghaalt:

```
attachments/config/component/{component_name}
persistent-storage/config/component/{component_name}
temp-storage/config/component/{component_name}
```

`invite.active`, `cross-domain-access.inbound`/`outbound` en `sleep-mode.match` zijn óók
lijsten, en hebben alleen een PUT.

**Wat het kost.** Een PUT schrijft het blok in zijn geheel, dus een entry toevoegen betekent
alle bestaande entries opnieuw meesturen. Dat is niet alleen omslachtig: wie het niet weet,
wist de rest. Een praktijkronde verloor zo `template=sso-only` op keycloak (dat is een
document, niet eens een lijst) en merkte het niet. De CLI waarschuwt er sinds vandaag voor,
maar waarschuwen is wat je doet als het probleem blijft bestaan.

**Wat we vragen.** Dezelfde `{add, remove}`-PATCH als bij attachments en storage, op
`invite`, `cross-domain-access` en `sleep-mode`. Dan kan `zadctl service config patch` daar
ook heen, en hoeft niemand een lijst over te typen om er één regel bij te zetten.

## <a id="3"></a>3. De invite-sleutel is niet terug te lezen

**Wat we zien.** Een aangemaakte invite komt terug met een lege sleutel:

```
$ zadctl -o json service config get invite
  key: ''   velden: ['key', 'contact-email']
```

**Wat het kost.** Dit was twee dingen tegelijk, en de helft is opgelost: sinds er een PATCH
op `active` staat, hoeft een tweede invite de eerste niet meer aan te raken, dus die sleutel
hoef je niet meer te kennen om iets toe te voegen. Wat overblijft: je kunt niet aantonen dat
een invite bruikbaar is, want de link *is* de sleutel. Wie hem is kwijtgeraakt kan hem
alleen vervangen.

**Wat we vragen.** De sleutel teruggeven aan wie de projectsleutel heeft — het is een
secret, maar wel hun eigen. Of, als dat bewust niet mag, dat ergens zeggen; dan is "een
invite maak je opnieuw aan" het antwoord en kunnen we dat in de CLI zetten in plaats van
een leeg veld te tonen.

## <a id="4"></a>4. `X-Wake-Token` is ongedocumenteerd

**Wat we zien.** De twee sleep-mode-endpoints weigeren een geldige projectsleutel:

```
$ zadctl service sleep-mode status productie
✗ Authentication failed (HTTP 401)
  X-Wake-Token header required
```

In de spec staat die header nergens: niet als parameter op
`/api/sleep-mode/{project_name}/{deployment_name}/status` of `/wake`, en er is geen
beschrijving die zegt waar zo'n token vandaan komt. Zoeken op "wake token" in de hele spec
levert niets op.

**Wat het kost.** De CLI heeft sinds vandaag `zadctl service sleep-mode status` en `wake`,
omdat een praktijkronde sleep-mode aanzette en niet kon laten zien dat het werkte. Ze
accepteren nu een `--wake-token`, maar niemand weet hoe je er een krijgt, dus in de praktijk
zijn ze onbruikbaar.

**Wat we vragen.** Of de projectsleutel toelaten op deze twee (een projecteigenaar mag zijn
eigen deployment toch wakker maken?), of documenteren waar een operator een wake-token
haalt. Als ze echt alleen voor de waker-pagina bedoeld zijn, is dát ook een antwoord — dan
halen we de commando's er weer uit en zeggen we waarom.

## <a id="5"></a>5. `user-env-vars` maskeert ook niet-geheime waarden

**Wat we zien.** Elke waarde komt terug als `***`, ook eentje die je zelf net zette:

```
$ zadctl -o json env list -c backend
{ "APP_MODE": "(set, not returned by the API)" }
```

Aliassen worden wél voluit teruggegeven.

**Wat het kost.** Je kunt niet controleren wat er staat. Een typefout in een niet-geheime
variabele is alleen zichtbaar door de workload zelf te ondervragen. Twee vrijwel identieke
features gedragen zich bovendien verschillend, wat de indruk wekt dat het een bug is.

**Wat we vragen.** Maskeer wat als secret gemarkeerd is, en geef de rest terug. Als het
onderscheid er nu niet is: een vlag per waarde bij het schrijven zou genoeg zijn.

## <a id="6"></a>6. `restrict-access` legt zijn eis niet vast in het schema

**Wat we zien.** `RestrictAccessConfig` heeft `enabled`, `role`, `realm-role` en
`error-message`, met `required` alleen op niets. Toch faalt de rollout met
"restrict-access.role or restrict-access.realm-role is required" zodra `enabled: true` staat
zonder rol.

**Wat het kost.** De CLI valideert een body tegen het schema vóór hij hem verstuurt, juist om
een gefaalde rollout te besparen. Die regel staat niet in het schema, dus hij laat hem door.
Wij gaan die eis niet in code zetten: dan bakken we een dienstnaam in de CLI, en dat is
precies wat deze CLI niet doet.

**Wat we vragen.** Druk het uit in het schema, bijvoorbeeld met een `anyOf` die bij
`enabled: true` één van beide rollen eist. Dan vangt niet alleen deze CLI het af, maar ook
de portal en elke andere client.

## <a id="7"></a>7. De Keycloak-realmblokkade heeft geen uitweg met projectrechten

**Wat we zien.** In project `vp-8bw` faalde een rollout, waarna elke volgende deterministisch
strandde op "Refusing to re-create ... admin user already exists in master realm". De
melding is uitstekend en noemt de remediëring — maar die vraagt rechten op de master-realm,
en een projectsleutel of SSO-gebruiker krijgt daar 403.

**Wat het kost.** Het project is onbruikbaar en blijft dat. De praktische uitweg was een
nieuw project aanmaken. Het inmiddels gezonde realm (well-known geeft 200) wordt door de
platformcheck niet gezien.

**Wat we vragen.** Een reparatiepad dat met projectrechten werkt: een endpoint dat de
realm-status opnieuw vaststelt, of dat het wachtwoord opnieuw zet. Desnoods iets dat alleen
een beheerder kan aanroepen — dan weten we tenminste naar wie we moeten doorverwijzen.

## <a id="8"></a>8. Attachment-inhoud is nergens te verifiëren

**Wat we zien.** De spec is er expliciet over: "An attachment's content lives in the
project's catalog and is never part of a read response." De koppeling is zichtbaar, de
inhoud niet.

**Wat het kost.** Of het bestand met de juiste inhoud op de mount staat, is via de API niet
vast te stellen — twee praktijkrondes noteerden dit als het enige dat ze niet konden
aantonen. Er is geen `exec` en geen leespad.

**Wat we vragen.** Geen inhoud: een `size` en een checksum (sha256) in de read-response van
de catalogus zijn genoeg om te zien dat wat er staat is wat je stuurde.

## <a id="9"></a>9. Twee `x-choices-source` zonder endpoint

**Wat we zien.** `x-choices-source` is een uitkomst: de CLI haalt er sinds vandaag de echte
waarden mee op (`waker-component` toont de componenten van je project). Twee ervan hebben
alleen een `description` en geen `endpoint`:

- `PublishOnWebDeploymentConfig.base-domain` — "de domeinen die het cluster ondersteunt"
- `LocalTargetPatch.port` — "de inkomende poorten van het ontvangende component, plus 4180"

**Wat het kost.** Weinig; die twee blijven een `<...>`-omschrijving in plaats van een lijst.

**Wat we vragen.** Als er een endpoint voor te maken is, graag. Zo niet, dan is dit geen
probleem — het staat hier voor de volledigheid.

## <a id="10"></a>10. `authorization-wall` antwoordt 403, en dat staat nergens

**Wat we zien.** Een component achter de muur geeft HTTP 403 met een inlogpagina, geen 302.
De servicebeschrijving ("wat wordt er ingesteld") zegt daar niets over.

**Wat het kost.** Wie met curl of een healthcheck wil aantonen dat een deployment leeft,
controleert op 200 en concludeert dat het stuk is.

**Wat we vragen.** Eén zin in de beschrijving van de dienst. Die tekst komt uit de registry,
dus hij landt vanzelf in `zadctl service describe authorization-wall`.

## <a id="12"></a>12. `approvals`: geen `enum` op `status`, en geen overzicht per project

Eerst de complimenten: `approvals` is precies wat er miste. Een deployment die een domein
claimt wacht op een oordeel, en zonder dit veld is "er verschijnt geen ingress" het eerste
dat iemand ervan merkt — op een deployment die Healthy heet. Dat het veld een `text`
meestuurt met wat het betekent, inclusief het gevolg, is beter dan wat wij er ooit van
hadden kunnen maken: die zin tonen we nu letterlijk, na elke mutatie en in
`deployment describe`.

Twee dingen kunnen we er niet uit afleiden.

**`status` heeft geen `enum`.** De beschrijving noemt `requested`, `denied` en `none`, maar
het schema zegt alleen `string`. Wij willen erop kunnen sturen — een afgewezen aanvraag is
iets anders dan een lopende, en `--strict` in een pijplijn zou op de eerste wel moeten
falen en op de tweede niet. Nu doen we dat bewust niet: op drie strings vertakken die de
spec niet belooft, is stil kapotgaan zodra er een vierde bijkomt. Zet er een `enum` op (en
desnoods `x-choices` met labels) en we kunnen het onderscheid maken.

**Er is geen overzicht per project.** `approvals` staat op een deployment en op het
resultaat van een schrijfactie. Wie wil weten waar zijn project op wacht, moet elke
deployment apart opvragen. Een veld op `project status`, of een
`GET /api/v2/projects/{project_name}/approvals`, zou dat één commando maken.

Wat we níet vragen: een endpoint om goed te keuren. Dat is een beheerdersfunctie en die
hoort niet in deze CLI.

## <a id="11"></a>11. Kortlevende projecttokens voor agents

Dit is een voorstel en geen bug, en het is het enige punt hier waar we zelf iets van willen
dat er nog niet is.

**Wat we zien.** Een projectsleutel verloopt niet en is niet in te trekken. Hij komt boven
water bij `project create` en bij `project list` (voor de rollen owner en admin), en daarna
leeft hij in een bestand op iemands laptop. Dat was werkbaar toen er mensen achter zaten.

**Wat het kost.** zadctl wordt in toenemende mate door agents gedraaid, en een agent leest
bestanden, plakt uitvoer in transcripten en logt dingen die later door iemand anders gelezen
worden. Eén ongelukje en er staat een sleutel die het over een maand nog doet, waar niemand
iets aan kan doen: er is geen intrekpad en geen manier om te zien welke sleutels uitstaan.

We hebben aan onze kant zitten kijken naar het versleutelen van de sleutel in het env-
bestand. Dat hebben we bewust laten liggen: de code die ontsleutelt is open source en draait
als dezelfde gebruiker als de agent, dus het is obfuscatie die zichzelf aan de eerste lezer
uitlegt. Het probleem is niet waar de sleutel ligt maar hoe lang hij geldig is, en dat kan
alleen aan jullie kant.

**Wat we vragen.** Een gedelegeerd, kortlevend projecttoken, uitgegeven op een geldige
SSO-sessie:

```
POST /api/v2/projects/{project_name}/tokens
  { "ttl": "8h", "scope": "read-only" }
→ { "token": "...", "expires_at": "2026-08-15T17:00:00Z", "id": "tok_..." }
```

Vier dingen die het voor ons bruikbaar maken, in volgorde van belang:

1. **Een vervalmoment in het antwoord.** Dan kan de CLI "verloopt over 3 uur" zeggen in
   plaats van het te ontdekken bij een 401. De machinerie daarvoor staat er al: het
   SSO-token wordt zo al behandeld.
2. **Intrekken en opsommen.** Dat is precies wat een vaste projectsleutel vandaag niet
   heeft. Lekt er een, dan is er nu geen knop. Voor tokens die je vaker uitdeelt is dat het
   verschil tussen een incident en een middag.
3. **Alleen-lezen als scope.** Veel agentwerk is kijken, niet schrijven. Een token dat niets
   kan veranderen is een andere risicocategorie dan een token dat kort geldig is.
4. **Een maximum-TTL per project**, zodat een beheerder kan zeggen "bij ons nooit langer dan
   een dienst".

**Waar dat in de CLI landt: bij het kiezen van een project, niet bij het inloggen.** Een
token is per project, en `zadctl login` weet nog niet welk project je gaat gebruiken. Het
moment waarop vandaag een projectsleutel binnenkomt is `zadctl project use <naam>` -- dat
haalt de projectenlijst op met je SSO-token en schrijft de sleutel van dat ene project weg.
Daar hoort dit dus ook: `zadctl project use <naam> --agent` (of standaard, als een project
zo is ingesteld) vraagt een kortlevend token voor dat project in plaats van de vaste
sleutel.

Twee dingen die daaruit volgen en die het endpoint moet ondersteunen:

- **Opnieuw uitgeven zonder opnieuw kiezen.** Verloopt het token, dan moet de CLI met de
  bestaande SSO-sessie een nieuw token voor hetzelfde project kunnen halen. Anders is een
  agent halverwege zijn werk stuk, en dat is precies wanneer niemand er is om in te loggen.
- **Meerdere projecten naast elkaar.** Twee mappen, twee projecten, twee tokens, elk met een
  eigen vervalmoment. Dat past in wat er staat -- het env-bestand houdt project, sleutel en
  API-URL al bij elkaar -- maar het betekent wel dat een token aan een project hangt en niet
  aan een sessie.

**Wat wij dan bouwen.** Weinig, en dat is het punt: een vlag op `project use`, het token met
zijn vervalmoment ernaast in het env-bestand, en dezelfde diagnose als bij een verlopen
SSO-token. CI verandert niet -- daar blijft een vaste projectsleutel in de omgeving staan,
want daar is geen mens om in te loggen. En we hoeven niets te versleutelen, wat ook betekent
dat het bestand leesbaar blijft wanneer er iets misgaat.

---

## Al opgelost, met dank

Zodat niemand hier werk overdoet. Alles hieronder is deze week geland en nagemeten:

- **`x-choices` op een dozijn velden**, met een label per waarde. De CLI toont ze sinds
  vandaag; `sleep-after-deploy` was daarvoor `<text>` en is nu een keuzelijst.
- **`x-choices-source`**, waarmee projectafhankelijke velden hun echte waarden krijgen.
- **`examples` op `sleep-mode.match`** — precies het veld waarvan niemand kon raden wat er
  in moest.
- **De beschrijving van `attachments` zegt nu 64 KB** in plaats van 256 KB, wat overeenkomt
  met wat de API afdwingt.
- **`add_services` en `remove_services` op `component update`**, waarmee een dienst binden
  niet langer de andere ontbindt.
- **PATCH op de lijsten die er geen hadden** (punt 2): `invite/config/project/active`,
  `sleep-mode/config/project/match` en de twee richtingen van `cross-domain-access`. Dezelfde
  `{add, remove}`-vorm als bij attachments en storage, maar één niveau dieper: op de naam van
  het veld. `zadctl service config patch --field <naam>` vindt ze door te kijken, dus de
  vierde werkt de dag dat hij landt. De waarschuwing bij `config set` wijst er nu ook heen.
- **`RestrictAccessConfig` legt zijn eis vast** (punt 6) met een `anyOf`. Wordt sindsdien
  hier afgevangen in plaats van door een gefaalde rollout -- al moesten we daarvoor wel eerst
  onze eigen validatie op de live spec aansluiten in plaats van op de meegeleverde kopie.
- **`x-platform-managed`** op `keycloak.realms`, waarmee onze waarschuwing over wat een
  `set` weggooit dat veld niet meer als slachtoffer noemt.
- **`approvals`**, met een `text` die zegt wat het voor deze deployment betekent. Die zin
  tonen we letterlijk, na elke mutatie en in `deployment describe`.
- **De uitleg boven aan de spec over `enum` versus `x-choices`.** Die heeft direct een fout
  in deze CLI rechtgezet: we presenteerden een menu als een gesloten lijst, waardoor `90m`
  bij `sleep-after-deploy` ongeldig leek.
