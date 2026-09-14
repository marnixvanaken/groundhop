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
| marktwaarde + historie | spelerprofiel |
| transfers + bedragen | `div.tm-player-transfer-history-grid` |
| interlands + doelpunten | data-header spelerprofiel |

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

**1. ID-namespaces botsen nu al.** De handmatig toegevoegde wedstrijden
gebruiken Transfermarkt-ID's (Van Persie = 1, Sneijder = 1934) in dezelfde
keyspace als Sofascore-ID's. Twee records dragen daardoor data uit beide
bronnen:

| ID | Naam | Symptoom |
|---|---|---|
| `2614` | Klaas-Jan Huntelaar | `teams_seen_for` = AFC Ajax + Netherlands, rating 8.4 |
| `138828` | Jetro Willems | NEC + Heracles + Netherlands, marktwaarde 275.000 |

Ook `51599` (Lee Hodson) draagt een Sofascore-marktwaarde op een TM-ID. Of dit
toevallig correcte merges zijn of vermenging van twee verschillende spelers is
alleen lokaal te controleren — beide bronnen zijn vanuit de CI-omgeving
geblokkeerd. Daarom schrijft de PoC een `id_source`-veld mee.

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

Nog niet gevalideerd: de spelerprofielparser (marktwaarde, transfers,
interlands) draaide alleen tegen een fixture, en de match-parser is op één
wedstrijd getest. Een oude wedstrijd zonder publiekscijfer, een bekerduel met
verlenging of strafschoppen, en een wedstrijd met een rode kaart zijn de
volgende testgevallen.
