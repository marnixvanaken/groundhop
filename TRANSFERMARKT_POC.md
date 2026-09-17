# Transfermarkt PoC — bevindingen

Proof of concept om te beoordelen of de databron van Sofascore naar
Transfermarkt kan. Raakt de bestaande pipeline niet aan.

## Snel draaien

```bash
pip install -r requirements.txt

# Wedstrijdrapport, en bewaar de HTML voor later
python3 transfermarkt_poc.py --match 4894734 --dump html_dump/

# Spelerprofiel: marktwaarde + transfers + interlands
python3 transfermarkt_poc.py --player 1

# Offline opnieuw parsen zonder netwerk
python3 transfermarkt_poc.py --match 4894734 --html html_dump/match_4894734.html
```

De parser rapporteert per veld `OK` / `LEEG` / `GEMIST`. `GEMIST` betekent dat
een selector niet matchte — dan is de parser stuk, niet de bron.

## Wat Transfermarkt wél levert

Geverifieerd tegen het schema van `data/selected_matches.json`: de output past
exact, met `lineup` en `id_source` als enige toevoegingen.

| Veld | Bron op TM |
|---|---|
| teams, score, ruststand | `div.sb-endstand`, `div.sb-halbzeit` |
| competitie, speelronde, datum | `div.sb-datum` |
| stadion, publiek, scheidsrechter | `p.sb-zusatzinfos` |
| doelpunten + assists + type | `#sb-tore` |
| kaarten + reden | `#sb-karten` |
| wissels | `#sb-wechsel` |
| opstelling + bank | subpagina `/spielbericht/aufstellung/` |
| bio, positie, lengte, interlands | data-header spelerprofiel |
| marktwaarde + historie | `ceapi/marketValueDevelopment/graph/{id}` |
| transfers + bedragen | `ceapi/transferHistory/list/{id}` |

**Publiekscijfers zijn de grootste winst**: nu 41 van 180 wedstrijden (23%)
via Sofascore, op Transfermarkt vrijwel altijd aanwezig — ook bij oude
wedstrijden.

## Wat structureel ontbreekt

Transfermarkt is een marktwaarde- en transferdatabase, geen
statistiekleverancier. Deze velden bestaan er niet:

| Veld | Dekking nu | Gebruikt in |
|---|---|---|
| `avg_rating` | 1855 spelers (62%) | 10 plekken + `RatingBadge` |
| `xg_total` / `xg` | 522 spelers (17%) | 6 plekken + record `highest_xg_match` |
| `total_shots`, `shots_on_target` | 1011 spelers (34%) | `PlayerDetail` |
| `pass_accuracy_pct`, `key_passes` | — | `PlayerDetail` |
| `tackles`, `interceptions`, `duels_*` | — | `PlayerDetail` |
| `fouls_committed`, `fouls_drawn` | — | alleen in data |
| `team_stats` (balbezit) | 180 wedstrijden | — |

Goals, assists, kaarten, wissels, opstelling en `minutes_played` blijven
overeind. De afleiding van minuten uit opstelling + wissels bestaat al in
`sofascore_tracker.py:1115-1180` (de fallback voor handmatige wedstrijden) en
werkt ongewijzigd voor Transfermarkt-data.

## Aandachtspunten voor een echte migratie

**1. ID-mapping is de grootste kostenpost.** Een eerdere versie van dit
document beweerde dat de handmatige entries Transfermarkt-ID's gebruiken en
botsen met Sofascore-ID's. Dat klopt niet: Transfermarkt-ID 1 is Silvio Adzic,
een Duitse rechtsbuiten die in 2017 stopte — niet Robin van Persie. De ID's in
`selected_matches.json` zijn dus Sofascore-ID's, en `2614` (Huntelaar) en
`138828` (Willems) droegen consistente data omdat het dezelfde speler is. Er is
geen botsing.

Het echte probleem is dat er *geen* overlap is: je 3016 spelers, 179
wedstrijden en 109 clubs hangen aan Sofascore-ID's waarvoor geen mappingtabel
naar Transfermarkt bestaat. Herkoppelen gaat via naam + geboortedatum, en wat
niet matcht verlies je. Daarom schrijft de PoC een `id_source`-veld mee, zodat
de twee namespaces gescheiden blijven.

**2. Spelersfoto's zijn niet deterministisch.** Sofascore geeft
`/player/{id}/image`; Transfermarkt zet een cache-busting timestamp in de URL
(`portrait/big/{id}-{ts}.jpg`) die je per speler moet scrapen. Clublogo's zijn
wél voorspelbaar. De bestaande cache van 409 afbeeldingen in `img/` vangt dit
grotendeels op.

**3. Er is geen kant-en-klare match-scraper.** `felipeall/transfermarkt-api`
dekt alleen `clubs`, `competitions` en `players` — geen wedstrijden. De
`spielbericht`-parser bouw je zelf; dat is precies wat hier staat.

**4. Cloudflare.** Transfermarkt zit erachter. `curl_cffi` (nu correct in
`requirements.txt`) imiteert een browser-TLS-fingerprint en is de beste kans.
Bij 403/503: `--dump` gebruiken, pagina handmatig opslaan, dan `--html`.

## Status van deze PoC

Gevalideerd tegen een echte wedstrijd: PSV 4-1 Sparta Rotterdam
(`spielbericht/4894734`, Eredivisie speeldag 6). Cloudflare liet `curl_cffi`
zonder challenge door. Alle 16 velden komen correct binnen, inclusief 34.900
toeschouwers, scheidsrechter Danny Makkelie, en opstellingen van 11+12 (PSV) en
11+11 (Sparta) — met de hand nageteld.

De eerste run legde vier selectorfouten bloot, waarvan één stil:

| Veld | Probleem | Oplossing |
|---|---|---|
| `tournament` | gaf "6. Speeldag", **gerapporteerd als OK** | link naar seizoenspagina i.p.v. eerste `/wettbewerb/`-link |
| `date` | notatie is `zo, 13-09-26`, tweecijferig jaar | ISO-datum uit de `/datum/`-link |
| `attendance` | staat als `34.900 toeschouwers`, getal vóór label | beide volgordes |
| `substitutions` | `sb-aktion-wechsel-ein` is `<span>`, niet `<div>` | selectie op class zonder tag |

De stille fout is het leerzaamst: het veld was gevuld, dus het rapport zei `OK`,
maar `tournaments` zou volgelopen zijn met "1. Speeldag", "2. Speeldag" in
plaats van 21 competities. De parser markeert een competitienaam die op
`N. ` begint nu expliciet als `GEMIST`, en controleert dat elke basisopstelling
precies 11 spelers telt.

