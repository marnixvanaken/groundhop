#!/usr/bin/env python3
"""
Transfermarkt selectie — welke wedstrijden je hebt gezien, op Transfermarkt-eigen voet
=====================================================================================

Tot nu toe was de Transfermarkt-keten afgeleid van Sofascore: `tm_match_map.json`
koppelt een sofascore_id aan een tm_match_id, en die koppeling is gemaakt door de
Sofascore-lijst tegen de speelschema's van Transfermarkt te leggen. Dat werkte om
de overstap te kúnnen maken, maar het betekent ook dat er zonder Sofascore geen
wedstrijd meer bij kan: een nieuwe wedstrijd heeft geen sofascore_id om vanaf te
vertrekken.

Deze module haalt die afhankelijkheid weg. `data/tm_selectie.json` is een platte
lijst Transfermarkt-wedstrijd-ID's — meer is het niet, en meer hoeft het niet te
zijn. Alles wat het dashboard toont wordt daaruit opgehaald.

De Sofascore-herkomst gaat niet verloren: bij de wedstrijden die uit de migratie
komen blijft het sofascore_id als `sofascore_id` staan. Dat is herkomst, geen
sleutel — het zoektabblad gebruikt het om te zien wat je al hebt, en zodra dat
tabblad ook bij Transfermarkt zoekt is het alleen nog geschiedenis.

Gebruik
-------
    python3 transfermarkt_selectie.py --seed        # vul hem uit de bestaande koppeling
    python3 transfermarkt_selectie.py --lijst       # toon wat erin staat
    python3 transfermarkt_selectie.py --toevoegen 4361105
    python3 transfermarkt_selectie.py --verwijderen 4361105
    python3 transfermarkt_selectie.py --zelftest
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

SELECTIE = Path("data/tm_selectie.json")
MATCH_MAP = Path("data/tm_match_map.json")
CACHE = Path("data/tm_match_cache")


def lees(pad: Path = SELECTIE) -> list[dict]:
    return json.loads(pad.read_text("utf-8")) if pad.exists() else []


def schrijf(selectie: list[dict], pad: Path = SELECTIE):
    pad.parent.mkdir(parents=True, exist_ok=True)
    op_datum = sorted(selectie, key=lambda s: (s.get("date") or "", s["match_id"]))
    pad.write_text(json.dumps(op_datum, ensure_ascii=False, indent=2), "utf-8")


def voeg_toe(selectie: list[dict], match_id: int, label: str = "", datum: str = "",
             bron: str = "handmatig", vandaag: str = "") -> tuple[list[dict], bool]:
    """Voegt een wedstrijd toe. Geeft (nieuwe lijst, of het echt nieuw was) terug.

    Dubbel toevoegen is geen fout maar een non-actie: het dashboard zou de
    wedstrijd anders twee keer tellen, en dat is precies het soort stille fout
    waar niemand ooit achter komt.
    """
    match_id = int(match_id)
    if any(int(s["match_id"]) == match_id for s in selectie):
        return selectie, False
    return selectie + [{
        "match_id": match_id,
        "label": label,
        "date": datum,
        "bron": bron,
        "toegevoegd": vandaag or date.today().isoformat(),
    }], True


def verwijder(selectie: list[dict], match_id: int) -> tuple[list[dict], bool]:
    match_id = int(match_id)
    over = [s for s in selectie if int(s["match_id"]) != match_id]
    return over, len(over) != len(selectie)


def ids(selectie: list[dict]) -> list[int]:
    return [int(s["match_id"]) for s in selectie]


def uit_koppeling(mapping: dict, records: dict[int, dict]) -> list[dict]:
    """Bouwt de eerste selectie uit de bestaande Sofascore→Transfermarkt-koppeling.

    De datum en het label komen bij voorkeur uit het opgehaalde
    Transfermarkt-record; dat is immers wat het dashboard straks toont. Staat dat
    er nog niet, dan valt hij terug op wat de koppeling zelf noteerde, zodat een
    selectie ook te maken is vóór alles is opgehaald.
    """
    uit = []
    for sofa_id, info in mapping.items():
        tm_id = int(info["tm_match_id"])
        r = records.get(tm_id) or {}
        thuis = (r.get("home_team") or {}).get("name")
        uit_ = (r.get("away_team") or {}).get("name")
        label = f"{thuis} - {uit_}" if thuis and uit_ else info.get("sofascore_label", "")
        uit.append({
            "match_id": tm_id,
            "label": label,
            "date": r.get("date") or info.get("date", ""),
            "bron": "sofascore-migratie",
            "sofascore_id": int(sofa_id),
            "toegevoegd": date.today().isoformat(),
        })
    # Dezelfde TM-wedstrijd kan in theorie aan twee Sofascore-ID's hangen; dan
    # wint de eerste en verdwijnt de dubbel, want dubbel tellen is erger.
    gezien, schoon = set(), []
    for s in sorted(uit, key=lambda s: (s.get("date") or "", s["match_id"])):
        if s["match_id"] not in gezien:
            gezien.add(s["match_id"])
            schoon.append(s)
    return schoon


def gecachete_records(cache: Path = CACHE) -> dict[int, dict]:
    if not cache.exists():
        return {}
    uit = {}
    for pad in cache.glob("*.json"):
        try:
            uit[int(pad.stem)] = json.loads(pad.read_text("utf-8"))
        except (ValueError, json.JSONDecodeError):
            continue
    return uit


# ─── Zelftest ────────────────────────────────────────────────────────────────

def zelftest() -> int:
    goed = fout = 0

    def toets(wat, kreeg, verwacht):
        nonlocal goed, fout
        if kreeg == verwacht:
            goed += 1
            print(f"  ✓ {wat}")
        else:
            fout += 1
            print(f"  ✗ {wat}\n      kreeg:    {kreeg!r}\n      verwacht: {verwacht!r}")

    print("── toevoegen ──")
    s, nieuw = voeg_toe([], 111, "PSV - Ajax", "2024-01-01", vandaag="2026-09-17")
    toets("een lege lijst krijgt zijn eerste wedstrijd", ids(s), [111])
    toets("met label en datum", (s[0]["label"], s[0]["date"]), ("PSV - Ajax", "2024-01-01"))
    toets("en een datum van toevoegen", s[0]["toegevoegd"], "2026-09-17")

    s2, nieuw2 = voeg_toe(s, 111, vandaag="2026-09-17")
    toets("dezelfde wedstrijd nog eens verandert niets", ids(s2), [111])
    toets("en meldt dat hij niet nieuw was", nieuw2, False)
    toets("de eerste keer meldde wel nieuw", nieuw, True)

    s3, _ = voeg_toe(s, "111", vandaag="2026-09-17")
    toets("een id als tekst is dezelfde wedstrijd", ids(s3), [111])

    s4, _ = voeg_toe(s, 222, "NEC - PSV", "2023-01-01", vandaag="2026-09-17")
    toets("een tweede wedstrijd komt erbij", sorted(ids(s4)), [111, 222])

    print("\n── verwijderen ──")
    weg, gelukt = verwijder(s4, 111)
    toets("verwijderen haalt hem eruit", ids(weg), [222])
    toets("en meldt dat het gelukt is", gelukt, True)
    _, mis = verwijder(s4, 999)
    toets("een onbekend id verwijderen is geen fout", mis, False)

    print("\n── uit de koppeling ──")
    mapping = {"1001": {"tm_match_id": 4361105, "date": "2024-03-30",
                        "sofascore_label": "NEC - PSV"},
               "1002": {"tm_match_id": 4361106, "date": "2025-02-05",
                        "sofascore_label": "PSV - Feyenoord"}}
    records = {4361105: {"date": "2024-03-30",
                         "home_team": {"name": "NEC Nijmegen"},
                         "away_team": {"name": "PSV Eindhoven"}}}
    sel = uit_koppeling(mapping, records)
    toets("elke koppeling wordt een selectieregel", len(sel), 2)
    toets("op datum gesorteerd", [s["date"] for s in sel],
          ["2024-03-30", "2025-02-05"])
    toets("het label komt uit het Transfermarkt-record als dat er is",
          sel[0]["label"], "NEC Nijmegen - PSV Eindhoven")
    toets("en anders uit de koppeling", sel[1]["label"], "PSV - Feyenoord")
    toets("de Sofascore-herkomst blijft bewaard", sel[0]["sofascore_id"], 1001)
    toets("met de migratie als bron", sel[0]["bron"], "sofascore-migratie")

    # Twee Sofascore-ID's die naar dezelfde Transfermarkt-wedstrijd wijzen mogen
    # er niet twee van maken; dan telt het dashboard hem dubbel.
    dubbel = {"1": {"tm_match_id": 500, "date": "2024-01-01", "sofascore_label": "A - B"},
              "2": {"tm_match_id": 500, "date": "2024-01-01", "sofascore_label": "A - B"}}
    toets("twee koppelingen naar één wedstrijd geven één regel",
          len(uit_koppeling(dubbel, {})), 1)

    print("\n── bewaren en teruglezen ──")
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        pad = Path(d) / "sel.json"
        toets("een bestand dat er niet is leest als leeg", lees(pad), [])
        schrijf(s4, pad)
        terug = lees(pad)
        toets("wat erin gaat komt eruit", sorted(ids(terug)), [111, 222])
        toets("op datum, oudste eerst", [t["date"] for t in terug],
              ["2023-01-01", "2024-01-01"])

    print(f"\n  alles goed ({goed})" if not fout else f"\n  {fout} fout, {goed} goed")
    return 1 if fout else 0


def main():
    p = argparse.ArgumentParser(
        description="Beheer de Transfermarkt-lijst van geziene wedstrijden")
    p.add_argument("--seed", action="store_true",
                   help="vul de selectie uit data/tm_match_map.json")
    p.add_argument("--lijst", action="store_true", help="toon de selectie")
    p.add_argument("--toevoegen", type=int, metavar="TM_ID")
    p.add_argument("--verwijderen", type=int, metavar="TM_ID")
    p.add_argument("--zelftest", action="store_true")
    args = p.parse_args()

    if args.zelftest:
        raise SystemExit(zelftest())

    if args.seed:
        if not MATCH_MAP.exists():
            raise SystemExit(f"  {MATCH_MAP} ontbreekt — draai eerst "
                             f"transfermarkt_map.py --map")
        if SELECTIE.exists():
            raise SystemExit(f"  {SELECTIE} bestaat al ({len(lees())} wedstrijden) — "
                             f"seeden zou je eigen toevoegingen overschrijven.\n"
                             f"  Verwijder hem eerst met de hand als dat de bedoeling is.")
        mapping = json.loads(MATCH_MAP.read_text("utf-8"))
        sel = uit_koppeling(mapping, gecachete_records())
        schrijf(sel)
        met_label = sum(1 for s in sel if s["label"])
        print(f"  ✓ {SELECTIE} geschreven ({len(sel)} wedstrijden, "
              f"{met_label} met een naam uit Transfermarkt)")
        print(f"    Vanaf nu is dit de bron. {MATCH_MAP} is nog slechts herkomst.")
        raise SystemExit(0)

    if args.toevoegen or args.verwijderen:
        sel = lees()
        if args.toevoegen:
            r = gecachete_records().get(args.toevoegen) or {}
            thuis = (r.get("home_team") or {}).get("name")
            uit_ = (r.get("away_team") or {}).get("name")
            sel, nieuw = voeg_toe(sel, args.toevoegen,
                                  f"{thuis} - {uit_}" if thuis and uit_ else "",
                                  r.get("date", ""))
            print(f"  {'✓ toegevoegd' if nieuw else '· stond er al'}: {args.toevoegen}")
        else:
            sel, weg = verwijder(sel, args.verwijderen)
            print(f"  {'✓ verwijderd' if weg else '· stond er niet in'}: "
                  f"{args.verwijderen}")
        schrijf(sel)
        print(f"    {len(sel)} wedstrijden in {SELECTIE}")
        raise SystemExit(0)

    sel = lees()
    if not sel:
        raise SystemExit(f"  {SELECTIE} is leeg of ontbreekt — "
                         f"draai --seed om hem uit de koppeling te vullen")
    print(f"\n  {len(sel)} wedstrijden in {SELECTIE}")
    herkomst: dict[str, int] = {}
    for s in sel:
        herkomst[s.get("bron", "?")] = herkomst.get(s.get("bron", "?"), 0) + 1
    for bron, n in sorted(herkomst.items()):
        print(f"    {n:>4}  {bron}")
    print()
    for s in sel[-15:]:
        print(f"    {s.get('date', '?'):<12} {s['match_id']:>9}  {s.get('label', '')}")
    if len(sel) > 15:
        print(f"    ... en nog {len(sel) - 15} eerder")


if __name__ == "__main__":
    main()
