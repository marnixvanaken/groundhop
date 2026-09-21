#!/usr/bin/env python3
"""
Haalt ontbrekende afbeeldingen op en zet ze in img/.

Van de 3016 spelers stonden er 300 lokaal en van de toernooien geen enkele.
Zonder deze bestanden valt de app terug op initialen, en op een gehoste
omgeving zonder netwerk naar Sofascore blijft dat zo.

Draai dit op je eigen machine; hier is Sofascore niet bereikbaar.

  python3 tools/fetch_images.py                 # alles wat ontbreekt
  python3 tools/fetch_images.py tournament      # alleen competitielogo's
  python3 tools/fetch_images.py player --limit 200
"""

import argparse
import json
import sys
import time
from pathlib import Path

try:
    import requests
except ImportError:
    sys.exit("requests ontbreekt — pip install -r requirements.txt")

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "dashboard_data.json"

# Toernooien zitten bij Sofascore onder een ander pad dan spelers en clubs.
PAD = {"player": "player", "team": "team", "tournament": "unique-tournament"}

KOPPEN = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Referer": "https://www.sofascore.com/",
    "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
}


def ids(data, soort):
    if soort == "player":
        return [p["id"] for p in data["players"]]
    if soort == "team":
        return [t["id"] for t in data["teams_visited"]]
    return [t["id"] for t in data["tournaments"]]


def haal(soort, ident, sessie):
    url = f"https://api.sofascore.app/api/v1/{PAD[soort]}/{ident}/image"
    r = sessie.get(url, headers=KOPPEN, timeout=20)
    if r.status_code != 200 or len(r.content) < 200:
        return None
    return r.content


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("soort", nargs="?", choices=list(PAD) + ["alles"], default="alles")
    ap.add_argument("--limit", type=int, help="stop na dit aantal nieuwe bestanden")
    ap.add_argument("--pauze", type=float, default=0.4, help="seconden tussen verzoeken")
    args = ap.parse_args()

    data = json.loads(DATA.read_text(encoding="utf-8"))
    soorten = list(PAD) if args.soort == "alles" else [args.soort]
    sessie = requests.Session()

    for soort in soorten:
        map_ = ROOT / "img" / soort
        map_.mkdir(parents=True, exist_ok=True)
        ontbreekt = [i for i in ids(data, soort) if not (map_ / str(i)).exists()]
        print(f"{soort}: {len(ontbreekt)} ontbreken")

        gelukt = mislukt = 0
        for ident in ontbreekt:
            if args.limit and gelukt >= args.limit:
                print(f"  limiet van {args.limit} bereikt")
                break
            try:
                inhoud = haal(soort, ident, sessie)
            except Exception as e:
                print(f"  {ident}: {e}")
                mislukt += 1
                continue
            if inhoud is None:
                mislukt += 1
            else:
                (map_ / str(ident)).write_bytes(inhoud)
                gelukt += 1
                if gelukt % 25 == 0:
                    print(f"  {gelukt} opgehaald…")
            time.sleep(args.pauze)

        print(f"  klaar: {gelukt} opgehaald, {mislukt} niet beschikbaar")


if __name__ == "__main__":
    main()
