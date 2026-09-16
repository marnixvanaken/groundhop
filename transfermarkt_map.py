#!/usr/bin/env python3
"""
Transfermarkt ID-mapper
=======================

Koppelt de wedstrijden in data/selected_matches.json aan Transfermarkt-ID's.
Dit is de voorwaarde voor de volledige migratie: de bestaande data hangt aan
Sofascore-ID's waarvoor geen mappingtabel bestaat.

Werkwijze
---------
Per (bron-club, seizoen) wordt het speelschema opgehaald. Dat bevat thuis- én
uitduels, dus 48 pagina's dekken alle 179 wedstrijden.

Twee keuzes maken dit robuust:

1. De parser zoekt links naar /spielbericht/ en loopt omhoog naar de
   omliggende tabelrij, in plaats van class-namen vast te leggen. Dat
   overleeft opmaakwijzigingen.
2. Koppelen gebeurt op datum, niet op clubnaam. Een club speelt per dag
   hooguit één wedstrijd, dus dat omzeilt "PSV Eindhoven" versus "PSV".
   De clubnamen worden alleen gebruikt als controle achteraf.

Gebruik
-------
    # Zoek de Transfermarkt-ID van een club
    python3 transfermarkt_map.py --search "PSV Eindhoven"

    # Bekijk één speelschema (controleer de parser voordat je alles draait)
    python3 transfermarkt_map.py --fixtures 383 --season 2025

    # Volledige koppeling; schrijft data/tm_match_map.json
    python3 transfermarkt_map.py --map

    # Alleen de clubs oplossen, zonder speelschema's op te halen
    python3 transfermarkt_map.py --clubs
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
import unicodedata
from pathlib import Path

from transfermarkt_poc import (BASE, HEADERS, _IMPERSONATE, _datum_nl, _http,
                               _knip, soep)

SELECTED = Path("data/selected_matches.json")
CLUB_MAP = Path("data/tm_club_map.json")
DASHBOARD = Path("data/dashboard_data.json")
MATCH_MAP = Path("data/tm_match_map.json")
UITGESTELD = Path("data/tm_uitgesteld.json")

SPIELBERICHT_RE = re.compile(r"/spielbericht/index/spielbericht/(\d+)")
VEREIN_RE = re.compile(r"/verein/(\d+)")
MIN_DELAY, MAX_DELAY = 2.0, 4.0


def wacht():
    time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))


def saison_van(datum: str) -> int:
    """Transfermarkt nummert een seizoen op het startjaar; juli is de grens."""
    jaar, maand = int(datum[:4]), int(datum[5:7])
    return jaar if maand >= 7 else jaar - 1


# Alleen echt generieke aanduidingen. Let op: clubafkortingen die de identiteit
# dragen (PSV, VVV, RKC) horen hier NIET in — die wegstrepen maakt "PSV" leeg.
_GENERIEK = {"fc", "afc", "sc", "ac", "as", "ss", "cf", "bv", "nv", "vfb", "vfl",
             "club", "1899", "1900", "04", "united", "royal"}


def _kernwoorden(naam: str) -> list[str]:
    t = unicodedata.normalize("NFKD", naam or "").encode("ascii", "ignore").decode()
    woorden = [w for w in re.split(r"[^a-z0-9]+", t.lower()) if w]
    return [w for w in woorden if w not in _GENERIEK] or woorden


def lijkt_op(a: str, b: str) -> bool:
    """
    Controle achteraf op de datumkoppeling, niet de koppeling zelf.

    Regel: de kortste naam moet volledig in de langste zitten. Dat laat
    'PSV' ~ 'PSV Eindhoven' toe, maar houdt 'Real Madrid' ~ 'Real Sociedad'
    tegen — die delen alleen een generiek eerste woord.
    """
    ka, kb = _kernwoorden(a), _kernwoorden(b)
    if not ka or not kb:
        return False
    kort, lang = (ka, kb) if len(ka) <= len(kb) else (kb, ka)
    if set(kort) <= set(lang):
        return True
    ja, jb = "".join(ka), "".join(kb)
    return ja in jb or jb in ja


def _kwal_sig(naam: str) -> frozenset:
    """
    Canonieke 'kwalificatie' van een clubnaam: jeugd, vrouwen, beloften.

    Dit is de belangrijkste veiligheidsklep. Zonder deze controle valt
    'Jong PSV Eindhoven' samen met 'PSV', en wordt een jeugdwedstrijd aan de
    seniorenwedstrijd van diezelfde dag gekoppeld — dat gebeurde met
    Lens U19 - PSV U19, die aan RC Lens - PSV werd gehangen.

    'Onder 19', 'U19' en 'UEFA U19' leveren allemaal {'u19'} op.
    """
    woorden = _kernwoorden(naam)
    sig = set()
    for i, t in enumerate(woorden):
        if t in ("jong", "youth", "jeugd", "beloften"):
            sig.add("jong")
        elif t in ("vrouwen", "women", "dames", "feminin", "feminines", "dytiko"):
            sig.add("vrouwen")
        elif t == "ii":
            sig.add("ii")
        elif re.fullmatch(r"u\d{2}", t):
            sig.add(t)
        elif t in ("onder", "under") and i + 1 < len(woorden) and woorden[i + 1].isdigit():
            sig.add(f"u{woorden[i + 1]}")
    return frozenset(sig)


# De .nl-site gebruikt Nederlandse clubnamen, de bestaande data Engelse. Zonder
# deze tabel vindt 'Netherlands' de club 'Nederland' niet, ook al staat die in
# de zoekresultaten.
_ALIASSEN = {
    "netherlands": ["nederland"],
    "standard liege": ["standard luik"],
    "bayern munich": ["bayern munchen"],
    "cologne": ["koln"],
    "the hague": ["den haag"],
    "spain": ["spanje"], "germany": ["duitsland"], "belgium": ["belgie"],
    "france": ["frankrijk"], "italy": ["italie"], "england": ["engeland"],
    "wales": ["wales"], "northern ireland": ["noord ierland"],
}


def _naamvormen(naam: str) -> list[str]:
    """Geeft de naam plus bekende anderstalige varianten."""
    plat = " ".join(_kernwoorden(naam))
    return [naam] + _ALIASSEN.get(plat, [])


def namen_matchen(a: str, b: str) -> bool:
    """
    Naamvergelijking die de aliastabel meeneemt.

    lijkt_op() alleen is niet genoeg voor de controle achteraf: Transfermarkt
    noemt de tegenstander 'Italië' waar de eigen data 'Italy' zegt, en
    'Noord-Ierland' waar er 'Northern Ireland' staat. Beide koppelingen waren
    correct maar werden afgekeurd.
    """
    for va in _naamvormen(a):
        for vb in _naamvormen(b):
            if lijkt_op(va, vb):
                return True
    return False


def kies_club(naam: str, kandidaten: list[dict]) -> tuple[dict | None, list[dict]]:
    """
    Kiest de beste club, of niets bij twijfel.

    Geeft bewust GEEN terugval op 'de eerste kandidaat'. Dat deed de vorige
    versie, waardoor Netherlands, Standard Liège, Jong PSV en PSV U19 alle vier
    op PSV uitkwamen: de zoekpagina bevat zijbalklinks naar clubs, en 'PSV' won
    de sortering op naamlengte.
    """
    qk = _kwal_sig(naam)
    vormen = [set(_kernwoorden(v)) for v in _naamvormen(naam)]
    scored = []
    for k in kandidaten:
        c, ck = set(_kernwoorden(k["name"])), _kwal_sig(k["name"])
        if qk != ck:          # jeugd/vrouwen nooit op het seniorenteam laten vallen
            continue
        beste = None
        for q in vormen:
            if q == c:
                s = 0
            elif q <= c:
                s = len(c - q)
            elif c <= q:
                s = len(q - c)
            else:
                continue
            beste = s if beste is None else min(beste, s)
        if beste is None:
            continue
        scored.append((beste, k))

    if not scored:
        return None, kandidaten[:6]
    scored.sort(key=lambda x: x[0])
    if len(scored) > 1 and scored[0][0] == scored[1][0]:
        return None, [k for _, k in scored[:6]]      # even goed: laat de mens kiezen
    return scored[0][1], []


# ─── Club zoeken ─────────────────────────────────────────────────────────────

def zoek_club(naam: str, toon: bool = False) -> list[dict]:
    """Zoekt clubs via de snelzoekfunctie. Geeft kandidaten met ID en naam."""
    url = f"{BASE}/schnellsuche/ergebnis/schnellsuche"
    try:
        resp = _http.get(url, params={"query": naam}, headers=HEADERS,
                         timeout=25, **_IMPERSONATE)
    except Exception as e:
        print(f"  ! zoeken mislukt: {type(e).__name__}: {e}")
        return []
    if resp.status_code != 200:
        print(f"  ! HTTP {resp.status_code} bij zoeken op {naam!r}")
        return []

    s = soep(resp.text)
    gezien, kandidaten = set(), []
    for a in s.find_all("a", href=VEREIN_RE):
        href = a.get("href", "")
        # Alleen clubprofiel-links; sla logo's en competitielinks over.
        if "/startseite/verein/" not in href and "/spielplan/verein/" not in href:
            continue
        cid = int(VEREIN_RE.search(href).group(1))
        tekst = a.get_text(strip=True) or a.get("title", "")
        if not tekst or cid in gezien:
            continue
        gezien.add(cid)
        kandidaten.append({"id": cid, "name": tekst,
                           "slug": href.strip("/").split("/")[0]})

    # Exacte naamovereenkomst eerst.
    kandidaten.sort(key=lambda k: (not lijkt_op(k["name"], naam), len(k["name"])))
    if toon:
        print(f"\n  Zoekresultaten voor {naam!r}:")
        for k in kandidaten[:8]:
            merk = "→" if lijkt_op(k["name"], naam) else " "
            print(f"   {merk} {k['id']:>7}  {k['name']}")
        if not kandidaten:
            print("    geen clubs gevonden")
    return kandidaten


# ─── Speelschema ─────────────────────────────────────────────────────────────

def _rij_van(link):
    """Loopt omhoog naar de omliggende <tr>; anders het dichtstbijzijnde blok."""
    el = link
    for _ in range(8):
        el = el.parent
        if el is None:
            return None
        if el.name in ("tr", "li"):
            return el
    return link.parent


def _datum_uit_rij(rijtekst: str) -> str:
    """
    Leest een datum uit een speelschemarij.

    /spielplandatum/ schrijft 'zo 03-08-25', /spielplan/ schrijft
    'za 9 aug. 2025'. Beide vormen worden geprobeerd, zodat de parser niet
    afhangt van welke van de twee pagina's gebruikt wordt.
    """
    m = re.search(r"(\d{1,2})[-./](\d{1,2})[-./](\d{2,4})", rijtekst)
    if m:
        jaar = int(m.group(3))
        jaar += 2000 if jaar < 100 else 0
        return f"{jaar:04d}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    return _datum_nl(rijtekst)


def _thuis_of_uit(rij) -> str | None:
    """
    Leest de T/U-kolom: speelde de club thuis of uit?

    Dat maakt de controle sterker dan alleen kijken of een van beide clubnamen
    voorkomt — we weten dan welke kant de tegenstander hoort te zijn.
    """
    for span in rij.find_all("span", title=True):
        titel = span["title"].lower()
        if "thuis" in titel or "heim" in titel or "home" in titel:
            return "thuis"
        if "uit" in titel or "ausw" in titel or "away" in titel:
            return "uit"
    for td in rij.find_all("td"):
        tekst = td.get_text(strip=True)
        if tekst in ("T", "H"):
            return "thuis"
        if tekst in ("U", "A"):
            return "uit"
    return None


def speelschema(club_id: int, saison: int, toon: bool = False) -> list[dict]:
    """
    Haalt het speelschema van een club voor één seizoen op.

    Gebruikt /spielplandatum/: die pagina schrijft datums numeriek, terwijl
    /spielplan/ een tekstuele maand gebruikt. Gemeten op PSV 2025/26 gaf
    /spielplandatum/ 40 van 40 leesbare rijen, /spielplan/ nul.

    Zoekt links naar /spielbericht/ en leest datum, tegenstander en thuis/uit
    uit de omliggende rij. Legt bewust geen class-namen vast.
    """
    url = f"{BASE}/club/spielplandatum/verein/{club_id}/saison_id/{saison}"
    try:
        resp = _http.get(url, headers=HEADERS, timeout=30, **_IMPERSONATE)
    except Exception as e:
        print(f"  ! ophalen mislukt: {type(e).__name__}: {e}")
        return []
    if resp.status_code != 200:
        print(f"  ! HTTP {resp.status_code} voor club {club_id} seizoen {saison}")
        return []

    s = soep(resp.text)
    wedstrijden, gezien = [], set()
    for a in s.find_all("a", href=SPIELBERICHT_RE):
        mid = int(SPIELBERICHT_RE.search(a["href"]).group(1))
        if mid in gezien:
            continue
        rij = _rij_van(a)
        if rij is None:
            continue
        rijtekst = rij.get_text(" ", strip=True)
        datum = _datum_uit_rij(rijtekst)
        if not datum:
            continue

        # Op deze pagina is alleen de tegenstander gelinkt; de club zelf niet.
        clubs = []
        for cl in rij.find_all("a", href=VEREIN_RE):
            naam = cl.get_text(strip=True) or cl.get("title", "")
            cid = int(VEREIN_RE.search(cl["href"]).group(1))
            if naam and not any(c["id"] == cid for c in clubs):
                clubs.append({"id": cid, "name": naam})

        gezien.add(mid)
        wedstrijden.append({
            "match_id": mid, "date": datum,
            "clubs": clubs,
            "kant": _thuis_of_uit(rij),
            "rij": _knip(rijtekst, 140),
        })

    if toon:
        print(f"\n  Speelschema club {club_id}, seizoen {saison}: "
              f"{len(wedstrijden)} wedstrijden")
        for w in wedstrijden[:15]:
            namen = " / ".join(c["name"] for c in w["clubs"]) or "(geen clublinks)"
            kant = {"thuis": "T", "uit": "U"}.get(w["kant"], "?")
            print(f"   {w['date']}  {kant}  id={w['match_id']:<9} {namen}")
        if len(wedstrijden) > 15:
            print(f"   ... en nog {len(wedstrijden) - 15}")
        if not wedstrijden:
            print("    !! niets gevonden — parser of URL klopt niet")
            print(f"    URL: {url}")
            print("    draai --probe-fixtures om te zien waar het misgaat")
    return wedstrijden


def probe_speelschema(club_id: int, saison: int, dump: Path | None = None):
    """
    Test welke URL het speelschema levert en waar de parser op stukloopt.

    Onderscheidt twee foutbeelden die er in het rapport hetzelfde uitzien:
    geen /spielbericht/-links op de pagina, of wel links maar geen leesbare
    datum in de omliggende rij.
    """
    kandidaten = [
        ("dummy-slug + seizoen",  f"{BASE}/club/spielplan/verein/{club_id}/saison_id/{saison}"),
        ("echte slug + seizoen",  f"{BASE}/psv/spielplan/verein/{club_id}/saison_id/{saison}"),
        ("zonder seizoen",        f"{BASE}/club/spielplan/verein/{club_id}"),
        ("spielplandatum",        f"{BASE}/club/spielplandatum/verein/{club_id}/saison_id/{saison}"),
        ("leistungsdaten",        f"{BASE}/club/leistungsdaten/verein/{club_id}/saison_id/{saison}"),
    ]
    print(f"\n{'=' * 78}\n  SPEELSCHEMA-PROBE club {club_id}, seizoen {saison}\n{'=' * 78}")
    for naam, url in kandidaten:
        print(f"\n▼ {naam}\n  {url}")
        try:
            resp = _http.get(url, headers=HEADERS, timeout=30, **_IMPERSONATE)
        except Exception as e:
            print(f"  ✗ {type(e).__name__}: {e}")
            continue
        body = resp.text or ""
        print(f"  status={resp.status_code}  lengte={len(body):,}")
        if resp.status_code != 200:
            continue

        s = soep(body)
        titel = s.find("title")
        print(f"  titel: {_knip(titel.get_text(strip=True) if titel else '(geen)', 90)}")

        links = s.find_all("a", href=SPIELBERICHT_RE)
        print(f"  /spielbericht/-links: {len(links)}")
        if not links:
            # Geen wedstrijdlinks: klopt de URL wel, en welke tabellen staan er?
            print(f"  tabellen: {len(s.select('table'))}  responsive-table: "
                  f"{len(s.select('div.responsive-table'))}")
            hrefs = {a['href'].split('/')[1] for a in s.find_all('a', href=True)
                     if a['href'].startswith('/') and len(a['href'].split('/')) > 1}
            print(f"  eerste padsegmenten op de pagina: {sorted(hrefs)[:14]}")
            if dump:
                dump.mkdir(parents=True, exist_ok=True)
                pad = dump / f"fixtures_{club_id}_{saison}_{re.sub(r'[^a-z]+','_',naam)}.html"
                pad.write_text(body, encoding="utf-8")
                print(f"  ✓ bewaard: {pad}")
            continue

        # Wel links: hoeveel rijen leveren een bruikbare datum?
        met_datum, zonder_datum = 0, []
        for a in links[:40]:
            rij = _rij_van(a)
            rijtekst = rij.get_text(" ", strip=True) if rij else ""
            if _datum_uit_rij(rijtekst):
                met_datum += 1
            elif len(zonder_datum) < 3:
                zonder_datum.append((rij.name if rij else "?", _knip(rijtekst, 130)))
        print(f"  rijen met leesbare datum: {met_datum} van {min(len(links), 40)}")
        for tag, tekst in zonder_datum:
            print(f"    geen datum in <{tag}>: {tekst}")
        eerste = _rij_van(links[0])
        if eerste is not None:
            print(f"  EERSTE RIJ ruw: {_knip(str(eerste), 700)}")
        if dump:
            dump.mkdir(parents=True, exist_ok=True)
            pad = dump / f"fixtures_{club_id}_{saison}.html"
            pad.write_text(body, encoding="utf-8")
            print(f"  ✓ bewaard: {pad}")


# ─── Volledige koppeling ─────────────────────────────────────────────────────

def wordt_overgeslagen(match: dict) -> str | None:
    """
    Geeft een reden als deze wedstrijd bewust niet gemigreerd wordt, anders None.

    Vrouwenwedstrijden staan op Transfermarkt onder een eigen club die de
    snelzoekfunctie niet oplevert. Bewust uitgesteld in plaats van halfbakken
    gekoppeld; ze worden vastgelegd in data/tm_uitgesteld.json.
    """
    toernooi = (match.get("tournament") or "").lower()
    ploegen = f"{match['home_team']['name']} {match['away_team']['name']}".lower()
    if any(w in toernooi for w in ("vrouwen", "women", "dames")) or \
            any(w in ploegen for w in ("vrouwen", "women")):
        return "vrouwenvoetbal — uitgesteld"
    return None


def bron_club(match: dict) -> str:
    """
    De club wiens speelschema deze wedstrijd bevat.

    Vrouwenwedstrijden staan in de eigen data onder de mannennaam ("PSV
    Eindhoven"), terwijl het toernooiveld wel klopt ("Eurojackpot Vrouwen
    Eredivisie"). Op Transfermarkt is dat een aparte club, dus leiden we de
    juiste naam uit het toernooi af.
    """
    club = match.get("source_team") or match["home_team"]["name"]
    toernooi = (match.get("tournament") or "").lower()
    if any(w in toernooi for w in ("vrouwen", "women", "dames", "feminin")):
        if not any(w in club.lower() for w in ("vrouwen", "women", "dames")):
            return f"{club} Vrouwen"
    return club


def los_clubs_op(namen: list[str]) -> dict:
    """
    Zoekt per clubnaam de Transfermarkt-ID. Hergebruikt een eerdere run, zodat
    handmatige correcties in data/tm_club_map.json blijven staan.

    Clubs die niet eenduidig op te lossen zijn, worden als onopgelost
    weggeschreven en apart gerapporteerd — nooit geraden.
    """
    bekend = json.loads(CLUB_MAP.read_text("utf-8")) if CLUB_MAP.exists() else {}

    # Een eerdere versie koos bij twijfel blind de eerste kandidaat, waardoor
    # Netherlands en Standard Liège als PSV in de cache belandden. Controleer
    # daarom of elke gecachte keuze nu nog gekozen zou worden.
    verdacht = [n for n, info in bekend.items()
                if info and kies_club(n, [info])[0] is None]
    for n in verdacht:
        print(f"  ! gecachte koppeling {n!r} → {bekend[n]['name']!r} afgekeurd, opnieuw zoeken")
        bekend[n] = None

    nieuw, open_staand = 0, []
    for naam in namen:
        if bekend.get(naam) is not None:
            continue
        print(f"  zoeken: {naam}")
        kandidaten = zoek_club(naam)
        beste, twijfel = kies_club(naam, kandidaten)
        if beste:
            bekend[naam] = beste
            print(f"    → {beste['id']} {beste['name']}")
        else:
            bekend[naam] = None
            open_staand.append((naam, twijfel))
            print("    → ONOPGELOST")
            for k in twijfel[:4]:
                print(f"        kandidaat: {k['id']:>7}  {k['name']}")
        nieuw += 1
        wacht()

    if nieuw:
        CLUB_MAP.parent.mkdir(exist_ok=True)
        CLUB_MAP.write_text(json.dumps(bekend, ensure_ascii=False, indent=2), "utf-8")
        print(f"\n  ✓ {CLUB_MAP} bijgewerkt ({nieuw} verwerkt)")

    if open_staand:
        print(f"\n  ▼ {len(open_staand)} clubs onopgelost — zet ze handmatig:")
        for naam, twijfel in open_staand:
            print(f"    python3 transfermarkt_map.py --set-club {naam!r} ID")
            for k in twijfel[:6]:
                print(f"        {k['id']:>7}  {k['name']}")
    return bekend


def zet_club(naam: str, club_id: int):
    """Legt een clubkoppeling handmatig vast in data/tm_club_map.json."""
    bekend = json.loads(CLUB_MAP.read_text("utf-8")) if CLUB_MAP.exists() else {}
    bekend[naam] = {"id": club_id, "name": f"(handmatig) {naam}", "slug": "club"}
    CLUB_MAP.parent.mkdir(exist_ok=True)
    CLUB_MAP.write_text(json.dumps(bekend, ensure_ascii=False, indent=2), "utf-8")
    print(f"  ✓ {naam!r} → {club_id} vastgelegd in {CLUB_MAP}")


def extra_uit_export(matches: list[dict], export: list[dict]) -> list[dict]:
    """Wat staat er in de dashboard-export dat niet in de selectie staat?"""
    bekend = {m.get("id") for m in matches if m.get("id") is not None}
    gezien, extra = set(), []
    for m in export:
        mid = m.get("id")
        # Zonder id valt een wedstrijd nergens aan te koppelen, en dan hoort
        # hij ook hier niet ongemerkt binnen te glippen.
        if mid is None or mid in bekend or mid in gezien:
            continue
        gezien.add(mid)
        extra.append(m)
    return extra


def te_koppelen_wedstrijden() -> list[dict]:
    """
    De wedstrijden die gekoppeld moeten worden: selected_matches.json, plus wat
    alleen nog in de dashboard-export zit.

    Die twee horen gelijk te lopen en doen dat niet. NEC - PSV van 13 maart 2011
    staat wel in de export en niet in de selectie. Hoe dat zo gekomen is doet er
    niet meer toe; wat telt is dat de volgende export de selectie als bron neemt
    en die wedstrijd dan zonder één melding verdwijnt. De export is het
    feitelijke register van wat er gezien is, dus telt hij mee — en wordt
    gemeld, want stilzwijgend bijtrekken is precies hoe hij zoekraakte.
    """
    matches = json.loads(SELECTED.read_text("utf-8"))
    print(f"  {len(matches)} wedstrijden in {SELECTED}")
    if not DASHBOARD.exists():
        return matches
    export = json.loads(DASHBOARD.read_text("utf-8")).get("matches") or []
    extra = extra_uit_export(matches, export)
    if extra:
        print(f"  {len(extra)} staan alleen in {DASHBOARD} en tellen mee:")
        for m in extra:
            print(f"    {m.get('date', '?')}  {m['home_team']['name']} - "
                  f"{m['away_team']['name']}")
    return matches + extra


def koppel_alles():
    """Koppelt elke geziene wedstrijd aan een TM-match-ID."""
    matches = te_koppelen_wedstrijden()

    # Stap 1: welke (club, seizoen)-paren moeten opgehaald worden?
    paren = {}
    overgeslagen = [(m, wordt_overgeslagen(m)) for m in matches if wordt_overgeslagen(m)]
    te_koppelen = [m for m in matches if not wordt_overgeslagen(m)]
    if overgeslagen:
        print(f"  {len(overgeslagen)} bewust overgeslagen "
              f"({overgeslagen[0][1]})")
    for m in te_koppelen:
        club, saison = bron_club(m), saison_van(m["date"])
        paren.setdefault((club, saison), []).append(m)
        # Oefenduels in de voorbereiding staan op Transfermarkt soms nog onder
        # het afgelopen seizoen. De index is op (club, datum), dus een extra
        # speelschema kan alleen maar treffers opleveren.
        if int(m["date"][5:7]) in (7, 8):
            paren.setdefault((club, saison - 1), [])
    print(f"  {len(paren)} speelschema's op te halen\n")

    # Stap 2: club-ID's oplossen.
    clubs = los_clubs_op(sorted({c for c, _ in paren}))

    # Stap 3: speelschema's ophalen en indexeren op datum.
    print(f"\n  Speelschema's ophalen...")
    index: dict[tuple, list] = {}
    mislukt = []
    for i, ((club, saison), eigen) in enumerate(sorted(paren.items()), 1):
        info = clubs.get(club)
        if not info:
            mislukt.append((club, saison, "club-ID onbekend"))
            continue
        print(f"  [{i}/{len(paren)}] {club} {saison}/{str(saison+1)[-2:]}", end="")
        ws = speelschema(info["id"], saison)
        print(f" — {len(ws)} wedstrijden")
        if not ws:
            # Een leeg speelschema betekent vrijwel altijd een verkeerd club-ID,
            # niet een club die dat seizoen niet speelde.
            mislukt.append((club, saison,
                            f"leeg — club-ID {info['id']} ({info['name']}) klopt wrsch. niet"))
        for w in ws:
            index.setdefault((club, w["date"]), []).append(w)
        wacht()

    # Stap 4: koppelen op datum.
    print(f"\n{'=' * 78}\n  KOPPELRESULTAAT\n{'=' * 78}")
    mapping, ongekoppeld, twijfel = {}, [], []
    for m in te_koppelen:
        club = bron_club(m)
        kandidaten = index.get((club, m["date"]), [])
        if len(kandidaten) == 1:
            w = kandidaten[0]
            namen = [c["name"] for c in w["clubs"]]
            # Transfermarkt linkt alleen de tegenstander en zegt via T/U aan
            # welke kant onze club stond. Daaruit volgt wie de tegenstander
            # in onze eigen data hoort te zijn.
            if w["kant"] == "thuis":
                verwacht = m["away_team"]["name"]
            elif w["kant"] == "uit":
                verwacht = m["home_team"]["name"]
            else:
                verwacht = None
            if verwacht:
                klopt = any(namen_matchen(n, verwacht) for n in namen)
            else:
                klopt = any(namen_matchen(n, m["home_team"]["name"])
                            or namen_matchen(n, m["away_team"]["name"]) for n in namen)
            if klopt:
                mapping[str(m["id"])] = {
                    "tm_match_id": w["match_id"], "date": m["date"],
                    "sofascore_label": f"{m['home_team']['name']} - {m['away_team']['name']}",
                    "tm_clubs": namen,
                    "tm_kant": w["kant"],
                    "naam_bevestigd": True,
                }
            else:
                # Niet wegschrijven. Een datumtreffer met een afwijkende naam is
                # precies hoe Lens U19 - PSV U19 aan de seniorenwedstrijd RC Lens
                # - PSV werd gekoppeld: zelfde dag, ander toernooi.
                twijfel.append((m, w))
        elif len(kandidaten) > 1:
            # Zelfde club, zelfde dag: kies op tegenstandersnaam.
            beste = next((w for w in kandidaten
                          if any(namen_matchen(c["name"], m["away_team"]["name"])
                                 or namen_matchen(c["name"], m["home_team"]["name"])
                                 for c in w["clubs"])), None)
            if beste:
                mapping[str(m["id"])] = {
                    "tm_match_id": beste["match_id"], "date": m["date"],
                    "sofascore_label": f"{m['home_team']['name']} - {m['away_team']['name']}",
                    "tm_clubs": [c["name"] for c in beste["clubs"]],
                    "naam_bevestigd": True,
                }
            else:
                ongekoppeld.append(m)
        else:
            ongekoppeld.append(m)

    n = len(matches)
    print(f"  bruikbaar gekoppeld : {len(mapping)} / {n} ({100 * len(mapping) // n}%)")
    print(f"  afgekeurd (naam)    : {len(twijfel)} — datum klopt, club niet")
    print(f"  niet gekoppeld      : {len(ongekoppeld)}")

    if twijfel:
        print(f"\n  ▼ AFGEKEURD en niet weggeschreven — datum matcht, clubnaam niet.")
        print(f"     Meestal een jeugd- of vrouwenwedstrijd op dezelfde dag als")
        print(f"     de seniorenwedstrijd. Los de club op met --set-club.")
        for m, w in twijfel[:10]:
            print(f"    {m['date']}  jij: {m['home_team']['name']} - {m['away_team']['name']}")
            print(f"                TM : {' / '.join(c['name'] for c in w['clubs'])}"
                  f"  (id {w['match_id']})")

    if ongekoppeld:
        groepen = {}
        for m in ongekoppeld:
            club, toernooi = bron_club(m), (m.get("tournament") or "")
            if not clubs.get(club):
                reden = f"club onopgelost: {club}"
            elif "friendly" in toernooi.lower() or "vriend" in toernooi.lower():
                reden = "vriendschappelijk — staat mogelijk niet in het speelschema"
            else:
                reden = "datum niet in het speelschema"
            groepen.setdefault(reden, []).append(m)
        print(f"\n  ▼ Niet gekoppeld, gegroepeerd op oorzaak:")
        for reden, groep in sorted(groepen.items(), key=lambda x: -len(x[1])):
            print(f"\n    [{len(groep)}x] {reden}")
            for m in groep[:6]:
                print(f"       {m['date']}  {m['home_team']['name']} - {m['away_team']['name']}")
            if len(groep) > 6:
                print(f"       ... en nog {len(groep) - 6}")

    if mislukt:
        print(f"\n  ▼ Speelschema's die niet opgehaald konden worden:")
        for club, saison, reden in mislukt[:15]:
            print(f"    {club} {saison} — {reden}")
        print(f"\n     Los op met: python3 transfermarkt_map.py --set-club 'naam' ID")
        print(f"     Zoek het juiste ID met: --search 'naam'")
        print(f"     (zonder punthaken — die leest de shell als omleiding)")

    MATCH_MAP.parent.mkdir(exist_ok=True)
    MATCH_MAP.write_text(json.dumps(mapping, ensure_ascii=False, indent=2), "utf-8")
    print(f"\n  ✓ {MATCH_MAP} geschreven ({len(mapping)} koppelingen)")

    # Alles wat níét meegaat, met reden, zodat er niets stilzwijgend verdwijnt.
    uitgesteld = []
    for m, reden in overgeslagen:
        uitgesteld.append({"id": m["id"], "date": m["date"], "reden": reden,
                           "label": f"{m['home_team']['name']} - {m['away_team']['name']}",
                           "tournament": m.get("tournament", "")})
    for m in ongekoppeld:
        club = bron_club(m)
        if not clubs.get(club):
            reden = f"club onopgelost: {club}"
        elif "friendly" in (m.get("tournament") or "").lower():
            reden = "oefenduel — niet in het speelschema"
        else:
            reden = "datum niet in het speelschema"
        uitgesteld.append({"id": m["id"], "date": m["date"], "reden": reden,
                           "label": f"{m['home_team']['name']} - {m['away_team']['name']}",
                           "tournament": m.get("tournament", "")})
    for m, w in twijfel:
        uitgesteld.append({"id": m["id"], "date": m["date"],
                           "reden": "afgekeurd: clubnaam wijkt af van de datumtreffer",
                           "label": f"{m['home_team']['name']} - {m['away_team']['name']}",
                           "tournament": m.get("tournament", ""),
                           "tm_kandidaat": w["match_id"]})
    uitgesteld.sort(key=lambda x: x["date"])
    UITGESTELD.write_text(json.dumps(uitgesteld, ensure_ascii=False, indent=2), "utf-8")
    print(f"  ✓ {UITGESTELD} geschreven ({len(uitgesteld)} niet meegenomen)")
    print(f"\n  {len(mapping)} van {len(matches)} wedstrijden gaan mee "
          f"({100 * len(mapping) // len(matches)}%)")


# ─── Zelftest ────────────────────────────────────────────────────────────────

def _w(mid, thuis="NEC Nijmegen", uit="PSV Eindhoven", datum="2011-03-13"):
    return {"id": mid, "date": datum,
            "home_team": {"name": thuis}, "away_team": {"name": uit}}


def zelftest() -> int:
    """Rekent na of de export-aanvulling precies de wezen oplevert."""
    gevallen = [
        ("lege export levert niets",
         [_w(1), _w(2)], [], []),
        ("export gelijk aan de selectie levert niets",
         [_w(1), _w(2)], [_w(1), _w(2)], []),
        ("een wees in de export telt mee",
         [_w(1)], [_w(1), _w(9)], [9]),
        ("dezelfde wees twee keer telt één keer",
         [_w(1)], [_w(9), _w(9)], [9]),
        ("een record zonder id blijft buiten",
         [_w(1)], [_w(None), _w(9)], [9]),
        ("lege selectie neemt de hele export over",
         [], [_w(4), _w(5)], [4, 5]),
        ("een selectie-record zonder id maakt niets bekend",
         [_w(None)], [_w(7)], [7]),
    ]
    fout = 0
    for naam, selectie, export, verwacht in gevallen:
        uit = [m["id"] for m in extra_uit_export(selectie, export)]
        goed = uit == verwacht
        print(f"  {'ok  ' if goed else 'FOUT'} {naam}")
        if not goed:
            print(f"       verwacht {verwacht}, kreeg {uit}")
            fout += 1
    print("\n  alles goed" if not fout else f"\n  {fout} fout")
    return 1 if fout else 0


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description="Koppel wedstrijden aan Transfermarkt-ID's")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--search", help="zoek de Transfermarkt-ID van een clubnaam")
    g.add_argument("--fixtures", type=int, help="toon het speelschema van deze club-ID")
    g.add_argument("--clubs", action="store_true", help="los alleen de club-ID's op")
    g.add_argument("--map", action="store_true", help="volledige koppeling")
    g.add_argument("--probe-fixtures", type=int, metavar="CLUB_ID",
                   help="test welke URL het speelschema levert")
    g.add_argument("--set-club", nargs=2, metavar=("NAAM", "ID"),
                   help="leg een clubkoppeling handmatig vast")
    g.add_argument("--zelftest", action="store_true",
                   help="reken de export-aanvulling na, zonder netwerk")
    p.add_argument("--season", type=int, help="seizoen (startjaar)")
    p.add_argument("--dump", help="map om opgehaalde HTML in te bewaren")
    args = p.parse_args()

    if args.zelftest:
        raise SystemExit(zelftest())

    if args.set_club:
        zet_club(args.set_club[0], int(args.set_club[1]))
    elif args.search:
        zoek_club(args.search, toon=True)
    elif args.probe_fixtures:
        if args.season is None:
            sys.exit("  --probe-fixtures vereist ook --season <startjaar>")
        probe_speelschema(args.probe_fixtures, args.season,
                          Path(args.dump) if args.dump else None)
    elif args.fixtures:
        if args.season is None:
            sys.exit("  --fixtures vereist ook --season <startjaar>")
        speelschema(args.fixtures, args.season, toon=True)
    elif args.clubs:
        matches = te_koppelen_wedstrijden()
        namen = sorted({m.get("source_team") or m["home_team"]["name"] for m in matches})
        print(f"  {len(namen)} unieke clubs\n")
        los_clubs_op(namen)
    else:
        koppel_alles()


if __name__ == "__main__":
    main()
