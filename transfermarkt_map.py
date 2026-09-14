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

from transfermarkt_poc import BASE, HEADERS, _IMPERSONATE, _http, _knip, soep

SELECTED = Path("data/selected_matches.json")
CLUB_MAP = Path("data/tm_club_map.json")
MATCH_MAP = Path("data/tm_match_map.json")

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


def speelschema(club_id: int, saison: int, toon: bool = False) -> list[dict]:
    """
    Haalt het speelschema van een club voor één seizoen op.

    Zoekt links naar /spielbericht/ en leest datum en tegenstander uit de
    omliggende rij. Legt bewust geen class-namen vast.
    """
    url = f"{BASE}/club/spielplan/verein/{club_id}/saison_id/{saison}"
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

        # Datum: dd-mm-jjjj of dd-mm-jj, beide komen voor op TM.
        m = re.search(r"(\d{1,2})[-./](\d{1,2})[-./](\d{2,4})", rijtekst)
        if not m:
            continue
        jaar = int(m.group(3))
        jaar += 2000 if jaar < 100 else 0
        datum = f"{jaar:04d}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"

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
            "rij": _knip(rijtekst, 140),
        })

    if toon:
        print(f"\n  Speelschema club {club_id}, seizoen {saison}: "
              f"{len(wedstrijden)} wedstrijden")
        for w in wedstrijden[:12]:
            namen = " / ".join(c["name"] for c in w["clubs"]) or "(geen clublinks)"
            print(f"   {w['date']}  id={w['match_id']:<9} {namen}")
        if not wedstrijden:
            print("    !! niets gevonden — parser of URL klopt niet")
            print(f"    URL: {url}")
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
            if re.search(r"(\d{1,2})[-./](\d{1,2})[-./](\d{2,4})", rijtekst):
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

def los_clubs_op(namen: list[str]) -> dict:
    """Zoekt per clubnaam de Transfermarkt-ID. Hergebruikt een eerdere run."""
    bekend = json.loads(CLUB_MAP.read_text("utf-8")) if CLUB_MAP.exists() else {}
    nieuw = 0
    for naam in namen:
        if naam in bekend:
            continue
        print(f"  zoeken: {naam}")
        kandidaten = zoek_club(naam)
        beste = next((k for k in kandidaten if lijkt_op(k["name"], naam)), None) \
            or (kandidaten[0] if kandidaten else None)
        if beste:
            bekend[naam] = beste
            print(f"    → {beste['id']} {beste['name']}")
        else:
            bekend[naam] = None
            print("    → niet gevonden")
        nieuw += 1
        wacht()
    if nieuw:
        CLUB_MAP.parent.mkdir(exist_ok=True)
        CLUB_MAP.write_text(json.dumps(bekend, ensure_ascii=False, indent=2), "utf-8")
        print(f"\n  ✓ {CLUB_MAP} bijgewerkt ({nieuw} nieuw)")
    return bekend


def koppel_alles():
    """Koppelt elke wedstrijd in selected_matches.json aan een TM-match-ID."""
    matches = json.loads(SELECTED.read_text("utf-8"))
    print(f"  {len(matches)} wedstrijden in {SELECTED}")

    # Stap 1: welke (club, seizoen)-paren moeten opgehaald worden?
    paren = {}
    for m in matches:
        club = m.get("source_team") or m["home_team"]["name"]
        paren.setdefault((club, saison_van(m["date"])), []).append(m)
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
            mislukt.append((club, saison, "leeg speelschema"))
        for w in ws:
            index.setdefault((club, w["date"]), []).append(w)
        wacht()

    # Stap 4: koppelen op datum.
    print(f"\n{'=' * 78}\n  KOPPELRESULTAAT\n{'=' * 78}")
    mapping, ongekoppeld, twijfel = {}, [], []
    for m in matches:
        club = m.get("source_team") or m["home_team"]["name"]
        kandidaten = index.get((club, m["date"]), [])
        if len(kandidaten) == 1:
            w = kandidaten[0]
            namen = [c["name"] for c in w["clubs"]]
            klopt = any(lijkt_op(n, m["home_team"]["name"]) for n in namen) or \
                    any(lijkt_op(n, m["away_team"]["name"]) for n in namen)
            mapping[str(m["id"])] = {
                "tm_match_id": w["match_id"], "date": m["date"],
                "sofascore_label": f"{m['home_team']['name']} - {m['away_team']['name']}",
                "tm_clubs": namen,
                "naam_bevestigd": klopt,
            }
            if not klopt:
                twijfel.append((m, w))
        elif len(kandidaten) > 1:
            # Zelfde club, zelfde dag: kies op tegenstandersnaam.
            beste = next((w for w in kandidaten
                          if any(lijkt_op(c["name"], m["away_team"]["name"])
                                 or lijkt_op(c["name"], m["home_team"]["name"])
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
    bevestigd = sum(1 for v in mapping.values() if v["naam_bevestigd"])
    print(f"  gekoppeld          : {len(mapping)} / {n} ({100 * len(mapping) // n}%)")
    print(f"  waarvan bevestigd  : {bevestigd} (clubnaam komt overeen)")
    print(f"  naam wijkt af      : {len(twijfel)} — controleer deze")
    print(f"  niet gekoppeld     : {len(ongekoppeld)}")

    if twijfel:
        print(f"\n  ▼ Datum matcht, maar clubnaam niet — handmatig nakijken:")
        for m, w in twijfel[:10]:
            print(f"    {m['date']}  jij: {m['home_team']['name']} - {m['away_team']['name']}")
            print(f"                TM : {' / '.join(c['name'] for c in w['clubs'])}"
                  f"  (id {w['match_id']})")

    if ongekoppeld:
        print(f"\n  ▼ Niet gekoppeld:")
        for m in ongekoppeld[:15]:
            club = m.get("source_team") or m["home_team"]["name"]
            print(f"    {m['date']}  {m['home_team']['name']} - {m['away_team']['name']}"
                  f"   (via {club})")

    if mislukt:
        print(f"\n  ▼ Speelschema's die niet opgehaald konden worden:")
        for club, saison, reden in mislukt[:15]:
            print(f"    {club} {saison} — {reden}")

    MATCH_MAP.parent.mkdir(exist_ok=True)
    MATCH_MAP.write_text(json.dumps(mapping, ensure_ascii=False, indent=2), "utf-8")
    print(f"\n  ✓ {MATCH_MAP} geschreven ({len(mapping)} koppelingen)")


def main():
    p = argparse.ArgumentParser(description="Koppel wedstrijden aan Transfermarkt-ID's")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--search", help="zoek de Transfermarkt-ID van een clubnaam")
    g.add_argument("--fixtures", type=int, help="toon het speelschema van deze club-ID")
    g.add_argument("--clubs", action="store_true", help="los alleen de club-ID's op")
    g.add_argument("--map", action="store_true", help="volledige koppeling")
    g.add_argument("--probe-fixtures", type=int, metavar="CLUB_ID",
                   help="test welke URL het speelschema levert")
    p.add_argument("--season", type=int, help="seizoen (startjaar)")
    p.add_argument("--dump", help="map om opgehaalde HTML in te bewaren")
    args = p.parse_args()

    if args.search:
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
        matches = json.loads(SELECTED.read_text("utf-8"))
        namen = sorted({m.get("source_team") or m["home_team"]["name"] for m in matches})
        print(f"  {len(namen)} unieke clubs\n")
        los_clubs_op(namen)
    else:
        koppel_alles()


if __name__ == "__main__":
    main()
