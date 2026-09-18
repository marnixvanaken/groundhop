# GroundHop — Design

Werkmap voor het herontwerp. Figma-bestand: `GroundHop – Design`.

## Bestanden

| Bestand | Wat |
|---|---|
| `extract_tokens.py` | Leest het token-object `T` uit `dashboard.html` |
| `tokens.json` | Gegenereerd. Importeren in Figma via Tokens Studio |

Opnieuw genereren na een wijziging in `dashboard.html`:

```bash
python3 design/extract_tokens.py
```

## Wat er in de data zit

Gemeten op `data/dashboard_data.json`, stand 14 april 2026.

| | Aantal | Dekking |
|---|---|---|
| Wedstrijden | 180 | 2008-06-01 t/m 2026-04-11 |
| Goals gezien | 653 | 175 duels met complete goal-lijst |
| Stadions | 31 | in 27 steden, 140 bezoeken |
| Spelers | 3016 | 2200 kwamen ook echt in actie |
| Landen | 121 | nationaliteiten van die spelers |
| Clubs | 109 | |
| Toernooien | 21 | over 54 seizoenen |
| Scheidsrechters | 64 | 158 van de 180 duels gedekt |

Vier observaties die het ontwerp sturen:

**Philips Stadion is 94 van de 140 stadionbezoeken.** Twee derde van alles speelt
zich op één plek af, en 25 van de 31 stadions zijn precies één keer bezocht. Het
verhaal is dus één thuisbasis met een lange staart, niet een gelijkmatige
verzameling. Een raster van 31 gelijke tegels vertelt dat verkeerd.

**121 landen is het grootste getal in de dataset.** Opgebouwd uit 180
wedstrijden. Dat cijfer verdient een eigen ingang in plaats van een lijstje
onderaan Home.

**De rijkste objecten hebben geen detailscherm.** Er is `PlayerDetail` en
`ClubDetail`, maar geen wedstrijd- en geen stadiondetail — terwijl per duel de
goals met minuut, assist en type klaarliggen, plus scheidsrechter, stadion en
soms publiek.

**De scheidsrechters worden nergens getoond.** 64 arbiters met een gemiddeld
aantal gele kaarten per wedstrijd, volledig ongebruikt in de UI.

### Twee dingen om rekening mee te houden

Publiekscijfers zijn er bij **41 van de 180** wedstrijden. Het record "meeste
toeschouwers" rust dus op een kwart van de data. Toon dat eerlijk of laat het weg.

Het veld `lineup` staat op **1 van de 180** wedstrijden. De opstelling is
desondanks te reconstrueren: via `players[].matches_detail` is 179 van de 180
wedstrijden gedekt, met een mediaan van 43 spelers per duel, inclusief
starter-vlag, minuten, rating, goals en assists.

## Richting

De wedstrijd is het atoom. Elk duel knoopt een stadion, twee clubs, een
toernooi, een scheidsrechter en zo'n 43 spelers aan elkaar. Zodra dat scherm
bestaat, krijgen spelers en stadions allebei diepte, want beide kanten linken
erheen.

Vijf tabs:

| Tab | Inhoud |
|---|---|
| Home | Het logboek kort: duels, landen, grounds, laatst gezien |
| Duels | 180 wedstrijden per seizoen → wedstrijddetail |
| Grounds | Kaart en lijst → stadiondetail |
| Spelers | 3016 spelers, 121 landen, Gezien XI |
| Meer | Clubs, toernooien, scheidsrechters, records, seizoenen |

## Wireframe-inventaris

Nieuw, in volgorde van aanpak:

- [ ] Wedstrijddetail — scorebord, goaltijdlijn, opstelling, scheids, stadion
- [ ] Stadiondetail — eerste en laatste bezoek, duels daar, gemiddelden
- [ ] Landendetail — welke spelers uit dit land, in welke duels
- [ ] Home, nieuwe opzet
- [ ] Duels, lijst per seizoen
- [ ] Grounds, kaart en lijst
- [ ] Spelers, lijst en filters
- [ ] Meer

Toestanden die bij elk scherm horen:

- [ ] Leeg, laden, fout
- [ ] Ontbrekende velden: geen publiek, geen scheidsrechter, geen stadionnaam

## Figma-opzet

Pages: `00 · Cover`, `01 · Foundations`, `02 · Components`, `03 · Wireframes`,
`04 · UI`, `05 · Archive`.

Frames: mobiel 402 × 874 als uitgangspunt, 768 waar `ContinentView` naar
`WorldMap` wisselt, 1440 voor desktop. Marges 16px, onderaan 130px vrij voor de
zwevende navigatiebalk.

Variabelen staan in de collectie `color` met de modes Light en Dark, plus `core`
voor spacing, radius en typografie. De collectie `_bron dark` levert de donkere
waarden en wordt niet direct gebruikt bij het ontwerpen.

Wireframes in grijstinten, zonder blur en zonder kleur. Kleur komt pas op
page 04.

## iOS 27 en Liquid Glass

iOS 27 heeft een transparantie-slider in Instellingen → Weergave, waarmee de
gebruiker zelf bepaalt hoeveel doorschijnendheid er is. Elk scherm moet dus
kloppen bij elke stand:

- Bouw contrast op tussen tekst en de card-vulling, niet tussen tekst en de
  achtergrond die erdoorheen schijnt.
- Controleer elk scherm met de cards op volle dekking en op de laagste.
- Geen tekst kleiner dan 12px op glas. De 10px caption in `StatBox` is een
  aandachtspunt.

Figma kent alleen *Background blur*, geen `saturate()` of `brightness()`. Glas
oogt daar dus doffer dan in de browser. Niet nabouwen met extra lagen;
controleer het eind in de echte app.

## Huisstijl

De huidige waarden zijn Apple's systeemkleuren: `#007AFF` is systemBlue,
`#34C759` is systemGreen. Native, maar niet van GroundHop.

Wissel de accentkleur en laat de structuur staan. Het logo zet `Ground` al in
het groen, dus groen als accent en blauw terug naar gewone datakleur. Elke
accentkleur heeft twee varianten nodig, zoals `green` en `greenDark` nu al doen:
een vollere voor vlakken en badges, een donkere voor tekst op licht.

Is de kleur in Figma gekozen, dan gaat hij terug naar het `T`-object in
`dashboard.html` en draai je `extract_tokens.py` opnieuw.
