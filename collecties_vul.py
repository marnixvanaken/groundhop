#!/usr/bin/env python3
"""
Zoekt de Transfermarkt-nummers op van clubs in de albums die je nog nooit zag.

Een club die je zag, staat met nummer en logo in je data. Een club die je nog
nooit zag niet, en zonder nummer heeft hij in het album geen logo. Dit script
zoekt die nummers één keer op bij Transfermarkt en bewaart ze in
data/collecties_ids.json. GroundHop.command draait het bij het starten; het
doet alleen iets als er een club zonder nummer is.

Twijfel wordt niet opgeslagen: bij twee even goede kandidaten blijft de club
zonder nummer en dus zonder logo. Liever geen logo dan dat van een andere club.

Gebruik:  python3 collecties_vul.py
"""

from __future__ import annotations

import json
from pathlib import Path

COLLECTIES = Path("data/collecties.json")
IDS = Path("data/collecties_ids.json")


def ontbrekend(ref: dict, bekend: dict) -> list[str]:
    return [c["naam"] for comp in ref["competities"] for c in comp["clubs"]
            if not c.get("tm") and c["naam"] not in bekend]


def main():
    ref = json.loads(COLLECTIES.read_text("utf-8"))
    bekend = json.loads(IDS.read_text("utf-8")) if IDS.exists() else {}
    te_doen = ontbrekend(ref, bekend)
    if not te_doen:
        return
    import transfermarkt_map as tmap
    print(f"  clubnummers opzoeken voor de collecties: {len(te_doen)}")
    for naam in te_doen:
        kandidaten, fout = tmap.zoek_club_met_status(naam)
        if fout:
            print(f"    ! Transfermarkt onbereikbaar — later opnieuw")
            break
        club, twijfel = tmap.kies_club(naam, kandidaten)
        if club:
            bekend[naam] = club["id"]
            print(f"    ✓ {naam}: {club['id']} ({club['name']})")
        else:
            print(f"    ? {naam}: {'twijfel tussen ' + ', '.join(k['name'] for k in twijfel[:3]) if twijfel else 'niet gevonden'}")
        tmap.wacht()
    IDS.write_text(json.dumps(bekend, ensure_ascii=False, indent=1, sort_keys=True) + "\n", "utf-8")


if __name__ == "__main__":
    main()