De spelerparser bleek een ander probleem te hebben: transfers en
marktwaardehistorie staan **in het geheel niet in de HTML**, ook niet op de
eigen subpagina's. Op `/transfers/spieler/{id}` is de enige class met
"transfer" erin een footerlink. De frontend laadt beide na via interne
JSON-endpoints, en die zijn rechtstreeks bruikbaar:

| Gegeven | Bron |
|---|---|
| naam, bio, positie, lengte, interlands | `/profil/spieler/{id}` (HTML) |
| transfers + bedragen | `/ceapi/transferHistory/list/{id}` (JSON) |
| marktwaarde + volledige historie | `/ceapi/marketValueDevelopment/graph/{id}` (JSON) |

Dat is beter dan HTML-parsen: gestructureerde data die niet breekt bij een
opmaakwijziging. De marktwaardehistorie levert per punt de waarde, de datum,
de club en de leeftijd van de speler.

Twee vallen die daarbij zijn afgevangen:

- **Bedragen.** `10,00 mln. €` is Nederlands, `€14.00m` Engels. Naïef de punten
  strippen maakt van de tweede 1,4 miljard. De eenheid beslist nu of een
  scheidingsteken decimaal of duizendtal is; tien notaties zijn getest.
- **Datums.** De `x`-tijdstempels staan op lokale middernacht (CET/CEST).
  Omrekenen in UTC schuift elke datum een dag terug — gecontroleerd tegen het
  `datum_mw`-veld uit dezelfde respons.

## Eindstand van de PoC

Beide parsers zijn gevalideerd tegen echte pagina's, zonder gemiste velden:

| Parser | Testgeval | Resultaat |
|---|---|---|
| Wedstrijd | PSV 4-1 Sparta (`4894734`) | **16/16** velden |
| Speler | Ruben van Bommel (`735701`) | **10/10** velden |

De spelerrun leverde 13 marktwaardepunten op (€25.000 bij MVV O18 in juni 2022
tot €10 mln bij PSV in mei 2026) en 5 transfers met €15,8 mln als hoogste som.
Cloudflare gaf geen enkele keer een challenge met `curl_cffi`.

Onderweg zijn zes fouten gevonden en hersteld, waarvan **drie stil** — velden
die gevuld leken maar verkeerde data bevatten. Dat is de belangrijkste les uit
deze PoC: een gevuld veld is geen bewijs van een correct veld. Het rapport
controleert daarom nu ook op plausibiliteit (competitienaam die op `N. `
begint, basisopstelling die niet op 11 uitkomt) in plaats van alleen op
aanwezigheid.

## De vijfde stille fout: strafschoppen in de eindstand

De spelerslaag telt de doelpunten op spelersnaam en vergelijkt die met de som
van alle eindstanden. Over 164 wedstrijden kwam die controle 5 doelpunten
tekort, allemaal uit één wedstrijd:

```
2023-04-30  AFC Ajax - PSV: stand 7, gevonden 2
```

De bekerfinale van 2023 eindigde 1-1 en werd met 2-3 beslist na strafschoppen.
Transfermarkt telt die strafschoppen bij de eindstand op:

```html
<div class="sb-endstand"> 3:4<div class="sb-halbzeit">n.s.</div></div>
```

`3:4` als uitslag opschrijven is fout — dat was de wedstrijd niet. De pagina
draagt een apart blok `#sb-elfmeterscheissen`, en dat is het signaal: staat het
er, dan is de stand in het veld de doorlopende tussenstand bij het laatste
doelpunt in `#sb-tore`, en is het verschil de serie. Die komt nu in een eigen
veld `penalty_shootout` terecht.

De parser corrigeert alleen als de uitkomst klopt: een serie volgt per
definitie op een gelijkspel, en je kunt er niet minder dan nul benutten. Is dat
niet zo, dan meldt hij het als `GEMIST` in plaats van door te rekenen op een
aanname die niet opgaat.

Tien uitgewerkte gevallen staan vast in `--zelftest`.

Deze fout was niet te vinden door naar velden te kijken: `home_score` was
gevuld, plausibel, en van het juiste type. Hij kwam boven doordat een telling
van buitenaf niet uitkwam.

## De vierde stille fout: "Joey Veerman" als competitie

Bij de volledige run van 164 wedstrijden meldde het rapport zes gemiste
velden. De ernstigste stond er niet tussen, want het veld was *gevuld*:

```
tournament    OK    Joey Veerman
```

PSV – AS Monaco (CL-kwalificatie) heeft geen link naar een seizoenspagina, dus
viel de parser terug op "elke link met deze competitie-ID". De prestatielinks
van spelers hebben exact die vorm —
`/joey-veerman/leistungsdatendetails/spieler/257491/saison/2022/wettbewerb/CLQ`
— en dragen de spelersnaam als `title`. De terugval slaat spelerlinks nu over.

Daarnaast bleek de plausibiliteitscontrole zélf twee wedstrijden te slopen. Die
verwierp elke competitienaam die op `N. ` begon, om "6. Speeldag" te vangen.
Maar "2. Bundesliga" en "3. Liga" beginnen ook zo. De controle kijkt nu of er
daadwerkelijk een speeldag-woord op het cijfer volgt.

Ten slotte: bij verlenging staat er in het ruststandblok alleen `n.v.` en geen
score. Dat is geen gemiste selector maar een bron die het cijfer niet geeft —
nu `LEEG` in plaats van `GEMIST`.

Daarmee staat de teller op **vier stille fouten van de tien gevonden fouten**.
Alle vier waren gevulde velden met verkeerde inhoud, en alle vier zijn gevonden
doordat iemand naar de waarde keek in plaats van naar de status.

## `round`: geen verlies, maar een andere weergave

Het vergelijkingsrapport liet `round` op 1/5 staan tegen 5/5 bij Sofascore. Dat
is nagemeten en het is geen regressie:

