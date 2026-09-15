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

Over de vijftien afwijkingen die de run liet zien: 7× één dag (zesmaal staat TM
een dag later), 2× dag/maand verwisseld, 2× twee dagen, 1× alleen het jaar en
3× geheel anders, waarvan er één (Ben Davies) een bevestigde naamgenoot is.
Alleen die laatste categorie is het nakijken waard, en daar staan nu de clubs
bij: zagen twee bronnen dezelfde naam bij niet-overlappende clubs, dan zijn het
twee mensen en klopt er niets mis. De club is een getuige die losstaat van de
geboortedatum — precies wat een kruiscontrole moet zijn.

Draai `python3 transfermarkt_profiles.py --rapport` voor de indeling over alle
82; dat haalt niets op. `--zelftest` rekent de controle zelf na op twintig
gevallen waarvan de uitkomst vaststaat, inclusief de naamgenoten.

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
