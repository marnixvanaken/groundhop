# GroundHop — Design

Werkmap voor de wireframes en het designsysteem in Figma.

De code is de bron van waarheid voor de huidige tokens, Figma is de plek waar
nieuwe schermen bedacht worden. De richting is dus eerst code → Figma
(stap 2), en pas na het ontwerpen weer Figma → code (stap 5).

## Bestanden

| Bestand | Wat |
|---|---|
| `extract_tokens.py` | Leest het token-object `T` uit `dashboard.html` |
| `tokens.json` | Gegenereerd. Importeren in Figma via Tokens Studio |

Opnieuw genereren na een wijziging in `dashboard.html`:

```bash
python3 design/extract_tokens.py
```

## Stap 1 — Figma opzetten

1. Maak een gratis account op figma.com. Het gratis plan is genoeg: drie
   Figma-bestanden, onbeperkt drafts.
2. Haal Apple's officiële kit binnen: zoek op Figma Community naar
   **"iOS and iPadOS 27"** van Apple Design Resources en klik *Open in Figma*.
   Die kit bevat de echte systeemcomponenten, materialen en tekststijlen van
   iOS 27. Gebruik hem als referentie, niet als basis om in te tekenen.
3. Maak een eigen bestand `GroundHop – Design` met deze pages:

```
00 · Cover
01 · Foundations   kleuren, type, spacing, iconen
02 · Components    Card, Pill, StatBox, TabBar, …
03 · Wireframes    lo-fi, grijstinten
04 · UI            hi-fi, glass
05 · Archive
```

## Stap 2 — Tokens importeren

1. Plugins → zoek **Tokens Studio for Figma** → Run.
2. In de plugin: Tools → *Load from file* → kies `design/tokens.json`.
3. Ga naar Themes en maak twee themes aan: `Light` (sets `core` + `light`) en
   `Dark` (sets `core` + `dark`).
4. Klik *Export to Figma* → als **Variables**, niet als Styles. Dan krijg je
   één collectie met twee modes en kun je elk frame met één klik omschakelen
   tussen licht en donker.

Je hebt nu exact dezelfde 26 kleuren, 6 spacing-waarden en 6 tekstgroottes in
Figma als in `dashboard.html`.

## Stap 3 — Wireframes

Frames, afgeleid van de enige breakpoint in de CSS (`min-width: 768px`):

| Frame | Breedte | Waarvoor |
|---|---|---|
| Mobile | 402 × 874 | primair, dit is een mobile-first app |
| Tablet | 768 | hier wisselt `ContinentView` naar `WorldMap` |
| Desktop | 1440 | content gecentreerd, max 460–720 breed |

Vaste marges: 16px links en rechts, 130px onderaan vrijhouden voor de
zwevende navigatiebalk.

Te tekenen schermen, per tab uit `TABS` in `dashboard.html`:

- [ ] Home — stat band, Gezien XI, Records, Recent, Competities, Per seizoen, Landen
- [ ] Spelers — lijst met filters
- [ ] Speler detail
- [ ] Clubs — lijst
- [ ] Club detail
- [ ] Duels — matchlijst per seizoen
- [ ] Stadions
- [ ] Zoeken — alleen lokaal zichtbaar (`IS_LOCAL`)

En de toestanden die makkelijk vergeten worden:

- [ ] Leeg — nog geen wedstrijden toegevoegd
- [ ] Laden — skeletons
- [ ] Fout — data niet opgehaald
- [ ] Sync — de `SyncBanner` met voortgang

Teken deze in grijstinten, zonder blur en zonder kleur. Wireframes gaan over
volgorde, hiërarchie en wat er op het scherm past — niet over hoe het glas
eruitziet.

## Stap 4 — iOS 27 en Liquid Glass

iOS 27 heeft een transparantie-slider in Instellingen → Weergave. De gebruiker
bepaalt zelf hoeveel doorschijnendheid er is. Ontwerp daarom zo dat het scherm
klopt bij elke stand van die slider:

- Bouw contrast op tussen tekst en de **card-vulling**, niet tussen tekst en
  de achtergrond die erdoorheen schijnt.
- Controleer elk scherm tweemaal: met de cards op volle dekking en op de
  laagste. Blijft alles leesbaar, dan klopt het.
- Zet nooit tekst kleiner dan 12px op glas. De huidige `caption` van 10px in
  `StatBox` is een aandachtspunt.

Figma kent alleen *Background blur* en geen `saturate()` of `brightness()`
zoals de CSS. Glas ziet er in Figma dus altijd wat doffer uit dan in de
browser. Probeer dat niet na te bouwen met extra lagen — controleer het
eindresultaat in de echte app.

## Stap 5 — Eigen kleuren

De huidige palet-waarden zijn de systeemkleuren van Apple: `#007AFF` is
systemBlue, `#34C759` is systemGreen. Dat voelt native, maar is niet van
GroundHop.

Wissel alleen de **accentkleur** om en laat de structuur staan. Het logo
gebruikt al groen voor "Ground", dus groen als accent en blauw degraderen tot
gewone datakleur ligt voor de hand. Elke accentkleur heeft twee varianten
nodig, zoals `green` en `greenDark` nu al doen: een vollere voor vlakken en
badges, een donkere voor tekst op een lichte achtergrond.

Is de kleur in Figma gekozen, dan gaat hij terug naar het `T`-object in
`dashboard.html` en draai je `extract_tokens.py` opnieuw.