- Transfermarkt zet bij bekerduels een **fase** neer ("Groepsfase", "Achtste
  finale") in plaats van een nummer. De parser schrijft die in `round_name` en
  laat `round` leeg. Beide velden tellen nu mee in het rapport.
- Sofascore's nummers zijn bij Europese duels **onsamenhangend**: over de
  UEFA-wedstrijden in `selected_matches.json` staan waarden als `636`, `50`,
  `17` en `16` naast 1 t/m 8. Dat zijn interne ronde-ID's, geen speelronden.
- Het dashboard rendert `round` **alleen bij zoekresultaten** uit de live
  Sofascore-API (`dashboard.html:1604`, `R${e.roundInfo?.round}`), nooit vanuit
  een opgeslagen wedstrijd. Een leeg `round` op een opgeslagen record is dus
  nergens zichtbaar.

## De geboortedatum als kruiscontrole, en wat die eerst verkeerd deed

De profielrun haalde 2681 van de 2759 spelers op. Elke ingevulde geboortedatum
is naast de Sofascore-data gelegd: 2331 waren op naam te vergelijken, 2249
kwamen overeen, **82 niet**. Dat is 3,5%, en dat is te veel om af te doen als
ruis — maar te weinig om aan te nemen dat er systematisch verkeerde profielen
worden opgehaald. Een aantal zonder vorm zegt niets. Dus is er een vorm aan
gegeven.

**Een naam is geen speler.** De eerste versie nam per naam één geboortedatum
(`setdefault`) en vergeleek daarmee. In `dashboard_data.json` staan vier namen
die bij méér dan één speler horen: Danilo (drie data), David López, Ben Davies
en João Pedro. Voor die namen was een afwijking **gegarandeerd**, ongeacht of
het profiel klopte — de controle rapporteerde haar eigen aanname als fout. De
controle verzamelt nu per naam álle bekende data en telt gelijk zodra de datum
er één van is. Ben Davies (TM 1993-04-24) is daarmee gewoon goed.

Dat is dezelfde fout in een nieuwe gedaante: een gevuld veld is geen goed veld,
en een controle die zelf een aanname doet, toetst die aanname niet.

**De vorm van het verschil zegt waar het vandaan komt.** `vergelijk()` deelt
elke afwijking in, van mild naar ernstig:

| vorm | betekenis |
|---|---|
| één dag | twee bronnen leggen de datumgrens anders; geen fout in het profiel |
| twee of drie dagen | idem, of een leesfout aan één kant |
| dag en maand verwisseld | 1997-04-08 tegen 1997-08-04; een formaatkwestie |
| alleen het jaar | zelfde dag en maand, ander jaar |
| geheel anders | **kan een verkeerd profiel zijn** |

Over de volle set (79 na aftrek van de naamgenoten):

| vorm | aantal |
|---|---|
| één dag | 37 — waarvan 31× TM later |
| twee of drie dagen | 5 |
| dag en maand verwisseld | 3 |
| alleen het jaar | 4 |
| geheel anders | 29 |

**De dagverschillen zijn van de bron, niet van de parser.** 31 van de 37 staan
dezelfde kant op; dat is te eenzijdig voor toeval. Waar de datum onafhankelijk
bekend is, heeft Transfermarkt gelijk — Paul Wanner is van 23 december 2005,
Zeno Debast van 24 oktober 2003, beide zoals TM ze geeft. Sofascore zit er
systematisch één dag naast, zoals je krijgt wanneer een geboortedatum als
tijdstempel bewaard wordt en in een andere tijdzone teruggelezen.

**De club is de tweede getuige.** Bij een datum die nergens op lijkt is de vraag
niet welke datum klopt maar of het dezelfde mens is, en daar staat de
geboortedatum buiten. `clubs_overlappen()` reduceert beide clubnamen tot hun
onderscheidende woorden (`FK Haugesund` en `Haugesund` worden allebei
`{haugesund}`) en kijkt of er één gemeenschappelijk is. Zo valt 'geheel anders'
uiteen in drie groepen, en alleen de laatste vraagt om een mens.

**Een deel van de Sofascore-data zijn plaatshouders.** `1996-11-30`,
`1998-11-30`, `1999-11-30`, `2005-01-01` — 30 november en 1 januari, steeds aan
de Sofascore-kant. Dat is geen afwijkende datum maar een gat dat als datum is
opgeslagen, en het wordt nu apart geteld in plaats van als fout.

**Jaren uiteen is geen leesverschil.** Twee bronnen kunnen het oneens zijn over
een dag, een maand, soms een jaar. Liggen de data vijftien jaar uiteen, dan
lezen ze niet dezelfde geboortedatum verkeerd maar beschrijven ze twee mensen.
Dat is de enige aanwijzing die ook werkt als beide bronnen dezelfde club noemen,
en het is wat Andy Little eruit haalt (TM 1989-05-12, Sofascore 1974-10-03) —
een naam die bij twee spelers hoort, bij beide bronnen alleen gezien bij het
Noord-Ierse elftal, waar de clubtoets dus blind is.

Wat er over 2331 vergelijkingen overblijft: geen enkel geval waarin de twee
bronnen dezelfde naam bij verschillende clubs zagen. Er is dus nergens een
profiel van de verkeerde speler opgehaald.

Draai `python3 transfermarkt_profiles.py --rapport` voor de indeling; dat haalt
niets op. `--zelftest` rekent de controle zelf na op vijfendertig gevallen
waarvan de uitkomst vaststaat: de vormen, de naamgenoten, de clubnamen en de
plaatshouders.

## 502 en 504 hoorden ook bij de tijdelijke fouten

De retry-lus kende `403`, `429` en `503` — Cloudflare die afremt. In de volle
profielrun kwamen daarnaast een stuk of twintig `502`/`504` langs: Transfermarkt
zelf die even niet antwoordt. Die vielen meteen fataal uit en kostten evenzoveel
spelers, terwijl een tweede poging ze had opgeleverd. Alle vijf staan nu in
`TIJDELIJKE_STATUS`. Een `404` hoort daar niet bij: die herhaalt zich.

## Wat nog getest moet worden

Randgevallen uit de eigen dataset: verlenging, strafschoppen, een rode kaart,
en een oude wedstrijd zonder publiekscijfer. Draai daarvoor:

```bash
python3 transfermarkt_poc.py --match <id> --dump html_dump/
```

en bekijk of er `GEMIST`-regels verschijnen.

## Het dashboard ontdaan van wat Transfermarkt niet levert

Sofascore gaf per speler een cijfer, een xG en een rij aanvallende en
verdedigende tellingen. Transfermarkt geeft die niet, en gaat ze ook niet geven.
Een hokje dat voor altijd `—` toont is geen lege waarde maar een verbroken
belofte: het zegt de lezer dat er een getal hóórt te staan. Daarom zijn ze uit
`dashboard.html` gehaald in plaats van leeg gelaten.

Weg zijn: het cijferbadge (`RatingBadge`) met zijn kleurschaal, de sorteringen
op cijfer en op xG, het cijferblok in het spelersprofiel, de xG per wedstrijd,
en acht statistiekhokjes — xG, passnauwkeurigheid, schoten, schoten op doel,
duels gewonnen en verloren, tackles en intercepties. De opmaakhulpjes `fXg`,
`fRating` en `rBg` hadden daarna geen werk meer.

Wat overblijft in het profiel komt uit de opstelling en het wedstrijdverslag —
basis, invaller, bank, minuten, goals, assists, geel, rood — en dat levert
Transfermarkt wél, voor alle 164 wedstrijden in plaats van de twee waarvoor
Sofascore doelpunten had.

Een paar velden stonden al nergens in beeld: `key_passes`, `fouls_committed`,
`team_stats`, `shotmap` en het record `highest_xg_match` werden wel geëxporteerd
maar nooit getoond. Die zijn met rust gelaten; ze verdwijnen vanzelf met de
bron.

## "Al opgeslagen" vergeleek nummers uit twee verschillende stelsels

Het zoektabblad zoekt bij Sofascore en zet achter een resultaat dat je al hebt
`al opgeslagen`, door het event-ID te vergelijken met de opgeslagen wedstrijden
(`dashboard.html`, `reloadSavedIds`). Een uit Transfermarkt gehaalde wedstrijd
draagt een TM-ID. Na de overstap zou die vergelijking dus op niets meer matchen
en zou het dashboard elke wedstrijd die je al hebt opnieuw als nieuw aanbieden —
stil, zonder foutmelding, en alleen te merken door het te weten.

De koppeling die er toch al lag lost het op. `transfermarkt_sync.py` schrijft nu
per wedstrijd het bijbehorende Sofascore-ID mee als `sofascore_id`, als herkomst
en niet als sleutel, en het dashboard bouwt zijn verzameling uit beide nummers.
Een wedstrijd zonder koppeling krijgt het veld niet en valt netjes weg.

## De wedstrijd die alleen in de export bestond

`data/dashboard_data.json` telt 180 wedstrijden, `data/selected_matches.json`
179. Het verschil is NEC Nijmegen - PSV van 13 maart 2011, met stand, stadion,
scheidsrechter, doelpunten, kaarten, wissels en opstelling — compleet, alleen
niet in de selectie. Hoe dat zo gekomen is weet niemand meer.

Dat is geen schoonheidsfout. De export leest de selectie, dus de eerstvolgende
keer dat er geëxporteerd wordt, wordt die wedstrijd overschreven door een
bestand waar hij niet in staat. Zonder melding, zonder spoor, en alleen te
merken door vooraf te weten dat hij er hoorde te zijn.

`transfermarkt_map.py` koppelt nu de vereniging van beide bestanden: de selectie
plus wat alleen in de export staat. De aanvulling wordt genoemd bij elke run —
stilzwijgend bijtrekken is precies hoe hij zoekraakte. `--zelftest` rekent de
aanvulling na op zeven gevallen (leeg, gelijk, een wees, dezelfde wees dubbel,
een record zonder id, een lege selectie) en raakt het netwerk niet.

Praktisch betekent dit één speelschema extra ophalen: PSV in 2010/11.

## De ontbrekende schakel: `transfermarkt_dashboard.py`

Het dashboard leest één bestand, `data/dashboard_data.json`, en tot nu toe maakte
alleen `sofascore_tracker.py` dat. De Transfermarkt-keten liep dus tot aan de
spelerslaag en hield daar op: wedstrijden en spelers waren compleet, maar niets
zette ze om naar wat het dashboard opent.

`transfermarkt_dashboard.py` doet dat, en heeft de Sofascore-cache niet nodig —
de sync en de spelerslaag hebben het rekenwerk al gedaan. Wat hier gebeurt is
optellen (stadions, clubs, toernooien, scheidsrechters, seizoenen, records) en
het aanvullen van de spelers met wat alleen uit de combinatie volgt: de
positieletter, de landcode, en hun leeftijd op elke wedstrijddag. Het schrijft
naar `data/dashboard_data_tm.json` en laat het origineel met rust.

### Getoetst tegen de oude export, niet tegen zichzelf

`--zelftest` rekent 84 sommen na, maar een zelftest kan alleen bevestigen wat je
al dacht. De echte proef was de bouwer over de 180 Sofascore-wedstrijden laten
lopen — hetzelfde schema — en de uitkomst naast die van de tracker leggen. Vier
getallen weken af. Eén daarvan was mijn fout, drie die van de tracker, en dat
was alleen te zien door ze allemaal na te lopen.

**Mijn fout: De Kuip telde dubbel.** Ik groepeerde stadions op `id of naam`. De
Kuip staat in de eigen data drie keer, twee keer met id 612 en één keer zonder —
en werd zo twee stadions. De sleutelregel is nu: hetzelfde id is hetzelfde ding;
een record zonder id hoort bij de groep met dezelfde naam als die bestaat; pas
anders wordt de naam zelf de sleutel. Alleen op naam groeperen kan namelijk óók
niet: Amsterdam ArenA en Johan Cruijff ArenA zijn hetzelfde gebouw, en alleen het
id weet dat.

**De tracker sloeg stil over wat geen id had.** Twee scheidsrechters (Brych,
Schörgenhofer), twee stadions (Amsterdam ArenA, Gofferstadion) en één toernooi
(International Friendlies) stonden zonder id in de data en vielen daarmee uit de
telling. Je bent er wel geweest. Die tellen nu mee.

**De tracker telde doelpuntrecords, geen doelpunten.** `total_goals_witnessed`
was `sum(len(m["goals"]))`: het aantal doelpunten waarvan een record was
opgehaald. Twee wedstrijden scheelden negen goals — Rot-Weiss Essen - SV Wehen
Wiesbaden (stand 4, nul records) en de bekerfinale Ajax - PSV (stand 7, twee
records). De eindstand opgeteld is het eerlijke getal. Bij Transfermarkt is dat
ook veilig: `parse_match` houdt een strafschoppenserie apart van de uitslag, dus
een beslissende serie telt niet mee als doelpunten.

**En een keuze, geen fout: de bank telt niet mee.** "Jongste ooit" stond op
Mees Rensen (16j 45d) en "Oudste ooit" op Remko Pasveer (41j 317d). Allebei zaten
ze die dag op de bank en speelden ze geen minuut. Dat vak staat in het dashboard
pal boven de XI, en die XI bestaat uit spelers die gespeeld hebben; een
zestienjarige in trainingspak heb je niet zien voetballen. De records gaan nu
over wie er daadwerkelijk op het veld stond — en het rapport noemt er
uitdrukkelijk bij wie er op de bank nóg jonger of ouder was, zodat het een keuze
blijft en geen aanname.

### Wat het rapport meldt in plaats van verzwijgt

Twee vertalingen kunnen niet volledig zijn, en allebei melden ze wat ze niet
konden plaatsen, met aantallen:

- **Positie.** Het dashboard zet spelers in een opstelling op één letter (G, D,
  M, F); Transfermarkt schrijft de positie voluit en preciezer ("Centrale
  verdediger"). De letter gaat naar `position`, de volledige omschrijving naar
  `position_detail` — en het spelersprofiel toont voortaan die, want dat is
  nauwkeuriger dan "Verdediger". De volgorde van de vertaalregels is de hele
  truc: "Linkervleugelverdediger" bevat ook "vleugel" en "aanvallende
  middenvelder" bevat ook "aanval". Wie eerst op de aanvallende woorden toetst,
  zet halve verdedigingen en het complete middenveld in de spits.
- **Nationaliteit.** Transfermarkt.nl geeft een Nederlandse landnaam, het
  dashboard heeft een alpha-2-code nodig. Die vertaling staat al in
  `dashboard.html`, in `A2_NAMES`, en wordt daar gelezen in plaats van hier
  overgetypt — zo kan de vlag nooit een ander land aanwijzen dan de naam ernaast.
  Namen die er niet in staan worden geteld en genoemd.

Een lege plaatsnaam onder een stadion is uit het dashboard gehaald: Transfermarkt
noemt de stad niet, en een lege regel ziet eruit als een mislukte render.

## Foto's en clubwapens: uit de pagina, niet uit een geraden URL

Het dashboard haalde spelersfoto's en clublogo's op via `/img/player/{id}` en
`/img/team/{id}`, een proxy in `server.py` die Sofascore om een plaatje vraagt
bij een Sofascore-ID. Met een Transfermarkt-ID levert dat niets op, dus na de
overstap zou je overal initialen en afkortingen zien.

Transfermarkt zet beide plaatjes gewoon in de HTML die we toch al ophalen. De
opstellingspagina toont elke speler twee keer — eerst het portret zonder tekst,
dan de naamlink — en alleen die eerste draagt de foto-URL; het wedstrijdblok
bevat het clubwapen. Geen extra verzoeken, en geen geconstrueerd URL-patroon:
dat zou stil breken zodra Transfermarkt zijn CDN verlegt, en dan zie je alleen
lege plekken zonder te weten waarom.

De URL's reizen mee door de keten: `parse_lineup` → `minuten_per_speler` →
`bouw_spelers` → `photo_url` per speler, en `parse_match` → `logo_url` per club.
Een speler die alleen in een doelpunt opduikt en niet in de opstelling staat,
heeft geen foto; dat is geen fout en wordt ook niet als fout behandeld.

### Waarom ze alsnog langs de proxy gaan

De eerste versie zette de URL rechtstreeks in de `<img src>`. Dat leek korter
maar sloopt iets: de Sofascore-export dráágt `photo_url` al, en die wijst naar
precies wat de proxy ophaalt. Rechtstreeks laden zou dus voor de oude data de
proxy omzeilen — en die staat er juist omdat het anders op mobiel niet werkt.

`/img/ext?u=<url>` haalt nu elke opgegeven afbeelding op, maar alleen van
`api.sofascore.app`, `tmssl.akamaized.net` en `*.transfermarkt.technology`.
Zonder die grens zou het een open proxy zijn waarmee iedereen die het dashboard
kan bereiken willekeurige URL's vanaf die machine kan ophalen. De toets weigert
ook `http`, en `transfermarkt.technology.iets-anders.nl` — een achtervoegsel dat
op het goede domein lijkt is geen goed domein. Sofascore krijgt zijn cookies
mee, Transfermarkt niet; die heeft er niets mee te maken.

Het rapport telt voortaan hoeveel spelers een portret hebben en hoeveel clubs
een wapen, zodat de volgende run laat zien of het ook echt gelukt is.

## Twee kleinigheden die de eerste echte run opleverde

De bouwer meldde wat hij niet kon plaatsen, en dat was precies waarvoor die
melding bedoeld was:

- **Eén onbekende positie: "Verdediging".** Dat is de groepskop boven de
  verdedigers. Toegevoegd als eigen woord, niet door op "verdedig" te toetsen —
  dan valt "verdedigende middenvelder" er ook in en staat het halve middenveld
  achterin.
- **Acht landnamen die Transfermarkt anders spelt**, samen 37 spelers:
  "Democratische Republiek Congo", "Republiek Congo", "Bosnië en Herzegovina",
  "Trinidad en Tobago", "Haiti", "Wit-Rusland" en "Benin" staan nu in een lijst
  vérschillen — geen tweede landenlijst.

  Sint Maarten staat er niet bij. Zijn ISO-code is `sx`, maar in de tabel van
  het dashboard is `sx` Schotland, zoals Sofascore het noemt. Hem toch op `sx`
  zetten geeft één speler een Schotse vlag, en een verkeerde vlag is erger dan
  geen vlag.

## `transfermarkt_vergelijk.py`: eerst verkeerd gebouwd, toen pas goed

De bouwer telt aan het eind op wat er in beide exports zit: 165 wedstrijden
tegen 180, 2785 spelers tegen 3016. Dat zegt of de aantallen kloppen, niet of de
inhoud klopt. 165 wedstrijden kunnen er 165 zijn met de verkeerde uitslagen, en
geen enkele telling zou dat merken.

De eerste versie van de vergelijker legde de twee exports daarom record voor
record naast elkaar en vergeleek per wedstrijd de uitslag, het stadion, de
scheidsrechter, het toernooi en het seizoen. Hij meldde **1020 punten om naar te
kijken**, en daarmee was hij waardeloos. Wat hij vond:

    stadion: 'Gofferstadion' → 'Goffertstadion'
    scheidsrechter: 'Jack Van Hulten' → 'Jack van Hulten'
    seizoen: 'Eredivisie 10/11' → 'Eredivisie 2010/11'
    toernooi: 'International Friendlies' → 'Oefeninterlands'

Dat is geen tegenspraak, dat is vertaling. Twee bronnen die dezelfde wedstrijd
beschrijven spellen alles anders, en dat had ik moeten verwachten voordat ik
"velden die allebei de bronnen zouden moeten weten" ging vergelijken. Beide
bronnen wéten het stadion; ze noemen het alleen anders.

De tweede fout zat in de regel "niets mag omhoog". Die leek sterk — de nieuwe
export heeft vijftien wedstrijden minder, dus is hij een deelverzameling — maar
hij gaat uit van twee bronnen die even volledig zijn. Dat zijn ze niet: de oude
export heeft bij 179 van de 180 wedstrijden gèèn opstelling. Sofascore kende de
bank niet, dus zijn de minuten daar onvolledig. Cody Gakpo die van 2451 naar
2625 minuten gaat is winst, geen dubbeltelling. Er kwamen 336 "stijgers" uit, en
alle 336 waren goed nieuws.

### Wat er wél toe doet

De herziene module scheidt vier dingen die niet door elkaar mogen lopen:

1. **Tegenspraak** — alleen de datum en de uitslag. Daar kan maar één van de
   twee bronnen gelijk hebben. 2-1 en 3-1 kunnen niet allebei waar zijn; De Kuip
   en Stadion Feijenoord wel.

2. **Vertaling** — dezelfde zaak, een andere naam, afgeleid uit de gekoppelde
   wedstrijden zelf. Stond in wedstrijd X het stadion vroeger als
   'Gofferstadion' en nu als 'Goffertstadion', dan is dat één naamwissel en geen
   165 fouten. De uitkomst is een vertaaltabel in plaats van een foutenlijst, en
   die is bruikbaar: je ziet in één oogopslag hoe de bronnen elkaars namen
   schrijven.

   Eén geval is hier wél verdacht: een oude naam die in twéé nieuwe namen
   uiteenvalt. Dan hield de ene bron uit elkaar wat de andere samennam, of
   andersom. Twee oude namen die één nieuwe worden is juist goed — Amsterdam
   ArenA en Johan Cruijff ArenA zijn hetzelfde gebouw.

3. **Dekking** — per veld hoeveel van de gekoppelde wedstrijden het hebben, in
   de oude en in de nieuwe export. Hier hoort de winst thuis, niet in de
   foutenlijst.

4. **Spelers** — hoeveel er vervallen, hoeveel erbij komen, en of de doelpunten
   optellen. Dat laatste is de scherpste controle die er op een export bestaat:
   de som van de eindstanden min de eigen doelpunten hoort gelijk te zijn aan de
   som van de doelpunten van alle spelers. De Transfermarkt-export doorstaat die
   toets (613 − 18 = 595). De Sofascore-export niet: 662 − 17 = 645 tegen 595 via
   de spelers, een gat van vijftig.

De vijftien uitgestelde wedstrijden worden afgevinkt tegen `tm_uitgesteld.json`,
niet tegen hun aantal. Zou er een zestiende verdwijnen om een heel andere reden,
dan valt die niet in die stapel weg maar komt hij er als onverklaard uit.

### Zichzelf nagerekend

35 zelftoetsen, waarvan de helft precies over het onderscheid gaat dat de eerste
versie miste: een ander stadion is géén tegenspraak, een andere uitslag wél; een
spelfout is hernoemen, twee namen die één worden is samenvoegen, en één naam die
twee wordt is het enige dat een melding verdient.

De koppeling zelf is over de échte oude export gehaald, tegen zichzelf: 180 van
180 wedstrijden gekoppeld, 3016 van 3016 spelers, nul tegenspraken — en dat
volledig via de zwakste koppelweg, want bij een zelfvergelijking is er geen
`sofascore_id` en koppelden alle 180 op datum plus clubnamen, zonder één botsing.

### Twee ✗-en die van de vergelijker waren, niet van de data

De eerste echte run gaf 10 punten. Acht ervan waren terecht; twee waren mijn
fout, en allebei van dezelfde soort — de vergelijker kende maar één van de twee
schrijfwijzen.

- **"Ajax - PSV: thuisscore 3 → 1, uitscore 4 → 1."** Dat is de bekerfinale van
  2023: 1-1 na verlenging, met 2-3 beslist. Transfermarkt telt de benutte
  strafschoppen bij de eindstand op (3:4), de parser haalt ze er weer af en legt
  ze apart vast; Sofascore zet de opgetelde stand in de uitslag. De vergelijker
  toetst nu of het verschil in uitslag precies de serie is — is dat zo, dan is
  het een andere afspraak en geen tegenspraak, en wordt het als zodanig gemeld.
  De datum blijft wél meetellen.

- **"Transfermarkt: 613 eindstanden, 595 via spelers, 0 eigen doelpunten ✗."**
  Nul eigen doelpunten in 165 wedstrijden is onmogelijk, en dat was ook precies
  het signaal: Sofascore markeert een eigen doelpunt als `type: "ownGoal"`, de
  Transfermarkt-parser als `type: "own"`. Ik toetste alleen op de eerste. Met
  allebei erin klopt de som: 613 − 18 = 595.

  De Sofascore-export blijft er wél op staan: 662 − 17 = 645 tegen 595 via de
  spelers. Dat gat van vijftig is echt, en het is precies waarom deze toets in
  het rapport staat.

### Wat de vertaaltabel liet zien

De naamwissels waren, zoals verwacht, bijna allemaal spelling: 'Gofferstadion' →
'Goffertstadion', 'Eredivisie 10/11' → 'Eredivisie 2010/11', 43 seizoenen die
alleen anders geschreven worden. De categorie 'gesplitst' leverde wél iets op,
en dat is waar die categorie voor bedoeld was:

- **Zes splitsingen zijn winst.** Transfermarkt houdt uit elkaar wat Sofascore
  samennam: de voorronde van de Champions League is geen Champions League, en de
  Play-Offs van de Jupiler Pro League zijn een eigen competitie.
- **Twee splitsingen zijn een probleem.** 'De Kuip' wordt in de nieuwe data zowel
  'De Kuip' als 'Stadion Feyenoord "De Kuip"', en 'Johan Cruijff Arena' zowel
  'Amsterdam ArenA' als 'Johan Cruijff ArenA'. Transfermarkt noemt hetzelfde
  gebouw per wedstrijd anders — bij de ArenA naar de naam van dat seizoen. In de
  stadionlijst van het dashboard worden dat twee rijen voor één stadion.
- **Eén splitsing is een fout in een van de bronnen.** Sofascore zag 'Pol van
  Boekel' bij een wedstrijd waar Transfermarkt 'Bas Nijhuis' noemt.

## De knopen doorgehakt

Vier beslissingen, vier stukken werk. De vijfde — het toevoegen van een
wedstrijd via Transfermarkt in plaats van Sofascore — is groter en staat nog
open.

### De officiële naam wint

`STADIONNAMEN` in `transfermarkt_dashboard.py` voegt samen wat Transfermarkt per
wedstrijd anders schrijft: `Stadion Feyenoord "De Kuip"` wordt `De Kuip`,
`Amsterdam ArenA` wordt `Johan Cruijff ArenA`. De tabel draait vóór het tellen,
en dat is het hele punt: na het tellen zou de stadionlijst al twee regels hebben
en zou de wedstrijd zelf nog steeds de oude naam tonen.

`sleutelmaker` kon dit niet oplossen. Die knoopt namen aan elkaar via een
gedeeld id, en Transfermarkt geeft stadions geen id — dus zonder tabel zijn het
twee stadions. De zelftest laat dat ook zien: zonder de tabel twee regels, met
de tabel één.

Wie liever de historische naam ziet (in 2018 de Amsterdam ArenA, in 2025 de
Johan Cruijff ArenA) haalt de regel weg; het is één regel.

### De splitsingen noemen hun wedstrijden

`'Pol van Boekel' werd 'Bas Nijhuis', 'Pol van Boekel'` vertelt je dát er iets
niet klopt, maar niet waar je moet kijken — en dat is nu juist het enige wat je
nodig hebt. De vergelijker zet de wedstrijden er nu bij; een tak met hooguit
drie wedstrijden krijgt ze allemaal, een grote tak alleen een telling.

### Een speelschema-cache die weet wat kan veranderen

`--map` haalde alle 56 speelschema's opnieuw op, ook voor één nieuwe wedstrijd.
Ze staan nu in `data/tm_schema_cache/`, met één regel die het verschil maakt:
een afgelopen seizoen verandert niet meer en mag voor altijd op schijf, een
lópend seizoen groeit elke speelronde en wordt altijd opnieuw opgehaald. Juli is
de grens. Anders mis je precies de wedstrijd waarvoor je het draait.

Lukt het ophalen niet, dan wint een oude cache van een leeg schema: die ene
ontbrekende wedstrijd is minder erg dan alle andere kwijtraken. `--ververs` gooit
alles overboord.

### Handmatig koppelen voor wat nergens in staat

De elf oefenduels staan in geen enkel speelschema. `--set-match SOFASCORE_ID
TM_ID` legt zo'n koppeling vast in `data/tm_match_handmatig.json` — een eigen
bestand, want `tm_match_map.json` wordt bij elke `--map` opnieuw geschreven en
wat je met de hand hebt uitgezocht mag daar niet mee weg. Het rapport over
niet-gekoppelde wedstrijden drukt de commandoregel meteen af, met het id erin.

De vier vrouwenwedstrijden blijven buiten de selectie: die staan naar alle
waarschijnlijkheid niet op Transfermarkt.

### Andy Little is nagekeken

TM 1989-05-12 is de juiste; Sofascore had de Noord-Ierse naamgenoot. Hij staat nu
in `NAGEKEKEN`, mét geboortedatum. Die datum is er niet voor de sier: verandert
hij op Transfermarkt, dan geldt het oordeel van toen niet meer en roept de
melding vanzelf opnieuw. Een naam daar neerzetten zonder te kijken maakt de hele
controle waardeloos.

### Wat de scheidsrechters leerden over de grens van deze methode

De splitsing `'Pol van Boekel' werd 'Bas Nijhuis', 'Pol van Boekel'` bleek
NEC - PSV van 30 maart 2024 te zijn: Transfermarkt heeft het goed, Sofascore had
de verkeerde man. Precies waarvoor die categorie bedoeld was.

Maar bij het opzoeken kwam er iets anders boven. PSV - Vitesse van 14 september
2019 werd geleid door Allard Lindhout, en beide bronnen schrijven die wedstrijd
aan Pol van Boekel toe — anders was het een derde tak in die splitsing geweest.

Twee bronnen die dezelfde fout maken vindt geen enkele vergelijking. Alles in
`transfermarkt_vergelijk.py` werkt op het verschil tussen de twee; waar ze het
eens zijn is er niets te zien, of ze samen gelijk hebben of samen ongelijk. Dat
is geen gebrek dat te repareren is, het is wat een vergelijking ís. Het is wel
goed om te weten wat de groene vinkjes in dat rapport betekenen: de twee bronnen
spreken elkaar niet tegen, niet dat de data waar is.

## Een teller die meegroeide met het rapport

De splitsingen kregen hun wedstrijden erbij — `'Pol van Boekel' werd: 'Bas
Nijhuis' — 2024-03-30 NEC Nijmegen - PSV Eindhoven` — en precies daardoor
sprong de eindstand van 9 naar 32 punten, zonder dat er één ding in de data
veranderde. De regel eronder was `fout += len(gesplitst_totaal)`, en
`gesplitst_totaal` was een platte lijst regels. Zolang elke splitsing één regel
kostte klopte dat toevallig; zodra er takken bij kwamen telde hij de uitleg mee
als bevinding.

Dezelfde lijst voedde ook het afkappen, dus `toon_lijst` knipte na vijftien
regels — middenin een splitsing. Wat overbleef was `toernooi: 'UEFA Europa
League' werd:` met niets eronder: een kopregel die je alleen vertelt dat er iets
staat wat je niet mag zien.

Beide komen uit één verkeerde keuze: de regel als eenheid nemen in plaats van de
bevinding. Nu is `gesplitst_totaal` een lijst blokken, telt de eindstand blokken,
en knipt `toon_blokken` tussen blokken. Zeven splitsingen zijn zeven punten,
hoeveel wedstrijden er ook bij staan — en zes daarvan zijn winst: Transfermarkt
houdt de voorrondes van de Champions League en de Europa League apart en scheidt
de play-offs van de Jupiler Pro League. Blijft over: de scheidsrechter.

## De aliastabel leest zichzelf hardop na

Na het samenvoegen van De Kuip en de ArenA stonden er nog steeds 41 stadions in
de export, waar er 39 verwacht werden. De koppeling in `bouw()` klopt — eerst
`hernoem_stadions`, dan pas `tel_stadions` — dus óf een sleutel matcht de
Transfermarkt-spelling niet, óf de regel hernoemt wel maar voegt niets samen
omdat de doelnaam verder nergens voorkomt.

Een aliastabel is stille code: een spelfout in een sleutel levert geen fout op,
alleen een regel die nooit afgaat. `stadionwissels()` meet daarom vóór het
hernoemen hoe vaak elke sleutel voorkomt en of de doelnaam er al is, en het
rapport zet het eronder:

    ✓ 'Amsterdam ArenA' → 'Johan Cruijff ArenA'
          7 wedstrijden, telt nu als één stadion
    · 'Stadion Feyenoord "De Kuip"' → 'De Kuip'
          3 wedstrijden, alleen het label wijzigt
    ✗ 'Gelredome' → 'GelreDome'
          komt in deze data niet voor — sleutel klopt niet

`✗` betekent: die regel doet niets. `·` betekent: hij hernoemt wel, maar de
telling blijft gelijk — precies het verschil tussen 41 en 39. Welke van de drie
het is, zegt de volgende run.

## De tweede helft: vervangen

`vergelijk eerst, vervang daarna` stond overal, maar de vervanging bestond niet
— die was met de hand, en met de hand overschrijf je een keer het verkeerde
bestand. `--vervang` doet het in één stap, met drie regels eromheen.

**Archiveren, niet weggooien.** De Sofascore-export is de enige kopie van wat
die bron ooit zei. Is hij weg, dan is de vergelijking niet meer over te doen en
staat er niets meer tegenover de nieuwe data. Hij gaat dus naar
`data/sofascore_archief/dashboard_data.2026-09-17.json`.

**Eerst alles bewaren, dan pas iets zetten.** Twee losse stappen per bestand
zouden betekenen dat een struikeling halverwege één bestand overschreven
achterlaat waar nog geen kopie van is. Nu zijn het twee rondes: alle kopieën
eerst, alle vervangingen daarna.

**Twee keer op één dag wordt geweigerd.** De tweede keer zou
`dashboard_data.json` archiveren die na de eerste keer al Transfermarkt ís — dat
overschrijft de enige Sofascore-kopie met een duplicaat van de nieuwe data. Het
archiefpad draagt de datum, en een bestaand pad is een bezwaar, geen waarschuwing:
er gebeurt dan niets.

Bezwaren blokkeren de hele omwisseling, ook de stappen die op zichzelf wel
konden. Half omgewisseld is de enige toestand waarin het dashboard een
Sofascore-wedstrijdenlijst naast Transfermarkt-dashboarddata zou lezen.

## Wat de vergelijking uiteindelijk zei

165 gekoppelde wedstrijden, gelijke datum en gelijke uitslag, op één na: de
bekerfinale van 2023, en dat is de strafschoppenafspraak en geen tegenspraak.
Zeven splitsingen, waarvan zes winst — Transfermarkt houdt de voorrondes van de
Champions League en de Europa League apart en scheidt de play-offs van de Jupiler
Pro League, waar Sofascore er één toernooi van maakt.

De zevende is de scheidsrechter, en die valt in het voordeel van de nieuwe bron
uit: bij NEC – PSV van 30-03-2024 zegt Transfermarkt Bas Nijhuis en Sofascore Pol
van Boekel, en Bas Nijhuis is juist.

De dekking gaat overal omhoog behalve bij de ronde (164 → 113). Dat kost niets:
`round` wordt in `dashboard.html` alleen in het zoekpaneel gebruikt, nooit
uit `dashboard_data.json` gelezen om te tonen.

En de optelsom, het scherpste verschil: Transfermarkt 613 − 18 = 595 ✓, Sofascore
662 − 17 = 645 tegen 595 ✗. De nieuwe export klopt met zichzelf, de oude niet.

## Wedstrijd toevoegen via Transfermarkt

Het zoekpaneel praatte volledig met Sofascore. Na de omwisseling zou toevoegen
data opleveren die niet meer bij de rest past, dus het moest om.

**Eerst moest de keten op eigen benen.** `tm_match_map.json` koppelt een
sofascore_id aan een tm_match_id; die koppeling is gemaakt door de
Sofascore-lijst tegen de speelschema's van Transfermarkt te leggen. Daarmee kon
er geen wedstrijd meer bíj, want een nieuwe wedstrijd heeft geen sofascore_id om
vanaf te vertrekken. `data/tm_selectie.json` is nu de bron: een platte lijst
Transfermarkt-wedstrijd-ID's, eenmalig te vullen met `--seed`. Het sofascore_id
blijft bewaard als herkomst, niet als sleutel.

**De omwisseling kondigt zichzelf aan.** De export schrijft zijn eigen herkomst
mee in `source`. De server leest dat veld en kiest daarop zijn keten. Er is geen
instelling om te vergeten om te zetten: zodra `dashboard_data.json` van
Transfermarkt komt, draait de Transfermarkt-keten.

**Drie vragen, geen doorgeefluik.** `/sofascore/` stuurt elk pad door naar de
API. Dat kan bij Transfermarkt niet, want die levert HTML die hier geparst moet
worden — en dat is winst: `/tm/zoek`, `/tm/club/<id>/<seizoen>` en
`/tm/seizoenen` zijn drie afgebakende vragen, er is geen pad waarlangs het
dashboard een willekeurige URL kan laten ophalen.

**Het paneel werd een stap korter.** Bij Sofascore moest je eerst een competitie
kiezen en dan een seizoen. De speelschemapagina van Transfermarkt geeft alle
competities van een seizoen in één keer, dus het zijn nog drie stappen: club,
seizoen, wedstrijden.

### Drie dingen die stil fout zouden zijn gegaan

**Een leeg antwoord dat twee dingen kan betekenen.** `zoek_club` gaf een lege
lijst terug of Transfermarkt nu onbereikbaar was of de naam niet bestond. Het
paneel zou dan "geen clubs gevonden" tonen terwijl er niets gezocht is.
`zoek_club_met_status` geeft de fout mee.

**Het wapen van een willekeurige andere club.** `TeamBadge` bouwt zijn URL uit
een Sofascore-teamnummer. Een Transfermarkt-clubnummer daarin levert geen fout
op maar een bestaand plaatje van een andere club — het soort fout dat niemand
opvalt. De clubwapens gaan nu langs `/img/ext`, dat de host toetst, met
Transfermarkts eigen logohost.

**Toevoegen vóór de omwisseling.** De Transfermarkt-keten schrijft
`dashboard_data.json`. Wie vóór de omwisseling een wedstrijd toevoegt zou die
keten starten en daarmee de Sofascore-export overschrijven zonder dat er ooit
vergeleken is. Alleen de wedstrijd aannemen is net zo fout: hij blijft dan in de
selectie staan en wordt nooit opgehaald. De route weigert en zegt wat er eerst
moet gebeuren; het paneel meldt het al bij binnenkomst.

### De uitslag uit een speelschemarij

Het paneel toont de stand bij elke wedstrijd. Die staat in de rij, maar zo ook
de aftraptijd, en `18:45` ziet er net zo uit als een uitslag. Transfermarkt
schrijft tijden met twee cijfers achter de dubbele punt en uitslagen met één,
dus daarop valt te scheiden — en bij twijfel liever niets tonen dan een
aftraptijd als uitslag.

### Het paneel toetst zichzelf

`test/paneel.test.mjs` rendert het paneel echt in een browser en bedient het
echt, met Transfermarkt onderschept. Dertien toetsen, in dezelfde geest als de
`--zelftest` van de Python-modules: dat een uitwedstrijd de tegenstander links
zet, dat er alleen een nummer, een datum en een naam naar de server gaan, en dat
er geen javascriptfout valt.
