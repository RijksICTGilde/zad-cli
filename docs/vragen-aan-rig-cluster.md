# Vragen aan RIG-Cluster

Wat de CLI en de praktijkrondes tegenkomen en niet aan hun eigen kant kunnen oplossen. **Eén
document**, en dat is sinds 17 augustus letterlijk zo: er lag een korte versie naast met
dezelfde punten erin, en elke wijziging moest dus op twee plekken. Dat ging één keer mis en
toen was het duidelijk genoeg.

De tabel hieronder *is* de korte versie: wat er open staat, wat het ons kost, en of het een
antwoord van jullie nodig heeft. Elk punt staat daaronder één keer uitgeschreven, met de
meting en het commando erbij zodat je het kunt nadoen. Wat geleverd is blijft staan, met een
streep erdoor en wat de hermeting opleverde — dat is de geschiedenis, en die kost niets zolang
hij op dezelfde plek staat als de rest.

Waar we een voorstel doen is dat een voorstel, geen ontwerp: jullie weten beter waar het hoort.
Alles is gemeten tegen `zad.sandbox.rijksapp.dev` tussen **14 en 17 augustus 2026**.

**Als er tijd is voor één ding:** punt 17 (waar draait hij terwijl het domein wacht) en het
gesprek over kortlevende tokens. De andere twee vragen met een `?` zijn op 17 augustus
beantwoord en staan hieronder doorgestreept: `__custom__` gaat uit de keuzelijst, en
`default-domain` zegt welk domein zonder goedkeuring in gebruik gaat. De sandbox draait met
skaffold, dus alles hieronder staat er zodra het gecommit is; hermeten kan meteen.

