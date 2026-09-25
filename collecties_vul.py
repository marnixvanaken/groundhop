#!/usr/bin/env python3
"""
Vult de albums aan met gegevens van Transfermarkt. Draait op je laptop, bij het
starten van GroundHop; doet alleen iets als er iets ontbreekt.

1. De clubs en stadions van het lopende seizoen, per competitie in
   data/collecties.json. Eén pagina per competitie voor de clubs, één voor de
   stadions; ontbreekt daar een stadion, dan de pagina van die club zelf.
   Resultaat: data/collecties_seizoen.json. Het seizoen kantelt op 1 juli; dan
   haalt hij de nieuwe lijsten vanzelf.

2. Transfermarkt-nummers van clubs in de terugvallijst zonder nummer, zodat
   ook die een (grijs) logo krijgen: data/collecties_ids.json.

Twijfel wordt niet opgeslagen. Klopt het aantal clubs van een competitie niet,
of vindt hij er geen, dan blijft de vorige lijst staan en zegt hij dat. Liever
een album van vorig seizoen dan een half album.

De clubs worden herkend aan hun link (/startseite/verein/<id>/saison_id/<jaar>)
en de stadions aan de hunne (/stadion/verein/<id>), niet aan class-namen: die
verandert Transfermarkt vaker dan zijn adressen.

Gebruik
-------
    python3 collecties_vul.py              # vul aan wat ontbreekt
    python3 collecties_vul.py --opnieuw    # haal de seizoenslijsten opnieuw op
    python3 collecties_vul.py --dump       # bewaar de pagina's in data/tm_debug/
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path

COLLECTIES = Path("data/collecties.json")
SEIZOEN = Path("data/collecties_seizoen.json")
IDS = Path("data/collecties_ids.json")
DEBUG = Path("data/tm_debug")

CLUB_RE = re.compile(r"/startseite/verein/(\d+)/saison_id/(\d{4})")
STADION_RE = re.compile(r"/stadion/verein/(\d+)")
MIN_CLUBS, MAX_CLUBS = 12, 24


def huidig_seizoen(vandaag: date | None = None) -> int:
    d = vandaag or date.today()
    return d.year if d.month >= 7 else d.year - 1


def lees_clubs(html: str, jaar: int, soep) -> list[dict]:
    """De clubs uit de competitiepagina: de tabel met de meeste clublinks van
    dit seizoen, in de volgorde van de pagina."""
    beste = []
    for tabel in soep(html).find_all("table"):
        gezien, clubs = set(), []
        for a in tabel.find_all("a", href=CLUB_RE):
            m = CLUB_RE.search(a["href"])
            cid, saison = int(m.group(1)), int(m.group(2))
            naam = (a.get("title") or a.get_text(strip=True)).strip()
            if saison != jaar or not naam or cid in gezien:
                continue
            gezien.add(cid)
            clubs.append({"naam": naam, "tm": cid})
        if len(clubs) > len(beste):
            beste = clubs
    return beste


def lees_stadions(html: str, soep) -> dict[int, str]:
    """{club-id: stadionnaam} uit elke link naar een stadion met tekst erin."""
    uit = {}
    for a in soep(html).find_all("a", href=STADION_RE):
        naam = a.get_text(" ", strip=True)
        if naam and len(naam) > 2:
            uit.setdefault(int(STADION_RE.search(a["href"]).group(1)), naam)
    return uit


def haal_seizoen(ref: dict, jaar: int, dump: bool) -> dict:
    from transfermarkt_poc import BASE, fetch, soep
    from transfermarkt_map import wacht

    bestaand = json.loads(SEIZOEN.read_text("utf-8")) if SEIZOEN.exists() else {}
    uit = {"seizoen": jaar, "opgehaald": date.today().isoformat(),
           "competities": dict(bestaand.get("competities", {})) if bestaand.get("seizoen") == jaar else {}}
    for comp in ref["competities"]:
        if comp["id"] in uit["competities"] or not comp.get("tm_code"):
            continue
        code = comp["tm_code"]
        print(f"  {comp['naam']} {jaar}/{(jaar + 1) % 100:02d} ophalen")
        try:
            html = fetch(f"{BASE}/x/startseite/wettbewerb/{code}/saison_id/{jaar}",
                         DEBUG if dump else None, f"{code}-{jaar}-clubs")
        except SystemExit as e:
            print(f"    ! {e} — de vorige lijst blijft staan")
            continue
        clubs = lees_clubs(html, jaar, soep)
        if not MIN_CLUBS <= len(clubs) <= MAX_CLUBS:
            print(f"    ! {len(clubs)} clubs gevonden, dat klopt niet — de vorige lijst blijft staan."
                  f" Draai met --dump en stuur data/tm_debug/{code}-{jaar}-clubs.html mee.")
            continue
        wacht()
        stadions = {}
        try:
            stadions = lees_stadions(fetch(f"{BASE}/x/stadien/wettbewerb/{code}/saison_id/{jaar}",
                                           DEBUG if dump else None, f"{code}-{jaar}-stadions"), soep)
        except SystemExit as e:
            print(f"    ! stadionpagina: {e}")
        for c in clubs:
            if c["tm"] not in stadions:
                wacht()
                try:
                    html = fetch(f"{BASE}/x/startseite/verein/{c['tm']}/saison_id/{jaar}")
                    stadions.update({k: v for k, v in lees_stadions(html, soep).items() if k == c["tm"]})
                except SystemExit:
                    pass
            c["stadion"] = stadions.get(c["tm"])
        zonder = [c["naam"] for c in clubs if not c["stadion"]]
        uit["competities"][comp["id"]] = clubs
        print(f"    ✓ {len(clubs)} clubs" + (f"; zonder stadion: {', '.join(zonder)}" if zonder else ""))
        wacht()
    return uit


def haal_ids(ref: dict) -> None:
    import transfermarkt_map as tmap
    bekend = json.loads(IDS.read_text("utf-8")) if IDS.exists() else {}
    te_doen = [c["naam"] for comp in ref["competities"] for c in comp["clubs"]
               if not c.get("tm") and c["naam"] not in bekend]
    if not te_doen:
        return
    print(f"  clubnummers opzoeken voor de collecties: {len(te_doen)}")
    for naam in te_doen:
        kandidaten, fout = tmap.zoek_club_met_status(naam)
        if fout:
            print("    ! Transfermarkt onbereikbaar — later opnieuw")
            break
        club, twijfel = tmap.kies_club(naam, kandidaten)
        if club:
            bekend[naam] = club["id"]
            print(f"    ✓ {naam}: {club['id']} ({club['name']})")
        else:
            print(f"    ? {naam}: " + ("twijfel tussen " + ", ".join(k["name"] for k in twijfel[:3])
                                      if twijfel else "niet gevonden"))
        tmap.wacht()
    IDS.write_text(json.dumps(bekend, ensure_ascii=False, indent=1, sort_keys=True) + "\n", "utf-8")


def main():
    ref = json.loads(COLLECTIES.read_text("utf-8"))
    jaar = huidig_seizoen()
    huidig = json.loads(SEIZOEN.read_text("utf-8")) if SEIZOEN.exists() else {}
    compleet = (huidig.get("seizoen") == jaar
                and all(c["id"] in huidig.get("competities", {}) for c in ref["competities"]))
    if "--opnieuw" in sys.argv or not compleet:
        if "--opnieuw" in sys.argv:
            SEIZOEN.unlink(missing_ok=True)
        nieuw = haal_seizoen(ref, jaar, "--dump" in sys.argv)
        if nieuw["competities"]:
            SEIZOEN.write_text(json.dumps(nieuw, ensure_ascii=False, indent=1) + "\n", "utf-8")
            compleet = all(c["id"] in nieuw["competities"] for c in ref["competities"])
    # Nummers opzoeken is alleen nodig voor de terugvallijst; staat het seizoen
    # compleet, dan heeft elke club zijn nummer al van Transfermarkt.
    if not compleet:
        haal_ids(ref)


if __name__ == "__main__":
    main()
