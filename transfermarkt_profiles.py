#!/usr/bin/env python3
"""
Transfermarkt profielen — vul de spelerslaag aan met persoonsgegevens
=====================================================================

`transfermarkt_players.py` leidt af wie speelde en hoe lang, uit data die al
binnen is. Geboortedatum, nationaliteit, positie, lengte en marktwaarde staan
alleen op het spelersprofiel, en dat is één verzoek per speler.

Kosten: het profiel alleen is 1 verzoek. Transferhistorie en het verloop van de
marktwaarde komen uit twee losse ceapi-endpoints; die haalt hij alleen op voor
de spelers die je met --volledig aanwijst, want anders verdrievoudigt de run.

De spelers worden aflopend op speelminuten afgewerkt. Breek je af, dan heb je
de spelers die ertoe doen al binnen, en de volgende run pakt de rest op.

Gebruik
-------
    python3 transfermarkt_profiles.py --limit 25     # eerst een handvol
    python3 transfermarkt_profiles.py                # alles, uren werk
    python3 transfermarkt_profiles.py --volledig 150 # top 150 ook transfers
    python3 transfermarkt_profiles.py --rapport      # alleen de stand
"""

from __future__ import annotations

import argparse
import json
import random
import time
from datetime import date
from pathlib import Path

from transfermarkt_poc import (BASE, CEAPI_MARKTWAARDE, CEAPI_TRANSFERS,
                              fetch, haal_json, parse_player)

SPELERS = Path("data/tm_players.json")
CACHE = Path("data/tm_player_cache")
UITVOER = Path("data/tm_players_full.json")
DASHBOARD = Path("data/dashboard_data.json")

MIN_DELAY, MAX_DELAY = 2.0, 4.0


def wacht():
    time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))


def haal_profiel(pid: int, volledig: bool, force: bool = False) -> dict | None:
    """Haalt en parst één spelersprofiel. Gebruikt de cache tenzij --force.

    Een profiel dat eerder zonder transfers is opgehaald wordt opnieuw gehaald
    zodra het wél volledig moet; andersom niet.
    """
    CACHE.mkdir(parents=True, exist_ok=True)
    pad = CACHE / f"{pid}.json"
    if pad.exists() and not force:
        bestaand = json.loads(pad.read_text("utf-8"))
        if bestaand.get("_volledig") or not volledig:
            return bestaand

    try:
        html = fetch(f"{BASE}/speler/profil/spieler/{pid}")
    except SystemExit as e:
        print(f"    ✗ profiel mislukt: {e}")
        return None

    transfers_data = mv_data = None
    if volledig:
        for sleutel, sjabloon in (("t", CEAPI_TRANSFERS), ("m", CEAPI_MARKTWAARDE)):
            wacht()
            try:
                data = haal_json(BASE + sjabloon.format(id=pid))
            except SystemExit:
                data = None            # ontbreekt: de rest blijft bruikbaar
            if sleutel == "t":
                transfers_data = data
            else:
                mv_data = data

    try:
        record, diag = parse_player(html, pid, transfers_data, mv_data)
    except Exception as e:
        print(f"    ✗ parsen mislukt: {type(e).__name__}: {e}")
        return None

    record["_volledig"] = volledig
    record["_gemist"] = [r[0] for r in diag.rows if r[1] == "GEMIST"]
    pad.write_text(json.dumps(record, ensure_ascii=False, indent=2), "utf-8")
    return record


# ─── Controle ────────────────────────────────────────────────────────────────

def controleer(profielen: list[dict]) -> None:
    """Rekent de opgehaalde profielen na op wat onafhankelijk te toetsen is.

    Twee soorten controle. Ten eerste plausibiliteit: een geboortedatum in 1890
    of een lengte van 3 meter is geen gevuld veld maar een fout. Ten tweede een
    vergelijking met de Sofascore-data die er al ligt — staan twee bronnen op
    dezelfde naam met een andere geboortedatum, dan is er één mis, of het is een
    andere speler en zit de ID-koppeling fout.
    """
    dit_jaar = date.today().year
    ongerijmd = []
    for p in profielen:
        gb = p.get("date_of_birth") or ""
        if gb[:4].isdigit():
            jaar = int(gb[:4])
            if not (1930 <= jaar <= dit_jaar - 14):
                ongerijmd.append(f"{p.get('name')}: geboortejaar {jaar}")
        h = p.get("height_cm")
        if h and not (150 <= h <= 215):
            ongerijmd.append(f"{p.get('name')}: lengte {h} cm")
        mw = p.get("market_value")
        if mw is not None and not (0 <= mw <= 400_000_000):
            ongerijmd.append(f"{p.get('name')}: marktwaarde {mw}")

    print(f"\n  ── plausibiliteit ──")
    if ongerijmd:
        print(f"  ✗ {len(ongerijmd)} ongerijmde waarden:")
        for r in ongerijmd[:15]:
            print(f"    {r}")
    else:
        print(f"  ✓ geen ongerijmde geboortejaren, lengtes of marktwaarden")

    if not DASHBOARD.exists():
        return
    oud = json.loads(DASHBOARD.read_text("utf-8")).get("players", [])
    op_naam = {}
    for p in oud:
        if p.get("name") and p.get("date_of_birth"):
            op_naam.setdefault(p["name"], p["date_of_birth"])

    vergeleken = gelijk = 0
    afwijkend = []
    for p in profielen:
        sofa = op_naam.get(p.get("name"))
        if not sofa or not p.get("date_of_birth"):
            continue
        vergeleken += 1
        if sofa == p["date_of_birth"]:
            gelijk += 1
        else:
            afwijkend.append(f"{p['name']}: TM {p['date_of_birth']} / Sofascore {sofa}")

    print(f"\n  ── geboortedatum tegen de Sofascore-data ──")
    print(f"  op naam te vergelijken   {vergeleken:>6}")
    print(f"  gelijk                   {gelijk:>6}"
          f"{'   ✓' if vergeleken and gelijk == vergeleken else ''}")
    if afwijkend:
        print(f"  afwijkend                {len(afwijkend):>6}   ✗")
        print(f"  ! Een afwijking betekent een verkeerd profiel of een naamgenoot.")
        for r in afwijkend[:15]:
            print(f"    {r}")
        if len(afwijkend) > 15:
            print(f"    ... en nog {len(afwijkend) - 15}")


