#!/usr/bin/env python3
"""
Bouwt demo/add-data.js voor het scherm 'wedstrijd toevoegen'.

Het echte paneel praat met Transfermarkt. Dat kan hier niet, dus de demo draait
op wat er in de export staat: je eigen clubs als zoekresultaat en als suggestie,
en per club het speelschema van de seizoenen waarin je die club zag.

Die wedstrijden zijn per definitie duels die je hebt bijgewoond, dus ze staan
allemaal al in je verzameling. Om ook de andere toestand te kunnen tonen heeft
het scherm een schakelaar; er wordt niets verzonnen.

Gebruik:  python3 demo/build_add_data.py
"""

import json
import shutil
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent.parent
DEMO = Path(__file__).resolve().parent
CRESTS = DEMO / "crests"
TARGET = DEMO / "add-data.js"

LOGOS = {}


def crest(team_id):
    """Zelfde weg als de andere schermen: lokaal bestand, anders de proxy."""
    bron = ROOT / "img" / "team" / str(team_id)
    if bron.exists():
        kop = bron.read_bytes()[:12]
        ext = (".png" if kop[:8] == b"\x89PNG\r\n\x1a\n"
               else ".webp" if kop[:4] == b"RIFF" and kop[8:12] == b"WEBP"
               else ".jpg" if kop[:3] == b"\xff\xd8\xff" else None)
        if ext:
            CRESTS.mkdir(exist_ok=True)
            shutil.copyfile(bron, CRESTS / f"{team_id}{ext}")
            return f"crests/{team_id}{ext}"
    url = LOGOS.get(team_id)
    return f"/img/ext?u={quote(url, safe='')}" if url else None


def seizoen(datum):
    """Een seizoen begint in juli; 2023 betekent 2023/24."""
    jaar, maand = int(datum[:4]), int(datum[5:7])
    return jaar if maand >= 7 else jaar - 1


def main():
    d = json.loads((ROOT / "data" / "dashboard_data.json").read_text(encoding="utf-8"))
    LOGOS.update({c["id"]: c["logo_url"] for c in d.get("teams_visited", []) if c.get("logo_url")})

    duels = sorted(d["matches"], key=lambda m: m["date"], reverse=True)

    fixtures = [
        {
            "id": m["id"],
            "date": m["date"],
            "season": seizoen(m["date"]),
            "home": m["home_team"]["name"],
            "away": m["away_team"]["name"],
            "home_id": m["home_team"]["id"],
            "away_id": m["away_team"]["id"],
            "score": f"{m['home_score']}–{m['away_score']}",
            "tournament": m["tournament"],
            "home_crest": crest(m["home_team"]["id"]),
            "away_crest": crest(m["away_team"]["id"]),
        }
        for m in duels
    ]

    # Elke club die je zag is een zoekresultaat. Dat is geen wereldwijde index
    # zoals het echte paneel heeft, maar het gedrag dat we willen tonen —
    # zoeken terwijl je typt — is hetzelfde.
    clubs = []
    for c in sorted(d["teams_visited"], key=lambda c: -c["matches_count"]):
        eigen = [f for f in fixtures if c["id"] in (f["home_id"], f["away_id"])]
        clubs.append({
            "id": c["id"],
            "name": c["name"],
            "count": c["matches_count"],
            "crest": crest(c["id"]),
            "seasons": sorted({f["season"] for f in eigen}, reverse=True),
        })

    payload = {
        "source": d.get("source", "sofascore"),
        "clubs": clubs,
        "fixtures": fixtures,
        "totals": {"clubs": len(clubs), "matches": d["total_matches"]},
    }

    TARGET.write_text("window.ADD = " + json.dumps(payload, ensure_ascii=False, indent=1) + ";\n",
                      encoding="utf-8")
    top = clubs[0]
    print(f"{TARGET.relative_to(ROOT)} geschreven — {TARGET.stat().st_size/1024:.0f} KB")
    print(f"  clubs: {len(clubs)} — suggesties {', '.join(c['name'] for c in clubs[:4])}…")
    print(f"  duels: {len(fixtures)} — {top['name']} in {len(top['seasons'])} seizoenen")
    zonder = [c["name"] for c in clubs if not c["crest"]]
    if zonder:
        print(f"  zonder logo: {len(zonder)} — {', '.join(zonder[:5])}…")


if __name__ == "__main__":
    main()