| # | Punt | Antwoord | Kost ons |
|---|---|---|---|
| 17 | [Bij een aangevraagd domein is het werkende adres onvindbaar](#17) | half | Je weet niet waar het draait |
| 11 | [Kortlevende projecttokens voor agents](#11) | gesprek | Een gelekte sleutel blijft geldig |
| 7 | [Keycloak-realmblokkade heeft geen uitweg met projectrechten](#7) | | Project onbruikbaar |
| 8 | [Attachment-inhoud is nergens te verifiëren](#8) | | Mount niet aantoonbaar |
| 12 | [`approvals`: geen overzicht per project](#12) | | Alleen zichtbaar per deployment |
| 13 | [`active` is enkelvoudig bij lezen en een lijst bij patchen](#13) | | Twee normale commando's en de read weigert |
| ~~9~~ | ~~Vier `x-choices-source` zonder endpoint~~ — *vier bronnen wijzen nu een endpoint aan, plus `supports-dots`* | — | — |
| ~~10~~ | ~~`authorization-wall` antwoordt 403, dat staat nergens~~ — *staat in de dienstbeschrijving* | — | — |
| ~~18~~ | ~~De beschrijving van `invite` noemt andere velden dan het schema~~ — *rechtgezet op het veld zelf* | — | — |
| ~~23~~ | ~~`base_domain` mist de bron die `domain-format` wél kreeg~~ — *de keuzebron geldt nu op elk model* | — | — |
| ~~24~~ | ~~Twee gelijktijdige writes tellen verschillend~~ — *`pending_rollout` op de afgeronde taak* | — | — |
| ~~16~~ | ~~`__custom__` staat in de keuzelijst en wordt geweigerd~~ — *sentinel eruit, uitleg erin* | — | — |
| ~~21~~ | ~~De domeinlijst zegt niet welk domein direct mag~~ — *`default-domain` geleverd* | — | — |
| ~~5~~ | ~~`user-env-vars` maskeert ook niet-geheime waarden~~ — *besloten: teruglezen kan niet, met reden* | — | — |
| ~~26~~ | ~~Een gefaalde taak zegt niet van wie de fout is~~ — *`InvalidInput` geleverd, exit 1 gemeten* | — | — |
| ~~26b~~ | ~~Zeven `*Result`-schema's missen `error_category`~~ — *alle vijftien dragen hem, ook de gooiende taken* | — | — |
| ~~27~~ | ~~De storage-beschrijving noemt een default die niet de default is~~ — *bijgetrokken, plus een plafond van 1Gi* | — | — |
| ~~28~~ | ~~`minio-storage` markeert velden als verplicht die dat niet zijn~~ — *`x-platform-managed` geleverd* | — | — |
| ~~29~~ | ~~Wat garandeert `check-subdomain` precies?~~ — *`cluster_domain` geleverd* | — | — |
| ~~22~~ | ~~Vijf attachment-endpoints kennen `rollout` niet~~ | — | — |
| ~~25~~ | ~~`sleep-mode status` zegt `starting`~~ — *`sleep_state` geleverd* | — | — |
| ~~19~~ | ~~`POST /services` bindt niet als de dienst er al is~~ | — | — |
| ~~20~~ | ~~`check-subdomain` antwoordt 404 op alles~~ — *verhuisd onder het project* | — | — |
| ~~15~~ | ~~`check-subdomain` eist een parameter die nergens staat~~ — *zie 20* | — | — |
| ~~14~~ | ~~`PUT` op de storage-config geeft 500~~ | — | — |
| ~~1~~ | ~~Spec verandert zonder dat een client het kan zien~~ — *`ETag` geleverd* | — | — |
| ~~2~~ | ~~Geen PATCH op lijstvormige config~~ | — | — |
| ~~3~~ | ~~Invite-sleutel niet terug te lezen~~ — *mét een generator* | — | — |
| ~~4~~ | ~~`X-Wake-Token` is ongedocumenteerd~~ — *de projectsleutel volstaat* | — | — |
| ~~6~~ | ~~`restrict-access` legt zijn eis niet vast~~ | — | — |

Zes open, vierentwintig afgehandeld (geleverd of beslist). Dat tweede getal is de reden dat dit
document werkt.

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
op `active` staat, hoeft een tweede invite de eerste niet meer aan te raken. Wat overblijft
is de kern: **de code is de invite.** Je nodigt iemand uit door hem die link te sturen, dus
een projectbeheerder die hem niet kan opvragen kan de uitnodiging niet versturen — alleen
vervangen door een nieuwe, waarmee de vorige ongeldig wordt terwijl er misschien iemand mee
onderweg is.

En het is niet een geheim in de gebruikelijke zin. Wie de link heeft kan hem inwisselen, dus
hij is precies zo geheim als het kanaal waarover je hem stuurt. Voor de eigenaar van het
project verbergen beschermt niemand: die heeft de projectsleutel al, waarmee hij de invite
kan overschrijven, de rollen kan veranderen en de hele dienst kan uitzetten.

**Wat we vragen.** Geef de code terug aan wie de projectsleutel heeft. Drie vormen, in
volgorde van voorkeur:

1. Gewoon in het antwoord van `GET .../services/invite/config`, zoals aliassen ook voluit
   terugkomen. Dan werkt `zadctl service config get invite` en is er verder niets nodig.
2. Achter een eigen aanroep, als het uit de gewone read moet blijven —
   `GET .../services/invite/config/project/active/key` of iets in die geest. Dan kan een
   audit onderscheiden "iemand las de config" van "iemand haalde de link op".
3. Eenmalig bij het aanmaken, zoals de projectsleutel zelf. Minder fijn (wie hem daar mist
   is hem kwijt), maar beter dan nu.

**Klein, uit dezelfde hoek.** `active` is bij de PUT één entry (`InviteConfigSingular`,
"presents that list as a single entry") en bij de PATCH een lijst (`add`/`remove`). Dat
levert twee spellingen op voor hetzelfde veld: `--set active.key=...` om te schrijven,
`--set add[0].key=...` om te patchen. Wij volgen allebei omdat we het schema volgen, maar
iemand die tussen die twee commando's wisselt struikelt erover.

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

## <a id="5"></a>5. ~~`user-env-vars` maskeert ook niet-geheime waarden~~ — besloten, en het antwoord is nee

**Beslist op 15 augustus, en het is een keer heen en weer gegaan.** Er is een markering per
waarde gebouwd (een veld `public` op de schrijfbodies, zodat een niet-geheime variabele
teruggelezen kon worden) en die is er daarna bewust weer uitgehaald. De reden: een
omgevingsvariabele kán een geheim bevatten, en een leespad is voor een geautomatiseerde client
die het aangepraat krijgt net zo makkelijk te bereiken als voor de eigenaar van het project.
Het gemak van teruglezen weegt daar niet tegenop. Er is dus geen vlag, geen queryparameter en
geen uitzondering per waarde: zetten en wijzigen kan, teruglezen niet. Er staat nu een toets
die vastlegt dat die weg er niet is, zodat hij niet per ongeluk terugkomt.

**Het verschil met aliassen is geen inconsistentie**, en dat was jullie eigenlijke vraag. Een
alias is een verwijzing naar een platformvariabele: de waarde ís de koppeling, dus geen
geheim, en maskeren zou juist verbergen waar de lezer naar vroeg. Een aliaswaarde die geen
verwijzing is, blijft wel gemaskeerd.

De API zegt dit nu zelf, op de plek waar jullie het tegenkomen: in de beschrijving van het
leesendpoint en in die van het veld dat `***` teruggeeft, met het verschil met aliassen erbij.
Dus `zadctl env list` kan die zin letterlijk doorgeven in plaats van dat het op een bug lijkt.

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

## <a id="9"></a>9. ~~Vier `x-choices-source` zonder endpoint~~ — opgeleverd

**Opgeleverd op 17 augustus. Alle vier wijzen nu een endpoint aan**, dus er blijft geen
`<...>`-omschrijving meer over waar een lijst hoort:

| Veld | Endpoint | Pad in het antwoord |
|---|---|---|
| `LocalTargetPatch.port`, `PeerTargetPatch.port` | `GET /v2/projects/{p}/components` | `components[].ports` |
| `InviteEntry.auth-methods` | `GET /v2/projects/{p}/services/keycloak/config` | `configurations[].config.template` |
| `PublishOnWebDeploymentConfig.domain-format` | `GET /v2/projects/{p}/clusters` | `clusters[].base-domains[].supports-dots` |

Die laatste vroeg iets nieuws en dat is er meteen bij gekomen: **`supports-dots` per domein in
de clusterlijst**. De regel achter `domain-format` (de streepjes-varianten kunnen altijd, de
punt-varianten alleen op een domein dat losse subdomeinen met punten aankan) stond wel
beschreven maar was nergens uit af te leiden, dus moest je hem overslaan of gokken. Nu is hij
te berekenen.

**Wat we zagen.** `x-choices-source` is een uitkomst: de CLI haalt er sinds vandaag de echte
waarden mee op (`waker-component` toont de componenten van je project). Twee ervan hebben
alleen een `description` en geen `endpoint`:

- `PublishOnWebDeploymentConfig.base-domain` — "de domeinen die het cluster ondersteunt"
- `LocalTargetPatch.port` — "de inkomende poorten van het ontvangende component, plus 4180"

**Wat het kost.** Weinig; die twee blijven een `<...>`-omschrijving in plaats van een lijst.

**Wat we vragen.** Als er een endpoint voor te maken is, graag. Zo niet, dan is dit geen
probleem — het staat hier voor de volledigheid.

## <a id="10"></a>10. ~~`authorization-wall` antwoordt 403, en dat staat nergens~~ — opgeleverd

**Opgeleverd op 17 augustus.** Het staat nu in de beschrijving van de dienst, dus het komt
vanzelf mee in `zadctl service describe authorization-wall`, met het gevolg erbij dat jullie
noemden: wie op 200 controleert leest de 403 als een kapotte applicatie, terwijl het juist het
teken is dat de muur staat.

**Wat we zagen.** Een component achter de muur geeft HTTP 403 met een inlogpagina, geen 302.
De servicebeschrijving ("wat wordt er ingesteld") zegt daar niets over.

**Wat het kost.** Wie met curl of een healthcheck wil aantonen dat een deployment leeft,
controleert op 200 en concludeert dat het stuk is.

**Wat we vragen.** Eén zin in de beschrijving van de dienst. Die tekst komt uit de registry,
dus hij landt vanzelf in `zadctl service describe authorization-wall`.

## <a id="15"></a>15. `check-subdomain` eist een parameter die nergens staat

**Wat we zien.** Het commando doet precies wat de spec beschrijft en krijgt een 401:

```
$ zadctl project check-subdomain rig-test opa-rijks.nl
--> GET /api/subdomains/check/rig-test?base_domain=opa-rijks.nl
✗ 401 — Missing project_name parameter
```

De spec kent op dat pad twee parameters: `subdomain` in het pad en `base_domain` in de
query. `project_name` staat er niet, en meesturen als queryparameter helpt niet — we hebben
het geprobeerd, met dezelfde 401 als antwoord.

**Wat het kost.** Het commando is onbruikbaar, en wij kunnen het niet repareren door te
raden waar die parameter heen moet.

**Wat we vragen.** Zeg waar hij hoort (query, header, pad) en zet hem in de spec — of laat
hem vallen als de projectsleutel al genoeg zegt. Dat laatste lijkt ons logischer: elke andere
aanroep leidt het project uit de sleutel af.

## <a id="16"></a>16. ~~`__custom__` staat in de keuzelijst en wordt geweigerd~~ — opgeleverd

**Opgeleverd op 16 augustus, 's avonds; staat op de sandbox.** Jullie lazen het goed: `__custom__` hoorde daar niet. Het is een schakelaar
in het FORMULIER, geen waarde in de API. In de wizard betekent hij "ik vul zelf een domein in"
en zet hij een tweede, tijdelijk veld aan waar het echte domein in gaat; bij het opslaan wordt
de sentinel door dat domein vervangen. Dat tweede veld bestaat alleen in het formulier, het
configmodel weigert het, dus een API-client kon de schakelaar wel zetten en nooit invullen.

Hij gaat er dus uit op de twee plekken waar de API hem publiceerde: `GET /projects/{p}/clusters`
en de `x-choices-source` van het veld zelf. Het formulier houdt hem. In plaats daarvan zeggen
het veld, de keuzebron en de clusterlijst nu alle drie hoe het wel moet: **schrijf de
domeinnaam zelf in `base-domain`**, het hoeft er geen te zijn die het cluster aanbiedt. Dat
was precies de ontdekking die nergens stond.

De naam staat nu als `CUSTOM_DOMAIN_SENTINEL` bij de providers, zodat wat de API publiceert
hem bij naam kan overslaan in plaats van per ongeluk opnieuw. Een sweep over de andere
keuzelijsten leverde geen tweede sentinel op die in het OpenAPI-document terechtkomt.

**Nog één restje weggehaald op 17 augustus, en met dank voor de opmerking.** Hij stond nog in
één beschrijving, die van de clusterlijst, met de uitleg dat het een schakelaar in het
formulier is. Dat was verkeerd om dezelfde reden als de keuzelijst zelf: een client kan met
een formulierdetail niets, en een sentinel bij naam noemen in een contract nodigt uit om hem
alsnog te sturen. De uitleg staat nu in de code en de naam komt **nergens meer in het
OpenAPI-document voor**, vastgelegd met een toets die het hele document afzoekt. Wat er wel
staat is wat je nodig hebt: schrijf de domeinnaam zelf in `base-domain`.

**Wat we zien.** De keuzelijst voor `base-domain` (via `x-choices-source`) biedt
`__custom__` aan. Wie dat kiest krijgt bij de rollout: *"'__custom__' is geen ondersteund
base domain"*. Een eigen domein als gewone tekstwaarde invullen (`mijn-webshop-test.nl`)
werkt wél, maar dat is nergens te ontdekken.

**Wat het kost.** De enige aanwijzing dat een eigen domein kan, is een waarde die niet werkt.
Wij tonen die lijst zoals hij binnenkomt, dus wij geven die sentinel door.

**Wat we vragen.** Of `__custom__` uit de lijst halen en in de beschrijving zetten dat je hier
je eigen domein intypt, of hem in `x-choices` een `title` geven die dat zegt en de
foutmelding laten uitleggen wat je in plaats daarvan invult.

## <a id="17"></a>17. Bij een aangevraagd domein is het werkende adres onvindbaar

**Half beantwoord op 17 augustus, en de helft die er is haalt jullie van de blokkade af.**
Waar hij draait terwijl de aanvraag wacht, staat nu vast en is opvraagbaar: op het
`default-domain` van het cluster, uit `GET /projects/{p}/clusters` (zie punt 21). Die regel
staat in de beschrijving van dat veld, dus het is geen afleiding meer maar een uitspraak van
het platform.

**Wat er niet is, en dat blijft staan:** de samengestelde URL. Uit `default-domain` alleen kun
je het adres niet opbouwen zonder ook `domain-format` en de componentnaam mee te wegen, en dat
is precies het rekenwerk dat bij ons hoort en niet bij jullie. Dus dit punt blijft open, met
een kleinere vraag dan hij had: niet "waar draait hij", maar "zet die ene samengestelde URL
erbij in `urls`".

**Wat we zien.** Na het instellen van een eigen domein zegt `deployment describe` netjes dat
het is aangevraagd en dat de deployment daarom op het standaard clusteradres bereikbaar is —
maar `urls` bevat alleen het aangevraagde adres, dat nog niet resolvet. Het adres waar hij
wél op staat, staat nergens.

**Wat het kost.** Precies in de situatie waarin je wilt controleren of je applicatie draait,
is de werkende URL het enige dat ontbreekt. Wij kunnen hem niet afleiden: welk clusteradres
erbij hoort weet het platform.

**Wat we vragen.** Zet ze allebei in `urls`, of geef het werkende adres een eigen veld met
een naam die zegt wat het is. De goedkeuringsmelding weet het al; hij noemt het alleen niet.

## <a id="18"></a>18. ~~De beschrijving van `invite` noemt andere velden dan het schema~~ — opgeleverd

**Opgeleverd op 17 augustus, en op een andere plek dan jullie vroegen.** De registrytekst is
de UITLEG die ook in de portal staat, en daar is "via de API krijg je dit als één entry
terug" een vreemde eend: die lezer heeft geen API. De correctie hoort bij het veld, en daar
staat hij nu, in de beschrijving van `active`: dat het over de API één entry is en geen
lijst, dat je een tweede met de PATCH toevoegt, en dat rollen in `realm-roles` gaan terwijl
`roles` de oude spelling is die alleen nog bestaat zodat oudere projectbestanden blijven
valideren.

Daarmee leest `service describe` het uit het schema in plaats van uit een tekst die het
elders ook moet doen. Dat er voor echt API-specifieke uitleg misschien een eigen plek moet
komen is een open vraag aan onze kant; voor dit geval was het veld het antwoord.

**Wat we zagen.** `service describe invite` beschrijft een lijststructuur met een veld
`roles`; het schema kent `active` (één entry) plus `default-language`, en markeert `roles`
als vervangen door `realm-roles`.

**Wat het kost.** De beschrijving is voor een lezer het eerste antwoord, en hier stuurt hij
naar velden die niet bestaan. Wij tonen allebei uit dezelfde bron, dus wij kunnen het
verschil niet gladstrijken.

**Wat we vragen.** De tekst in de registry bijwerken naar wat het schema zegt.

## <a id="14"></a>14. ~~`PUT` op de storage-config geeft 500~~ — over

**Over sinds 16 augustus.** Draaiboek 01 loopt weer helemaal door, 44 van de 44, en stap 16
is precies de `PUT` die faalde. Het bewijs staat niet bij de schrijfactie maar aan de andere
kant: stap 42 haalt `/api/status` op bij de draaiende workload en eist
`.services["storage-data"].ok == true`, dus het volume is niet alleen geaccepteerd maar ook
gemount. Er is aan onze kant niets veranderd tussen de mislukte en de geslaagde ronde. Wat
hieronder stond laten we staan voor het geval het terugkomt.

**Wat we zagen.** Op 15 augustus, tegen de sandbox, met een body die exact het schema volgt:

```
PUT /api/v2/projects/p1-slp/services/persistent-storage/config/component/api
    [{"name": "data", "size": "1Gi", "mount-path": "/data"}]
→ 500 Internal Server Error   (drie keer geprobeerd, ook met rollout=true)

PATCH /api/v2/projects/p1-slp/services/persistent-storage/config/component/api
    {"add": [{"name": "data", "size": "1Gi", "mount-path": "/data"}]}
→ 200, wijziging opgeslagen
```

Zelfde entry, zelfde component, zelfde moment. `temp-storage` doet hetzelfde, dus het zit
niet in één dienst. `StorageEntry` vraagt `name`, `size` en `mount-path` en die zitten er
alle drie in; een fout in de body hadden we als 422 verwacht, niet als 500.

**Wat het kostte.** Playbook 01 — ons eigen draaiboek dat de CLI van begin tot eind uitoefent —
strandde erop, de enige stap die faalde en de eerste keer sinds 12 augustus dat die niet
doorliep.

**Wat we vroegen.** Kijken wat daar omviel. Als iemand weet wat het was: één zin daarover is
het verschil tussen "opgelost" en "vanzelf overgegaan", en dat laatste kan terugkomen.

## <a id="13"></a>13. `active` is enkelvoudig bij lezen en een lijst bij patchen

**Wat we zien.** Twee gewone commando's brengen een project in een stand waarin de read
weigert. Wij deden dit, in deze volgorde, om te controleren of de invitecode terugkomt:

```
$ zadctl service config patch invite --set 'add[0].key=' --set 'add[0].contact-email=test@…'
  → updated: 1   (de bestaande entry had sleutel "", dus die werd vervangen)

$ zadctl service config patch invite --set 'add[0].key=' --set 'add[0].contact-email=admin@…'
  → toegevoegd  (de eerste heeft nu een gegenereerde sleutel, dus er matchte niets)

$ zadctl service config get invite
  ✗ Conflict (HTTP 409): 'active' of service 'invite' holds 2 entries at target 'project',
    but this API presents it as a single entry.
```

De 409 legt keurig uit wat er aan de hand is en hoe je eruit komt — dank daarvoor. Maar de
route erheen is niet exotisch: twee keer een entry toevoegen met een lege sleutel, wat
allebei keer een geldige aanroep is.

**Wat het kost.** De PUT accepteert één entry, de PATCH voegt er onbeperkt toe, en pas de
volgende read zegt dat die twee elkaar bijten. Wie het overkomt kan zijn config niet meer
lezen tot hij raadt welke sleutel hij moet weghalen — en die sleutels zijn nou net wat de
read hem zou vertellen.

**Wat we vragen.** Één van tweeën, en jullie weten beter welke bij het portal past: laat de
PATCH weigeren zodra er een tweede entry bij zou komen zolang `active` enkelvoudig is (dan
komt de fout waar de handeling is), of haal `active` uit `api_singular_lists` zodat de read
gewoon een lijst teruggeeft.

## <a id="12"></a>12. `approvals`: geen overzicht per project

Eerst de complimenten: `approvals` is precies wat er miste. Een deployment die een domein
claimt wacht op een oordeel, en zonder dit veld is "er verschijnt geen ingress" het eerste
dat iemand ervan merkt — op een deployment die Healthy heet. Dat het veld een `text`
meestuurt met wat het betekent, inclusief het gevolg, is beter dan wat wij er ooit van
hadden kunnen maken: die zin tonen we nu letterlijk, na elke mutatie en in
`deployment describe`.

Twee dingen kunnen we er niet uit afleiden.

*`status` heeft inmiddels een `enum` (`none | requested | denied`) en `--strict` faalt sinds
vandaag op een afgewezen aanvraag en zwijgt over een lopende. Dank.*

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

## <a id="19"></a>19. ~~`POST /services` met `components` doet niets zodra de dienst er al is~~ — opgelost

**Opgelost op 16 augustus, dezelfde avond.** De beschrijving zegt het nu ook: *"A service
that is already selected at project level is reported in `services_skipped` and its
components are bound all the same, so configure-then-bind works in either order."* Nagemeten
voordat we onze omweg weghaalden — een kale `POST /services` met `components: ["worker"]` op
een dienst die al op het project stond, en `worker` had hem daarna. Dank; dit was de
zwaarste van de ronde.

Wij hebben de omweg (binden via `add_services` per component) weer verwijderd: één aanroep in
plaats van N+1, en het draaiboek bewaakt het nu met een stap die na het binden `component
list` naleest in plaats van het antwoord te geloven.

**Wat we zagen.** Twee aanroepen van hetzelfde commando, in één wegwerpproject, met
`rollout=false` zodat er niets aan het cluster lag:

```
POST /api/v2/projects/ap-dio/services   {"service": "health-check", "components": ["web"]}
→ services_added: ["health-check"], components_updated: ["web"]
   GET .../components → web: ["health-check"]                              ✔

POST /api/v2/projects/ap-dio/services   {"service": "health-check", "components": ["api"]}
→ services_skipped: ["health-check"], components_updated: ["api"]
   warnings: ["Service 'health-check' already exists on the project"]
   GET .../components → api: []                                            ✘
```

De tweede aanroep meldt `components_updated: ["api"]` en raakt `api` niet aan. Het lijkt
erop dat de hele request wordt afgekort zodra de dienst al op projectniveau geselecteerd is,
terwijl het antwoord de componentnamen uit de *request* teruggeeft in plaats van wat er
gebeurd is. Het is niet dienstspecifiek: gemeten met `health-check` en `metrics-scraper`, en
een praktijkronde liep er op `authorization-wall` in.

**Wat het kost.** Die tweede vorm is de gewone vorm. Je configureert een dienst en bindt hem
daarna, dus vrijwel iedereen zit in de kapotte tak. De ronde van 16 augustus kreeg `success`,
`components updated: frontend`, geen binding, en een publieke URL die 200 antwoordde terwijl
er een authorization-wall voor had moeten staan. Dat is precies het soort fout dat niemand
opmerkt, want alles zegt dat het goed ging.

**Wat er nog van overblijft.** Eén vraag, en die is klein geworden nu de binding werkt:
vult `components_updated` zich met wat er werkelijk is bijgewerkt, of met de namen uit de
request? Zolang beide hetzelfde zijn merkt niemand het verschil, maar het is het veld waarmee
een client zou willen controleren, en dat kan alleen als het over de werkelijkheid gaat.

## <a id="20"></a>20. ~~`check-subdomain` antwoordt 404 op alles~~ — opgelost

**Opgelost op 16 augustus**, samen met punt 15, en op de manier die wij niet hadden kunnen
raden: het endpoint is verhuisd naar `GET /api/v2/projects/{project_name}/subdomains/check/{subdomain}`.
De projectnaam in het pad is precies wat het liet werken — `validate_api_token` legitimeert de
sleutel tegen het project dat in de *route* staat, dus zonder die parameter was elk antwoord
een weigering. Nagemeten: `keycloak` op `sandbox.rijksapp.dev` is bezet, een vrije naam is
vrij. De CLI vraagt sinds vandaag om een project en heeft de noodmelding weer weggehaald.

**Wat we zagen.** Punt 15 was een 401 "Missing project_name parameter". Daarna een 404, op
elke naam:

```
GET /api/subdomains/check/zad?base_domain=sandbox.rijksapp.dev       → 404 {"detail":"Not Found"}
GET /api/subdomains/check/keycloak?base_domain=sandbox.rijksapp.dev  → 404
GET /api/subdomains/check/vlam-test?base_domain=sandbox.rijksapp.dev → 404
```

`zad` en `keycloak` bestaan gegarandeerd op dat domein, dus dit is geen uitspraak over de
naam.

**Wat het kost.** Een commando dat "niet beschikbaar" en "endpoint weg" niet uit elkaar houdt,
is erger dan geen commando: een script leest de niet-nul afsluiting als "kies een andere naam".
Wij vangen het sinds vandaag af en zeggen dat het antwoord onbruikbaar is (exit 2, platform),
maar dat is een pleister.

**Wat we vragen.** Of het endpoint terug is, of dat het weg mag. Beide antwoorden kunnen wij
verwerken; wat niet kan is dit.

## <a id="21"></a>21. ~~De domeinlijst zegt niet welk domein direct mag~~ — opgeleverd

**Opgeleverd op 16 augustus, 's avonds; staat op de sandbox.**
`GET /projects/{p}/clusters` draagt nu **`default-domain`** naast
`base-domains`, met de regel in de beschrijving: dat is het enige domein dat zonder
goedkeuring in gebruik gaat. `base-domain` leeg laten of precies die waarde zetten geeft
meteen het adres dat je vraagt; elke andere waarde levert een goedkeuringsaanvraag op, ook
een domein dat gewoon in `base-domains` staat. Dat was jullie waarneming: de twee gevallen
zien er in die lijst identiek uit, en dit is het veld waarop je ze uit elkaar houdt.

**Bewust niet de vorm die jullie voorstelden**, dus zeg het als het knelt. Een
`requires-approval` per optie is een oordeel, en dat oordeel kan de stand van dit project
meewegen (een domein dat hier al goedgekeurd is, is voor dit project geen aanvraag meer en
voor het buurproject wel). Die semantiek vastleggen in een booleaan per optie legt een keuze
vast die aan de eigenaar van het project hoort. `default-domain` is het FEIT waar dat oordeel
uit volgt, en het is er eentje per cluster in plaats van eentje per optie per project.

Voor jullie keuzelijst betekent het: markeer de optie die gelijk is aan `default-domain` als
"kan meteen", en de rest als "wacht op een mens".

**Wat we zien.** `GET /api/v2/projects/{p}/clusters` geeft `base-domains` met `value` en
`label`. Een domein uit die lijst kiezen op `deployment create` levert alsnog een approval op
die op een beheerder wacht — wat netjes gecommuniceerd wordt, maar de lijst suggereert dat je
kunt kiezen.

**Wat het kost.** "Staat in de lijst" en "kun je nu gebruiken" zijn twee dingen geworden, en
alleen het eerste is zichtbaar. Wie de lijst leest plant een adres dat er pas na een mens is.

**Wat we vragen.** Een veld per domein dat zegt welke van de twee het is — `requires-approval`
of iets in die geest. Wij zetten het dan in de keuzelijst en in `service describe`.

## <a id="22"></a>22. ~~Vijf attachment-endpoints kennen `rollout` niet~~ — opgeleverd

**Opgeleverd op 17 augustus.** Alle vijf nemen de parameter nu, dus een run die zijn
wijzigingen opspaart laat er geen meer ontsnappen. Wij hebben de waarschuwing die we ervoor
bouwden weer weggehaald: de endpoints die de parameter nog missen zijn er waar uitstellen geen
betekenis heeft -- admin-triggers, `task cancel`, `wake`, `project create` -- en daar zou zij
alleen vals alarm geven. Gezien op een `project delete`, waar "Rolled out anyway" nergens op
sloeg.

**Wat we zagen.** `POST/PUT/DELETE .../services/attachments/attachment[...]` en de twee
component-varianten namen geen `rollout`-parameter. Gemeten: met `rollout=false` op de
opdrachtregel gaat de wijziging er meteen op, en `pending-rollout` blijft op hetzelfde getal
staan.

**Wat het kostte.** Een run die alles opspaart om in één keer uit te rollen, had er dan één
laten ontsnappen zonder het te weten.

## <a id="23"></a>23. ~~`base_domain` mist de bron die `domain-format` wél kreeg~~ — opgeleverd

**Rond op 17 augustus, en generiek opgelost in plaats van dat ene veld bij te prikken.** De
annotatie die keuzelijsten in het document zet liep alleen over de configroutes van diensten;
`UpsertDeploymentRequest` is geen configroute, dus daar wist het document van niets. Nu kan
elk modelveld zijn provider declareren, waar het ook staat, en krijgt het dezelfde
`x-choices` of `x-choices-source` als zijn tegenhanger op de config. Eén regel per veld en
geen tweede lijst die kan gaan afwijken.

Wat dat oplevert voor jullie: `UpsertDeploymentRequest.base_domain` draagt nu de
`x-choices-source` naar `GET /v2/projects/{p}/clusters`, en `domain_format` draagt naast zijn
`enum` de bron die zegt welke waarden bij het gekozen domein passen. Beide vlaggen van
`deployment create` lezen daarmee uit hun eigen veld.

**Wat we zagen.** Hetzelfde veld, twee schema's, en de bruikbare informatie zat steeds in de
andere: `PublishOnWebDeploymentConfig.domain-format` draagt nu de
`enum` met elf waarden, dus die helft is weg. Wat blijft:

| | `UpsertDeploymentRequest` | `PublishOnWebDeploymentConfig` |
|---|---|---|
| `base_domain` / `base-domain` | vrije string, **geen bron** | `x-choices-source` → `GET .../clusters` |
| `domain_format` / `domain-format` | `enum` met 11 waarden | `enum` met 11 waarden ✔ |

**Wat het kost.** `deployment create --base-domain` en `--domain-format` zijn precies waar
iemand deze waarden nodig heeft, en daar staat van elk de helft. De ronde van 16 augustus las
de broncode van het platform om erachter te komen welke domeinen er waren.

**Wat we vragen.** Beide kanten allebei geven: de `x-choices-source` ook op
`UpsertDeploymentRequest.base_domain`, en de `enum` ook op `PublishOnWebDeploymentConfig.domain-format`.
Wij lezen dan per vlag wat erbij hoort in plaats van het te koppelen aan een schema dat er
toevallig naast ligt.

## <a id="24"></a>24. ~~Twee gelijktijdige writes tellen verschillend~~ — opgeleverd

**Opgeleverd op 17 augustus, langs jullie eigen voorstel: de teller wordt na de schrijfactie
gelezen.** Allebei die getallen waren waar op hun eigen moment; wat ze verschillend maakte is
dat elke client de teller ophaalde in een AANROEP ERNA, en tussen "mijn taak is klaar" en
"vertel me de stand" past de schrijfactie van een ander.

Dus staat hij nu in het antwoord dat zegt dat de taak klaar is: `pending_rollout` op
`GET /api/tasks/{id}`, gevuld zodra de taak een eindstand heeft, met de eigen wijziging
meegeteld. Op een lopende taak is hij `null`, want dan is er nog niets geschreven. Daarmee is
de extra ronde weg en is het getal dat jullie tonen van hetzelfde moment als het "opgeslagen"
waar het bij hoort.

Het is een etiket en geen deel van de uitkomst: lukt de telling niet, dan blijft het antwoord
over de taak gewoon staan met `null`.

**Wat we zagen.** Twee `service config set`-aanroepen tegelijk landden allebei — de config was
compleet — maar meldden respectievelijk "5" en "4 changes waiting". Een race in de teller,
niet in de data.

**Wat het kost.** Klein. Het getal staat in onze uitvoer, dus het leest als een fout van ons.

**Wat we vragen.** Niets met haast. Als de teller na de schrijfactie wordt gelezen in plaats
van ervoor, klopt hij vanzelf.

## <a id="25"></a>25. ~~`sleep-mode status` zegt `starting` voor iets dat draait~~ — opgelost

**Opgelost op 17 augustus, en het antwoord was leerzamer dan de vraag.** Er staat nu
`sleep_state` naast `state`, met `awake | sleeping | waking | disabled`, en beide velden
dragen uitleg in de spec. `state` bleek het *pollcontract van de wekker* te zijn en niets
anders: het staat op `starting` zolang de app geen ready pod heeft én wanneer er helemaal
geen wekker is. Onze bevinding was dus geen verkeerde stand maar een verkeerd gelezen veld.

Nagemeten: `{"state": "starting", "sleep_state": "disabled"}` op een gezonde deployment met
sleep-mode uit. Ons commando toonde de dict zoals hij binnenkwam en het platform stuurt het
misleidende veld eerst, dus `sleep_state` staat nu bovenaan met een helptekst die zegt waarom
er twee zijn.

**Wat we zagen.** Een deployment die `Healthy` is, met `sleep-mode` op `enabled=false`,
antwoordde `starting` -- exit 0, geen fout, maar het las als een deployment die vastzat.

---

## <a id="26"></a>26. ~~Een gefaalde taak zegt niet van wie de fout is~~ — opgeleverd

**Opgeleverd op 17 augustus, de eerste van de twee.** Een gefaalde taak draagt nu
`error_category` naast `error_type`, uit dezelfde gesloten `ErrorCategory`. Er is één lid
bijgekomen, `InvalidInput`: wat de aanroeper stuurde kan niet uitgevoerd worden en opnieuw
proberen verandert daar niets aan. Jullie geval wordt dus
`{"error_type": "invalid_services", "error_category": "InvalidInput"}`, en dat is exit 1
zonder tabel.

Wat op `InvalidInput` uitkomt: `invalid_services`, `invalid_component_references`,
`invalid_deployments`, `invalid_values`, `invalid_request`, `invalid_project_name`,
`validation_error`, `domain_validation`, `not_found`, `deployment_not_found`,
`component_not_found`, `duplicate_component`, `duplicate_component_in_deployment`,
`ambiguous_cluster`, `ambiguous_repository` en `in_use`. `invalid_target` houdt zijn eigen
`InvalidTarget`, want die betekent iets specifieks (de restorebestemming die jullie opgaven)
en oprekken zou hem stukmaken.

Wat bewust `Unknown` blijft: `conflict` (twee schrijvers die elkaar raken is niemands
vergissing en kan bij een volgende poging gewoon slagen) en `internal_error` (van ons, maar er
is nog geen lid dat dat zegt). Een categorie is een belofte over toeschrijving, dus liever
Unknown dan een gok. Zeg het als jullie een lid willen dat "dit is onze storing, probeer het
later" betekent; dat is een spec-uitbreiding en geen raadwerk.

`error_type` blijft een vrije string en wordt géén enum. Hij wordt op zo'n twintig plekken los
ingevuld, en een gesloten opsomming daarvan is een audit die je bij elke nieuwe faalvorm
overdoet. De categorie ernaast is wél gesloten, dus daar kunnen jullie de test op pinnen.

Het VERTALEN gebeurt op één plek, waar een taakrecord een antwoord wordt (V1 en V2 samen).
Dat er stond "elk taaktype krijgt hem daardoor" was te snel gezegd; zie 26b hieronder, waar
jullie precies aanwijzen waar het niet klopt.

**De afgeknipte `error` is ook weg.** Het was geen kolombreedte: de kolom is `TEXT`, en het
commentaar dat 255 tekens verdedigde beschreef een kolom die niet bestaat. Er wordt nu pas bij
8000 tekens geknipt, als vangnet tegen een exceptie die een dump meesleept, dus een gewone
foutzin komt heel aan. Jullie "langste van de twee" mag blijven staan, hij heeft alleen niets
meer te doen.

**Wat we zien.** `component add proefje --service attachments` op een project waar
`attachments` nog niet geselecteerd is, faalt zo:

```json
{
  "error_type": "invalid_services",
  "subtasks": [{"name": "Component toevoegen", "status": "failed",
                "error": "Service 'attachments' needs a project-level decision ..."}]
}
```

Er is geen `error_category`. `error_type` staat in de spec als vrije string
(`anyOf: [string, null]`, zonder enum) op alle zeven `*Result`-schema's.

**Wat het kost.** Wij mogen die niet interpreteren. Onze afspraak is: geeft de API geen
categorie, dan is de fout `Unknown` en is de exit code 3 ("niet toe te schrijven"), want
gokken zou een pipeline vertellen iets te herhalen wat niemand retryable heeft verklaard. Het
gevolg is dat een duidelijke *invoerfout* — je noemde een dienst die eerst op projectniveau
gekozen moet worden — als exit 3 uit de CLI komt in plaats van exit 1. Een praktijkronde
merkte dat op en had gelijk; wij kunnen het niet repareren.

Een tabel `invalid_services -> jouw fout` bijhouden is precies wat we niet doen: het veld is
niet opgesomd, dus die tabel loopt achter op de dag dat er een achtste waarde bij komt, en dan
zwijgt hij in plaats van te melden dat hij iets niet kent.

**Wat we vragen.** Eén van de twee, en de eerste is het minste werk:

- zet `error_category` op een gefaalde taak, met dezelfde `ErrorCategory` die
  `component_failures` al gebruikt — dan valt het in de mapping die er is; of
- maak `error_type` een enum in de spec. Dan is het een gesloten verzameling en pinnen wij
  hem vast met een test, zoals we met `ErrorCategory` en `ApprovalNoticeStatus` doen: een
  nieuwe waarde komt bij ons dan binnen als een rode build in plaats van als stilte.

**<a id="26b"></a>Eén ding is nog niet rond, en het is precies na te wijzen.** "Elk taaktype
krijgt hem daardoor" klopt nog niet in de spec: negen schema's dragen `error_category`, zeven
`*Result`-schema's niet. Dat zijn `UpdateImageResult`, `DeleteComponentResult`,
`DeleteDeploymentResult`, `RefreshDeploymentResult`, `RefreshProjectResult`,
`CloneBucketResult` en `CloneDatabaseResult`.

Nagemeten op de eerste: `deployment update-image productie --component bestaatniet` — een
component die niet bestaat, dus jullie eigen `component_not_found` — komt terug zonder
`error_category` en zonder `error_type`, en dus bij ons als `Unknown` met exit 3. Onze kant is
klaar: wij lezen het veld waar het staat en vallen anders terug op de oude tekstscan, dus zodra
die zeven het dragen klopt de exit code daar ook.

**<a id="26b-af"></a>Opgeleverd op 17 augustus, alle drie de lagen.** Jullie wezen het precies
aan, en het zat dieper dan het schema. Wat er stond en wat er nu staat:

1. **Het schema.** Acht van de vijftien `*Result`-modellen droegen `error_type` niet (jullie
   zeven plus `CreateProjectResult`), en ik had de categorie gezet waar het type al stond.
   **Nu dragen alle vijftien `error`, `error_type` en `error_category`**, met een toets die
   het zo houdt.
2. **De invulling.** Van de 34 plekken die een faal-dict opbouwen zetten er 8 een
   `error_type`. Ook op een taaktype waar het model het veld kende bleef het dus vaak leeg,
   en dan was `Unknown` terecht. **Nu zetten ze het alle 34 op vier na**, en die vier zijn
   de geneste `processing`-blokken die de reden een niveau hoger al dragen. Een ongeldige
   projectnaam heet `invalid_project_name`, een naam die al bestaat `already_exists`, een
   mislukte uitrol `processing_failed`.
3. **De handlers die gooien.** `update_image`, `delete_deployment` en de twee clone-taken
   gaven bij een fout helemaal geen resultaat terug: ze gooien, en de worker bewaarde dan
   alleen een fouttekst. Er was dus niets om een categorie op te zetten. **Nu laat elke
   gooiende handler een resultaat achter**, en er is een vorm bijgekomen om te zeggen dat
   het aan het verzoek lag: de twee controles in het image-pad (`deployment_not_found` en
   `component_not_found`, jullie meting) gooien die nu, en een 404 uit een manager telt
   mee, want die taal spraken ze al. Alles wat daar niet onder valt komt terug als
   `internal_error`, dus als "niet toe te schrijven", want dat is dan de waarheid.

**Eén ding is er en passant bij besloten, en dat verandert gedrag.** Een handler die gooide
liet de taak opnieuw proberen; een handler die een faal-dict teruggaf niet. Voor "dit
component bestaat niet" is opnieuw proberen zinloos, dus een afgewezen verzoek is nu een
BLIJVENDE mislukking, ook als het gegooid werd. Een 5xx uit een manager houdt zijn nieuwe
pogingen, want dat is van ons en kan overwaaien.

Jullie `deployment update-image productie --component bestaatniet` levert daarmee
`error_type: "component_not_found"`, `error_category: "InvalidInput"` en één poging. Dat is
exit 1.

**Klein, uit dezelfde hoek.** De platte `error` is op een vaste lengte afgeknipt en eindigt
midden in een woord (`... lists the actions that put s`), terwijl de subtaak dezelfde zin
voluit draagt. Wij tonen sinds vandaag de langste van de twee. Als het afknippen ergens een
kolombreedte is: de subtaak bewijst dat de hele tekst beschikbaar is.

## <a id="27"></a>27. ~~De storage-beschrijving noemt een default die niet de default is~~ — opgeleverd

**Opgeleverd op 17 augustus.** De beschrijving is bijgetrokken, niet
de default: 100Mi is de bedoelde startmaat en staat sinds juli met een reden in de code (een
volume kan groeien en niet krimpen, dus te ruim beginnen is de duurdere vergissing). Beide
`explanation`-teksten zeggen nu 100Mi, en noemen er de keuzelijst en het maximum bij.

**En er is iets bijgekomen dat jullie zullen merken.** Die keuzelijst was tot vandaag de enige
rem, en een keuzelijst is geen regel: de config-API keek helemaal niet naar de grootte, dus
`size: 10Gi` liep door naar een echte PVC. Er zit nu een grens op, en die grens is de grootste
maat die we aanbieden: **1Gi**. Boven die maat antwoordt de API 422 met het maximum en de
beschikbare maten in de melding. De grens staat in de beschrijving van `size` in het
schemafragment, dus jullie kunnen hem uit de spec lezen in plaats van uit een afwijzing.

Twee dingen om niet over te struikelen. Het is een plafond en geen opsomming, dus een maat
onder 1Gi die niet in de lijst staat (512Mi) blijft gewoon geldig. En een projectbestand dat
al een grotere mount draagt wordt niet alsnog afgekeurd: dat zou een ouder project
onopslaanbaar maken terwijl een PVC niet kan krimpen. De grens geldt op wat er binnenkomt.
Draaiboek 01 gebruikt `1Gi` en blijft dus precies geldig.

**Wat we zien.** De `explanation` van `persistent-storage` zegt "standaard is dat 1Gi op
**/data**", die van `temp-storage` "standaard is dat 500Mi op **/tmp**". Wat
`component add --service persistent-storage` daadwerkelijk aanmaakt is **100Mi**.

**Wat het kost.** Wij geven die beschrijving letterlijk door — dat is het punt van de
registry — dus onze `service describe` vertelt nu iets wat niet klopt, en wij kunnen het niet
gladstrijken zonder een tweede waarheid te introduceren.

**Wat we vragen.** Of de beschrijving naar 100Mi, of de default naar 1Gi/500Mi. Welke van de
twee waar is, weten jullie.

## <a id="28"></a>28. ~~`minio-storage` markeert velden als verplicht die dat niet zijn~~ — opgeleverd

**Opgeleverd op 17 augustus, en anders dan gevraagd, want de `required` klopte.** Binnen één
revisie zijn `generation`, `resource`, `status` en `created_at` echt verplicht, en ze stonden
al in een genest object: precies de vorm die jullie als alternatief voorstelden. Het gat zat
een laag hoger. `generation` en `revisions` zeiden alléén in hun beschrijving dat het platform
ze schrijft, en proza is geen regel, dus ze stonden nog gewoon op het schrijfoppervlak.

Beide velden dragen nu `x-platform-managed`. De API weigert een schrijfactie erop, een
config-`GET` laat ze weg, en het schemafragment zegt het. Daarmee verdwijnt de hele
`revisions`-tak uit wat jullie moeten invullen, en is er ook geen sterretje meer om te volgen.
Het geldt meteen voor elke dienst die deze kloonstatus draagt, dus `minio-storage`,
`postgresql-database` en de kloonstatus van `persistent-storage` en `temp-storage`.

Nagekeken voor het erop ging dat het niets van jullie breekt: `zadctl` leest `revisions` en
`generation` nergens, en de leeskant filterde platform-managed velden al, dus een
read-modify-write blijft kloppen.

**Wat we zien.** Het schema zet `revisions[0].*` in `required`, maar
`--set enable-versioning=true` zonder enige `revisions` wordt geaccepteerd en rolt uit.

**Wat het kost.** `service describe` zet een `*` achter een verplicht veld, dus de tabel
vraagt om iets wat de API niet nodig heeft. Wie de sterretjes volgt, vult velden in die er
niet horen.

**Wat we vragen.** De `required` weghalen waar hij niet geldt, of — als die velden intern
verplicht zijn zodra je `revisions` gebruikt — ze in een genest object zetten zodat de eis bij
dat object hoort en niet bij het hele document.

## <a id="29"></a>29. ~~Wat garandeert `check-subdomain` precies?~~ — opgeleverd

**Opgeleverd op 17 augustus, inclusief het stuk dat jullie "de nuttigste toevoeging" noemden.**
Jullie vermoeden klopte, en de oorzaak is aanwijsbaar: de controle op het basisdomein laat elk
syntactisch geldig domein toe, met "custom domain support" als reden, want een project mag zijn
eigen domein meebrengen. `speeltuin-vlam.nl` komt daar dus doorheen en het antwoord gaat alleen
over de reservering binnen ZAD. Strenger maken zou eigen domeinen onmogelijk maken, dus is het
antwoord duidelijker geworden in plaats van strenger.

Wat er nu staat: de beschrijving van het endpoint en van `available` zeggen waar de controle
wel en niet over gaat, en het antwoord draagt een veld erbij, **`cluster_domain`**. Waar
betekent dat dit cluster het domein zelf bedient en een vrije naam meteen een bruikbaar adres
is; onwaar betekent dat het je eigen domein is, en dan is de naam claimen pas de eerste helft
en moet het domein daarnaast nog aangevraagd en goedgekeurd worden. Daarmee vallen "vrije naam"
en "bruikbaar adres" in één antwoord samen.

De bron is dezelfde lijst die bepaalt welk domein een certificaat van het platform krijgt
(`nice_url.supported_domains` van het cluster), dus het is geen tweede waarheid. Het veld
reist ook mee in een afwijzing: het is een eigenschap van het domein en niet van de uitkomst,
en juist bij "niet beschikbaar" wil je weten welk van de twee dingen je aan het oplossen bent.

**Wat we zien.** `check-subdomain demo-app speeltuin-vlam.nl` antwoordt `available: true`,
voor een domein dat van niemand is en waarvoor geen DNS bestaat.

**Wat het kost.** De naam belooft meer dan het antwoord waarmaakt. Een lezer leest
"beschikbaar" als "dit adres kan ik gaan gebruiken", en wat er staat is vermoedelijk "deze
subdomeinnaam is niet gereserveerd binnen ZAD". Dat zijn twee verschillende dingen zodra het
base-domain niet van het cluster is.

**Wat we vragen.** Eén zin in de beschrijving die zegt waar de check wél over gaat. Als hij
ook zou kunnen zeggen of het base-domain van dit cluster is, is dat de nuttigste toevoeging:
dan valt "vrije naam" en "bruikbaar adres" samen in één antwoord.

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
- **Een `ETag` op `/openapi.json`** (punt 1), waarmee de cache op verandering kan controleren
  in plaats van op tijd: `If-None-Match` na een minuut, meestal een `304`, 0,03s in plaats
  van 0,16s.
- **De projectsleutel op `sleep-mode status` en `wake`** (punt 4), met beide headers
  gedocumenteerd. Die twee commando's zijn daarmee van onbruikbaar naar gewoon gegaan.
- **De uitleg boven aan de spec over `enum` versus `x-choices`.** Die heeft direct een fout
  in deze CLI rechtgezet: we presenteerden een menu als een gesloten lijst, waardoor `90m`
  bij `sleep-after-deploy` ongeldig leek.