def main():
    p = argparse.ArgumentParser(description="Haal spelersprofielen op")
    p.add_argument("--limit", type=int, help="stop na zoveel spelers")
    p.add_argument("--volledig", type=int, default=0, metavar="N",
                   help="haal voor de N spelers met de meeste minuten ook "
                        "transfers en marktwaardeverloop op (3 verzoeken elk)")
    p.add_argument("--force", action="store_true", help="negeer de cache")
    p.add_argument("--rapport", action="store_true",
                   help="toon de stand en de controle, haal niets op")
    args = p.parse_args()

    if not SPELERS.exists():
        raise SystemExit(f"  {SPELERS} ontbreekt — draai eerst transfermarkt_players.py")
    spelers = json.loads(SPELERS.read_text("utf-8"))
    print(f"  {len(spelers)} spelers in {SPELERS}")

    CACHE.mkdir(parents=True, exist_ok=True)
    volledig_ids = {s["id"] for s in spelers[:args.volledig]}

    te_doen = []
    for s in spelers:
        pad = CACHE / f"{s['id']}.json"
        wil_volledig = s["id"] in volledig_ids
        if args.force or not pad.exists():
            te_doen.append((s, wil_volledig))
        elif wil_volledig:
            bestaand = json.loads(pad.read_text("utf-8"))
            if not bestaand.get("_volledig"):
                te_doen.append((s, True))

    gecachet = len(list(CACHE.glob("*.json")))
    print(f"  {gecachet} al gecachet, {len(te_doen)} te doen")
    if args.volledig:
        print(f"  waarvan {len(volledig_ids)} ook transfers + marktwaardeverloop")

    if not args.rapport and te_doen:
        if args.limit:
            te_doen = te_doen[:args.limit]
            print(f"  beperkt tot {len(te_doen)}")
        verzoeken = sum(3 if v else 1 for _, v in te_doen)
        print(f"  ~{verzoeken} verzoeken, ruw geschat "
              f"{verzoeken * 3 // 60} minuten\n")
        for i, (s, volledig) in enumerate(te_doen, 1):
            print(f"  [{i}/{len(te_doen)}] {s['name']} "
                  f"({s['minutes_played']} min){'  +transfers' if volledig else ''}")
            haal_profiel(s["id"], volledig, args.force)
            wacht()

    # Voeg de profielgegevens samen met de afgeleide spelerslaag.
    samen, zonder = [], 0
    for s in spelers:
        pad = CACHE / f"{s['id']}.json"
        if not pad.exists():
            zonder += 1
            samen.append(s)
            continue
        profiel = json.loads(pad.read_text("utf-8"))
        samengevoegd = dict(s)
        for k, v in profiel.items():
            if k.startswith("_") or k in ("id", "id_source"):
                continue
            # De afgeleide naam uit de opstelling is soms afgekort ("J. Veerman");
            # die van het profiel is volledig en wint.
            if v not in (None, "", [], {}):
                samengevoegd[k] = v
        samen.append(samengevoegd)

    met_profiel = [s for s in samen if s.get("date_of_birth")]
    print(f"\n  {len(met_profiel)} van {len(samen)} spelers met profiel"
          f"{f', {zonder} nog zonder' if zonder else ''}")

    controleer(met_profiel)

    schoon = [{k: v for k, v in s.items() if not k.startswith("_")} for s in samen]
    UITVOER.write_text(json.dumps(schoon, ensure_ascii=False, indent=2), "utf-8")
    print(f"\n  ✓ {UITVOER} geschreven ({len(schoon)} spelers)")


if __name__ == "__main__":
    main()
